"""Typed events and measured results for the concurrent Jira demonstration."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Evaluation, Example, Probability


class JiraTicket(Example):
    """A fictional Jira issue, using its issue key as the unique identifier."""


class BatchRequest(BaseModel):
    """An explicit, bounded set of tickets to evaluate concurrently."""

    model_config = ConfigDict(extra="forbid")
    ticket_ids: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=1, max_length=20
    )
    concurrency: int = Field(default=20, ge=1, le=20, strict=True)
    threshold: Probability = 0.8

    @model_validator(mode="after")
    def unique_tickets(self) -> Self:
        """Reject duplicate issue keys so row identity and completed counts remain unambiguous."""
        if len(set(self.ticket_ids)) != len(self.ticket_ids):
            raise ValueError("Choose each ticket only once per batch.")
        return self


class BatchSummary(BaseModel):
    """Observed batch throughput and successful upstream request latency statistics."""

    total: int
    succeeded: int
    failed: int
    elapsed_ms: float
    tickets_per_second: float
    p50_ms: float | None
    p95_ms: float | None
    max_in_flight: int
    input_tokens: int
    output_tokens: int
    model: str | None
    concurrency: int
    estimated_cost_usd: float | None = None


class BatchStarted(BaseModel):
    """Announce the effective worker count before any upstream results arrive."""

    type: Literal["started"] = "started"
    total: int
    concurrency: int


class TicketStarted(BaseModel):
    """Record the moment a worker begins evaluating a ticket."""

    type: Literal["ticket_started"] = "ticket_started"
    ticket_id: str
    started_ms: float
    active: int


class TicketCompleted(BaseModel):
    """A successful live evaluation with its position on the batch timeline."""

    type: Literal["ticket_completed"] = "ticket_completed"
    ticket_id: str
    started_ms: float
    finished_ms: float
    evaluation: Evaluation


class TicketFailed(BaseModel):
    """An explicit ticket failure; errors are not replaced with generated decisions."""

    type: Literal["ticket_failed"] = "ticket_failed"
    ticket_id: str
    started_ms: float
    finished_ms: float
    error: str


class BatchFinished(BaseModel):
    """The final server-measured summary after every requested ticket has settled."""

    type: Literal["finished"] = "finished"
    summary: BatchSummary


type BatchEvent = BatchStarted | TicketStarted | TicketCompleted | TicketFailed | BatchFinished

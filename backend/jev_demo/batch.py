"""Stream real Jev evaluations from a bounded, cancellable Python worker pool."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from math import ceil
from statistics import median
from time import perf_counter

import httpx
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .batch_models import (
    BatchEvent,
    BatchFinished,
    BatchRequest,
    BatchStarted,
    BatchSummary,
    JiraTicket,
    TicketCompleted,
    TicketFailed,
    TicketStarted,
)
from .catalog import SCENARIOS
from .models import EvaluateRequest
from .pricing import estimate_cost_usd
from .service import JevError, Settings, evaluate


class BatchStreamingResponse(StreamingResponse):
    """Close the worker-owning generator even when sending a chunk fails."""

    def __init__(self, stream: AsyncGenerator[str]) -> None:
        """Retain the closeable stream and disable intermediary response buffering."""
        self._stream = stream
        super().__init__(
            stream,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Ensure an ASGI disconnect cannot leave Jev work detached from its request."""
        async with aclosing(self._stream):
            await super().__call__(scope, receive, send)


async def stream_batch(
    client: httpx.AsyncClient,
    settings: Settings,
    request: BatchRequest,
    tickets: list[JiraTicket],
) -> AsyncGenerator[str]:
    """Yield NDJSON progress and cancel owned tasks when the consumer disconnects."""
    worker_count = min(request.concurrency, len(tickets))
    events: asyncio.Queue[BatchEvent] = asyncio.Queue()
    pending = iter(tickets)
    active = 0
    maximum_active = 0
    succeeded = 0
    failed = 0
    input_tokens = 0
    output_tokens = 0
    latencies: list[float] = []
    models: set[str] = set()
    started = perf_counter()

    def offset_ms() -> float:
        """Measure an event's position relative to the batch's monotonic start time."""
        return round((perf_counter() - started) * 1000, 3)

    async def worker() -> None:
        """Process queued tickets serially within one worker, sharing the HTTP pool."""
        nonlocal active, maximum_active, succeeded, failed, input_tokens, output_tokens
        for ticket in pending:
            active += 1
            maximum_active = max(maximum_active, active)
            ticket_start = offset_ms()
            await events.put(
                TicketStarted(ticket_id=ticket.id, started_ms=ticket_start, active=active)
            )
            try:
                evaluation = await evaluate(
                    client,
                    settings,
                    SCENARIOS["triage"],
                    EvaluateRequest(
                        scenario_id="triage", text=ticket.text, threshold=request.threshold
                    ),
                )
            except JevError as exc:
                failed += 1
                await events.put(
                    TicketFailed(
                        ticket_id=ticket.id,
                        started_ms=ticket_start,
                        finished_ms=offset_ms(),
                        error=exc.message,
                    )
                )
            except Exception:
                failed += 1
                await events.put(
                    TicketFailed(
                        ticket_id=ticket.id,
                        started_ms=ticket_start,
                        finished_ms=offset_ms(),
                        error="The ticket could not be evaluated. No routing decision was made.",
                    )
                )
            else:
                succeeded += 1
                input_tokens += evaluation.response.usage.input_tokens
                output_tokens += evaluation.response.usage.output_tokens
                latencies.append(evaluation.elapsed_ms)
                models.add(evaluation.response.model)
                await events.put(
                    TicketCompleted(
                        ticket_id=ticket.id,
                        started_ms=ticket_start,
                        finished_ms=offset_ms(),
                        evaluation=evaluation,
                    )
                )
            finally:
                active -= 1

    async def process() -> None:
        """Own all workers and emit a summary after their actual completion."""
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        try:
            await asyncio.gather(*workers)
            elapsed = (perf_counter() - started) * 1000
            ordered = sorted(latencies)
            model = next(iter(models)) if len(models) == 1 else None
            await events.put(
                BatchFinished(
                    summary=BatchSummary(
                        total=len(tickets),
                        succeeded=succeeded,
                        failed=failed,
                        elapsed_ms=round(elapsed, 3),
                        tickets_per_second=round(succeeded * 1000 / elapsed, 3) if elapsed else 0,
                        p50_ms=median(latencies) if latencies else None,
                        p95_ms=ordered[ceil(0.95 * len(ordered)) - 1] if ordered else None,
                        max_in_flight=maximum_active,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=model,
                        concurrency=worker_count,
                        estimated_cost_usd=estimate_cost_usd(model, input_tokens),
                    )
                )
            )
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    coordinator = asyncio.create_task(process())
    try:
        yield BatchStarted(total=len(tickets), concurrency=worker_count).model_dump_json() + "\n"
        while True:
            event = await events.get()
            yield event.model_dump_json() + "\n"
            if isinstance(event, BatchFinished):
                break
    finally:
        coordinator.cancel()
        await asyncio.gather(coordinator, return_exceptions=True)

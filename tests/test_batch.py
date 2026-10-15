"""Verify real concurrency, measured summaries, and cancellation without network access."""

import asyncio
from collections import Counter
from collections.abc import Callable, Coroutine
from itertools import count

import httpx
import pytest
from pydantic import SecretStr, TypeAdapter
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope
from test_workbench import DUMMY_KEY, PRIVATE_ERROR, answer, mock_client, never_request

from jev_demo import batch, service
from jev_demo.batch import BatchStreamingResponse, stream_batch
from jev_demo.batch_models import (
    BatchEvent,
    BatchFinished,
    BatchRequest,
    BatchStarted,
    JiraTicket,
    TicketCompleted,
    TicketFailed,
    TicketStarted,
)
from jev_demo.models import JevRequest
from jev_demo.service import Settings
from jev_demo.tickets import TICKETS

EVENT: TypeAdapter[BatchEvent] = TypeAdapter(BatchEvent)
type AsyncHandler = Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]


def settings() -> Settings:
    """Construct dummy configuration without reading local environment files."""
    return Settings.model_construct(
        typesafe_api_key=SecretStr(DUMMY_KEY), typesafe_model="jev-latest"
    )


async def collect(
    handler: AsyncHandler, *, ticket_count: int, concurrency: int
) -> list[BatchEvent]:
    """Consume a bounded NDJSON stream using an isolated mocked provider."""
    tickets = TICKETS[:ticket_count]
    request = BatchRequest(
        ticket_ids=[ticket.id for ticket in tickets], concurrency=concurrency, threshold=0.93
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        lines = [line async for line in stream_batch(client, settings(), request, tickets)]
    assert all(line.endswith("\n") and len(line.splitlines()) == 1 for line in lines)
    assert DUMMY_KEY not in "".join(lines)
    assert PRIVATE_ERROR not in "".join(lines)
    return [EVENT.validate_json(line) for line in lines]


@pytest.mark.parametrize(("concurrency", "ticket_count"), [(1, 6), (3, 6), (20, 6), (20, 20)])
def test_workers_overlap_and_settle_each_ticket_once(concurrency: int, ticket_count: int) -> None:
    """An event barrier proves overlapping requests without latency-based assertions."""

    async def exercise() -> None:
        """Hold the first worker group until every expected request is in flight."""
        expected_workers = min(concurrency, ticket_count)
        active = 0
        maximum_active = 0
        started: list[str] = []
        first_group_ready = asyncio.Event()

        async def respond(request: httpx.Request) -> httpx.Response:
            """Block until the whole first group overlaps, while enforcing the bound."""
            nonlocal active, maximum_active
            started.append(JevRequest.model_validate_json(request.content).state)
            active += 1
            maximum_active = max(active, maximum_active)
            assert active <= expected_workers
            if active == expected_workers:
                first_group_ready.set()
            try:
                await first_group_ready.wait()
                return httpx.Response(200, json=answer().model_dump(mode="json"))
            finally:
                active -= 1

        events = await asyncio.wait_for(
            collect(respond, ticket_count=ticket_count, concurrency=concurrency), timeout=5
        )
        assert isinstance(events[0], BatchStarted)
        assert events[0].concurrency == expected_workers
        assert isinstance(events[-1], BatchFinished)
        assert events[-1].summary.max_in_flight == maximum_active == expected_workers
        assert events[-1].summary.concurrency == expected_workers
        assert events[-1].summary.succeeded == ticket_count
        assert events[-1].summary.failed == 0
        assert events[-1].summary.estimated_cost_usd is None
        assert active == 0
        assert Counter(started) == Counter(ticket.text for ticket in TICKETS[:ticket_count])
        starts = [event for event in events if isinstance(event, TicketStarted)]
        completions = [event for event in events if isinstance(event, TicketCompleted)]
        expected_ids = Counter(ticket.id for ticket in TICKETS[:ticket_count])
        assert Counter(event.ticket_id for event in starts) == expected_ids
        assert Counter(event.ticket_id for event in completions) == expected_ids
        assert all(1 <= event.active <= expected_workers for event in starts)
        assert all(event.finished_ms >= event.started_ms for event in completions)
        assert all(event.evaluation.decision.action == "review" for event in completions)
        assert not any(isinstance(event, TicketFailed) for event in events)

    asyncio.run(exercise())


def test_summary_measures_successful_latencies_throughput_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reported metrics use wall time, the median, and nearest-rank p95 of successes."""
    batch_ticks = count(step=0.025)
    request_ticks = iter(
        tick for index in range(20) for tick in (float(index), index + (index + 1) / 1000)
    )

    def batch_clock() -> float:
        """Provide deterministic elapsed time independent of machine performance."""
        return next(batch_ticks)

    def request_clock() -> float:
        """Produce twenty successful request durations from one to twenty milliseconds."""
        return next(request_ticks)

    async def respond(_request: httpx.Request) -> httpx.Response:
        """Return the same token usage for every successful request."""
        return httpx.Response(200, json=answer(model="jev-1.13.0").model_dump(mode="json"))

    monkeypatch.setattr(batch, "perf_counter", batch_clock)
    monkeypatch.setattr(service, "perf_counter", request_clock)
    events = asyncio.run(collect(respond, ticket_count=20, concurrency=1))
    final = events[-1]
    assert isinstance(final, BatchFinished)
    summary = final.summary
    assert summary.total == summary.succeeded == 20
    assert summary.failed == 0
    assert summary.elapsed_ms == 1025
    assert summary.tickets_per_second == round(20 / 1.025, 3)
    assert summary.p50_ms == 10.5
    assert summary.p95_ms == 19
    assert summary.input_tokens == 20 * 123
    assert summary.output_tokens == 20 * 17
    assert summary.model == "jev-1.13.0"
    assert summary.estimated_cost_usd == pytest.approx(0.00010332)


@pytest.mark.parametrize("all_fail", [False, True])
def test_failed_requests_never_produce_decisions_or_inflate_success_metrics(
    all_fail: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP and malformed-response failures remain explicit and excluded from success metrics."""
    failing_states = {ticket.text for ticket in (TICKETS[:4] if all_fail else TICKETS[:2])}
    requests: list[str] = []
    batch_ticks = count(step=0.025)

    def batch_clock() -> float:
        """Keep throughput assertions independent of clock rounding on a fast machine."""
        return next(batch_ticks)

    async def respond(request: httpx.Request) -> httpx.Response:
        """Mix safe successes with private error bodies that must not reach the stream."""
        state = JevRequest.model_validate_json(request.content).state
        requests.append(state)
        if state in failing_states:
            status = 200 if state == TICKETS[0].text else 503
            return httpx.Response(status, text=f"{PRIVATE_ERROR} Bearer {DUMMY_KEY}")
        return httpx.Response(200, json=answer(model="jev-1.13.0").model_dump(mode="json"))

    monkeypatch.setattr(batch, "perf_counter", batch_clock)
    events = asyncio.run(collect(respond, ticket_count=4, concurrency=2))
    successes = [event for event in events if isinstance(event, TicketCompleted)]
    failures = [event for event in events if isinstance(event, TicketFailed)]
    final = events[-1]
    assert isinstance(final, BatchFinished)
    summary = final.summary
    assert summary.total == 4
    assert summary.failed == len(failures) == len(failing_states)
    assert summary.succeeded == len(successes) == 4 - len(failing_states)
    assert len(requests) == 4
    assert all("evaluation" not in event.model_dump() for event in failures)
    assert Counter(event.ticket_id for event in [*successes, *failures]) == Counter(
        ticket.id for ticket in TICKETS[:4]
    )
    assert summary.input_tokens == len(successes) * 123
    assert summary.output_tokens == len(successes) * 17
    if all_fail:
        assert summary.p50_ms is summary.p95_ms is summary.model is None
        assert summary.tickets_per_second == 0
        assert summary.estimated_cost_usd is None
    else:
        assert summary.estimated_cost_usd == pytest.approx(0.000010332)
        assert summary.p50_ms is not None
        assert summary.p95_ms == max(event.evaluation.elapsed_ms for event in successes)
        expected = summary.succeeded * 1000 / summary.elapsed_ms
        assert summary.tickets_per_second == round(expected, 3)


@pytest.mark.parametrize("send_failure", [False, True])
def test_disconnect_cancels_requests_and_does_not_start_queued_tickets(
    send_failure: bool,
) -> None:
    """Generator close and ASGI send failures cancel owned requests before returning."""

    async def exercise() -> None:
        """Close after two requests are in flight while four tickets remain queued."""
        started: list[str] = []
        cancelled: list[str] = []
        running = asyncio.Event()
        blocked = asyncio.Event()

        async def respond(request: httpx.Request) -> httpx.Response:
            """Wait indefinitely until generator cleanup cancels the owned request."""
            state = JevRequest.model_validate_json(request.content).state
            started.append(state)
            if len(started) == 2:
                running.set()
            try:
                await blocked.wait()
            except asyncio.CancelledError:
                cancelled.append(state)
                raise
            raise AssertionError("A cancelled request must not complete.")

        async def send(message: Message) -> None:
            """Fail sending a body chunk once the worker pool is demonstrably running."""
            if message["type"] == "http.response.body":
                await running.wait()
                raise OSError("Client closed the connection.")

        async def receive() -> Message:
            """ASGI 2.4 handles this disconnect through the failing send operation."""
            raise AssertionError("This ASGI version should not listen for disconnect messages.")

        request = BatchRequest(ticket_ids=[ticket.id for ticket in TICKETS[:6]], concurrency=2)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            stream = stream_batch(client, settings(), request, TICKETS[:6])
            if send_failure:
                scope: Scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
                with pytest.raises(ClientDisconnect):
                    await asyncio.wait_for(
                        BatchStreamingResponse(stream)(scope, receive, send), timeout=5
                    )
            else:
                try:
                    assert isinstance(EVENT.validate_json(await anext(stream)), BatchStarted)
                    await asyncio.wait_for(running.wait(), timeout=5)
                finally:
                    await asyncio.wait_for(stream.aclose(), timeout=5)
        assert len(started) == len(cancelled) == 2
        assert Counter(started) == Counter(cancelled)

    asyncio.run(exercise())


@pytest.mark.parametrize("concurrency", [0, 21, True, 1.5, "3"])
def test_invalid_concurrency_is_rejected_before_upstream(concurrency: object) -> None:
    """Concurrency must be a bounded integer rather than a coerced string or boolean."""
    with mock_client(never_request) as client:
        response = client.post(
            "/api/triage/batch",
            json={"ticket_ids": [TICKETS[0].id], "concurrency": concurrency},
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("ticket_ids", "key", "expected_status"),
    [
        ([TICKETS[0].id, TICKETS[0].id], DUMMY_KEY, 422),
        (["UNKNOWN-000"], DUMMY_KEY, 404),
        ([TICKETS[0].id], "", 503),
        ([], DUMMY_KEY, 422),
    ],
)
def test_invalid_batches_are_rejected_before_upstream(
    ticket_ids: list[str], key: str, expected_status: int
) -> None:
    """Duplicates, unknown tickets, empty batches, and missing credentials cannot spend calls."""
    with mock_client(never_request, key=key) as client:
        response = client.post("/api/triage/batch", json={"ticket_ids": ticket_ids})
    assert response.status_code == expected_status


def test_batch_endpoint_returns_typed_ndjson_and_twenty_unique_samples() -> None:
    """The public endpoint exposes real stream events and its complete sample catalog."""

    def respond(_request: httpx.Request) -> httpx.Response:
        """Return a valid provider answer without external access."""
        return httpx.Response(200, json=answer().model_dump(mode="json"))

    with mock_client(respond) as client:
        response = client.post(
            "/api/triage/batch", json={"ticket_ids": [TICKETS[0].id], "concurrency": 8}
        )
        samples = client.get("/api/triage/tickets")
    assert response.status_code == samples.status_code == 200
    assert response.headers["Content-Type"].startswith("application/x-ndjson")
    assert response.headers["Cache-Control"] == "no-store"
    events = [EVENT.validate_json(line) for line in response.iter_lines()]
    assert [event.type for event in events] == [
        "started",
        "ticket_started",
        "ticket_completed",
        "finished",
    ]
    assert len(TICKETS) == len({ticket.id for ticket in TICKETS}) == 20
    assert TypeAdapter(list[JiraTicket]).validate_json(samples.content) == TICKETS

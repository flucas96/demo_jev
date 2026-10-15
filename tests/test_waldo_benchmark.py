"""Check gateway transport, honest billing, one-shot scoring, and durable paired rounds."""

import asyncio
import base64
import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from jev_demo import waldo
from jev_demo import waldo_gateway as gateway
from jev_demo.app import create_app
from jev_demo.models import Usage
from jev_demo.service import JevError, Settings
from jev_demo.waldo import Box, Match
from jev_demo.waldo_history import Comparison, History, Run


def config(path: Path | None = None) -> Settings:
    """Keep tests independent of real credentials and production history."""
    return Settings(
        typesafe_api_key=SecretStr("test-typesafe"),
        ai_gateway_api_key=SecretStr("test-gateway"),
        ai_gateway_base_url="https://gateway.test/v1",
        waldo_history_path=path,
    )


def completion(content: str = '{"left":0.1,"top":0.2,"right":0.3,"bottom":0.4}'):
    """Provide the observed OpenAI-compatible gateway response shape."""
    return {
        "model": gateway.DEFAULT_MODEL,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 40},
    }


@pytest.mark.parametrize("cost", [None, "0.01234"])
def test_gateway_uses_exact_image_and_real_usage(cost: str | None) -> None:
    """No scoring hints enter the prompt; reported cost takes precedence over list pricing."""
    image = b"fixture-image"

    def handler(request: httpx.Request) -> httpx.Response:
        """Inspect the outbound contract without contacting the provider."""
        assert str(request.url) == "https://gateway.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-gateway"
        payload = TypeAdapter(dict[str, object]).validate_json(request.content)
        assert payload["model"] == gateway.DEFAULT_MODEL
        assert payload["messages"] == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": gateway.PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64," + base64.b64encode(image).decode()
                        },
                    },
                ],
            }
        ]
        return httpx.Response(
            200, json=completion(), headers={"x-litellm-response-cost": cost} if cost else {}
        )

    async def run() -> gateway.Localization:
        """Exercise the async adapter using the real request builder."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await gateway.infer(client, config(), gateway.DEFAULT_MODEL, image)

    result = asyncio.run(run())
    assert result.box == Box(left=0.1, top=0.2, right=0.3, bottom=0.4)
    assert result.confidence is None
    assert result.usage == Usage(input_tokens=2000, output_tokens=40)
    assert result.cost_usd == pytest.approx(float(cost) if cost else 0.0121)
    assert result.cost_basis == ("gateway" if cost else "estimate")


@pytest.mark.parametrize("value", ["NaN", "inf", "-0.5", "invalid"])
def test_invalid_billing_header_cannot_pollute_totals(value: str) -> None:
    """Only finite nonnegative gateway costs may enter stored results."""
    assert (
        gateway.response_cost(httpx.Response(200, headers={"x-litellm-response-cost": value}))
        is None
    )


def test_invalid_model_geometry_is_a_paid_miss_then_moves_immediately() -> None:
    """A malformed answer costs a point and retains its usage, without a hidden retry."""

    async def run() -> gateway.Localization:
        """Return a syntactically valid completion containing an impossible box."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=completion('{"left":2}'))
            )
        ) as client:
            return await gateway.infer(client, config(), gateway.DEFAULT_MODEL, b"image")

    result = asyncio.run(run())
    assert result.box is None
    match = Match(15, "sprint", 42, 100)
    match.calls = 1
    match.record_result(result)
    assert match.submit("jev", 0, result.box, 101, invalid_answer=True)
    match.tick(101)
    assert match.players["jev"].round == 1
    assert match.players["jev"].misses == 1
    assert match.players["jev"].score == -1
    assert match.cost > 0


def test_unknown_usage_is_not_presented_as_zero_cost() -> None:
    """Missing billing and tokens produce an unknown total, with an explicit partial flag."""
    match = Match(15, "sprint", 42, 100)
    match.calls = 1
    match.record_result(gateway.Localization("model", None, None, None, 200, None, "unknown"))
    assert match.result().cost_usd is None
    assert match.result().cost_partial


def test_gateway_errors_never_expose_response_bodies() -> None:
    """Provider errors can contain credentials or internals, so only safe messages escape."""

    async def run() -> None:
        """Simulate an authorization failure with a deliberately sensitive response body."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(403, text="test-gateway PRIVATE DETAILS")
            )
        ) as client:
            await gateway.infer(client, config(), gateway.DEFAULT_MODEL, b"image")

    with pytest.raises(JevError) as failure:
        asyncio.run(run())
    assert "test-gateway" not in failure.value.message
    assert "PRIVATE" not in failure.value.message


def completed_run(pair: Comparison, stage: int) -> Run:
    """Build a server-scored result using the same image order for both competitors."""
    match = Match(
        pair.duration,
        "sprint",
        pair.seed,
        100,
        comparison_id=pair.id,
        stage=stage,
        requested_model=pair.model if stage == 1 else waldo.MODEL,
    )
    match.calls = 1
    box = match.puzzle("jev").reference
    match.record_result(gateway.Localization(pair.model, box, None, None, 300, 0.01, "gateway"))
    assert match.submit("jev", 0, box, 101)
    match.tick(100 + pair.duration)
    return match.result()


def test_history_survives_restart_and_advances_only_completed_rounds(tmp_path: Path) -> None:
    """A duplicate result cannot advance twice; interrupted rounds remain resumable."""
    path = tmp_path / "history.sqlite3"
    history = History(path)
    pair = history.create(gateway.DEFAULT_MODEL, 15, waldo.deck_fingerprint())
    first = completed_run(pair, 1)
    history.save(first)
    history.save(first)
    restored = History(path).get(pair.id)
    assert restored and restored.next_stage == 2
    assert (restored.seed, restored.duration, restored.deck) == (pair.seed, 15, pair.deck)
    stopped = completed_run(pair, 2).model_copy(update={"status": "stopped"})
    history.save(stopped)
    assert history.get(pair.id) == restored
    second = completed_run(pair, 2)
    history.save(second)
    finished = history.get(pair.id)
    assert finished and finished.next_stage == 3
    assert len(history.runs()) == 3
    assert first.seed == second.seed
    assert first.deck == second.deck


def test_routes_filter_models_and_reject_phase_skips_and_changed_references(tmp_path: Path) -> None:
    """Accessible vision models only; comparison order and deck are controlled by the server."""
    path = tmp_path / "history.sqlite3"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "data": [
                    {"id": gateway.DEFAULT_MODEL},
                    {"id": "text-embedding-3-large"},
                ]
            },
        )
    )
    with TestClient(create_app(config(path), transport)) as test_client:
        client = cast(httpx.Client, test_client)
        models = client.get("/api/waldo/models")
        assert gateway.DEFAULT_MODEL in models.text
        assert "text-embedding" not in models.text
        assert "test-gateway" not in models.text
        assert client.post("/api/waldo/comparisons", json={"model": "unknown"}).status_code == 422
        created = client.post(
            "/api/waldo/comparisons", json={"model": gateway.DEFAULT_MODEL, "duration": 15}
        )
        assert created.status_code == 200
        pair = Comparison.model_validate_json(created.content)
        with test_client.websocket_connect(
            f"/api/waldo/play?comparison_id={pair.id}&stage=2"
        ) as ws:
            assert (
                TypeAdapter(dict[str, object]).validate_python(ws.receive_json())["type"] == "error"
            )
        pair.deck = "changed"
        with History(path).connection() as connection:
            _ = connection.execute(
                "UPDATE comparisons SET payload = ? WHERE id = ?", (pair.model_dump_json(), pair.id)
            )
        with test_client.websocket_connect(
            f"/api/waldo/play?comparison_id={pair.id}&stage=1"
        ) as ws:
            assert "references" in json.dumps(ws.receive_json())
        assert client.get("/api/waldo/leaderboard").text == "[]"


def test_background_always_changes_and_order_is_seeded() -> None:
    """Background changes also hold at the deck boundary, with every asset retained once."""
    puzzles = waldo.playable_puzzles("sprint")
    for seed in range(100):
        course = waldo.shuffled_course(puzzles, seed)
        assert {p.id for p in course} == {p.id for p in puzzles}
        assert len(course) == len(puzzles)
        assert all(
            a.background != b.background
            for a, b in zip(course, course[1:] + course[:1], strict=True)
        )
    assert waldo.shuffled_course(puzzles, 42) == waldo.shuffled_course(puzzles, 42)
    assert waldo.shuffled_course(puzzles, 42) != waldo.shuffled_course(puzzles, 43)


def test_normal_mode_selects_gateway_directly_without_a_second_round(tmp_path: Path) -> None:
    """A standalone gateway round has no forced Jev follow-up and cancels safely."""
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """Expose a model and leave its image call pending until the user stops."""
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": gateway.DEFAULT_MODEL}]})
        payload = TypeAdapter(dict[str, object]).validate_json(request.content)
        requests.append(str(payload["model"]))
        await asyncio.Event().wait()
        return httpx.Response(200, json=completion())

    settings = config(tmp_path / "solo.sqlite3")
    settings.typesafe_api_key = SecretStr("")
    with (
        TestClient(create_app(settings, httpx.MockTransport(handler))) as client,
        client.websocket_connect(
            f"/api/waldo/play?duration=15&model={gateway.DEFAULT_MODEL}"
        ) as ws,
    ):
        first = TypeAdapter(dict[str, object]).validate_python(ws.receive_json())
        assert first["type"] == "state"
        assert first["model_label"] == "Claude Opus 5"
        assert first["comparison_id"] is None
        ws.send_json({"type": "stop"})
        while True:
            state = TypeAdapter(dict[str, object]).validate_python(ws.receive_json())
            if state["ended"]:
                assert state["status"] == "stopped"
                break
    assert requests == [gateway.DEFAULT_MODEL]

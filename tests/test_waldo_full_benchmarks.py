"""Verify the all-model benchmark uses game scoring and never rewards late responses."""

import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from jev_demo import waldo, waldo_benchmarks
from jev_demo.app import create_app
from jev_demo.service import JevError, Settings
from jev_demo.waldo_gateway import Localization


@pytest.mark.parametrize("late", [False, True])
def test_benchmark_scores_once_and_accounts_for_late_cost(
    monkeypatch: pytest.MonkeyPatch,
    late: bool,
) -> None:
    """The same reference earns a hit only within the deadline, with all returned usage retained."""
    now = [100.0]
    seen: list[str] = []
    match = waldo.Match(2, "sprint", 73, now[0])

    async def inference(
        _client: httpx.AsyncClient,
        _settings: Settings,
        puzzle: waldo.Puzzle,
        _model: str,
    ) -> Localization:
        """Advance a fake monotonic clock rather than waiting or contacting real models."""
        seen.append(puzzle.id)
        now[0] += 3 if late else 1
        return Localization(waldo.MODEL, puzzle.reference, 0.9, None, 1000, 0.01, "estimate")

    async def sleep(delay: float) -> None:
        """Model the game's feedback pause deterministically."""
        assert delay >= 0
        now[0] += delay

    monkeypatch.setattr(waldo_benchmarks, "perf_counter", lambda: now[0])
    monkeypatch.setattr(waldo_benchmarks.asyncio, "sleep", sleep)
    monkeypatch.setattr(waldo, "infer_model", inference)

    async def run() -> waldo_benchmarks.ModelBenchmark:
        """Exercise the production measurement loop without network traffic."""
        async with httpx.AsyncClient() as client:
            return await waldo_benchmarks.measure_model(client, Settings(), match)

    result = asyncio.run(run())
    assert result.status == "completed"
    assert result.run is not None
    assert result.run.score == (0 if late else 1)
    assert result.run.calls == (1 if late else 2)
    assert result.run.cost_usd == pytest.approx(0.01 if late else 0.02)
    assert not result.run.cost_partial
    assert len(seen) == len(set(seen))


def test_failed_model_is_not_published_as_a_completed_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unavailable routes remain explicit errors and do not gain a misleading benchmark dot."""
    match = waldo.Match(60, "sprint", 73, 100)

    async def failure(
        _client: httpx.AsyncClient,
        _settings: Settings,
        _puzzle: waldo.Puzzle,
        _model: str,
    ) -> Localization:
        """Simulate a safe, sanitized upstream failure."""
        raise JevError(502, "The model is unavailable.")

    monkeypatch.setattr(waldo_benchmarks, "perf_counter", lambda: 101)
    monkeypatch.setattr(waldo, "infer_model", failure)

    async def run() -> waldo_benchmarks.ModelBenchmark:
        """Execute the real failure path with no external calls."""
        async with httpx.AsyncClient() as client:
            return await waldo_benchmarks.measure_model(client, Settings(), match)

    result = asyncio.run(run())
    assert result.status == "error"
    assert result.error == "The model is unavailable."
    assert result.run is not None and result.run.cost_partial
    assert result.run.status == "error"


def test_saved_benchmarks_are_read_only_and_independent_of_player_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page visit reads the measured snapshot and needs neither credentials nor inference."""
    path = tmp_path / "benchmarks.json"
    report = waldo_benchmarks.BenchmarkReport(seed=73, deck="fixture", results=[])
    assert waldo_benchmarks.read_report(path) is None
    waldo_benchmarks.save_report(report, path)
    restored = waldo_benchmarks.read_report(path)
    assert restored == report
    monkeypatch.setattr(waldo_benchmarks, "read_report", lambda: restored)
    settings = Settings(
        typesafe_api_key=SecretStr(""),
        ai_gateway_api_key=SecretStr(""),
        waldo_history_path=None,
    )
    with TestClient(create_app(settings)) as test_client:
        response = cast(httpx.Client, test_client).get("/api/waldo/benchmarks")
    assert response.status_code == 200
    assert response.json()["id"] == report.id

"""Measure every accessible image model on one shared timed course, in parallel."""

import asyncio
import os
from pathlib import Path
from secrets import randbelow
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from . import waldo, waldo_gateway
from .service import JevError, Settings
from .waldo_history import Run, timestamp

REPORT_PATH = waldo.ASSETS / "full-benchmarks.json"
DURATION = 60


class ModelBenchmark(BaseModel):
    """Keep failed or unfinished measurements visible without inventing a score."""

    model: str
    label: str
    status: Literal["running", "completed", "error"] = "running"
    run: Run | None = None
    error: str | None = None


class BenchmarkReport(BaseModel):
    """An immutable course definition and one real measurement per model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=timestamp)
    finished_at: str | None = None
    duration: int = DURATION
    seed: int
    deck: str
    parallel: bool = True
    results: list[ModelBenchmark]


def read_report(path: Path = REPORT_PATH) -> BenchmarkReport | None:
    """Read a saved measurement without triggering any paid requests."""
    return BenchmarkReport.model_validate_json(path.read_bytes()) if path.exists() else None


def save_report(report: BenchmarkReport, path: Path = REPORT_PATH) -> None:
    """Replace the snapshot atomically so readers never see a partially written report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".benchmark-", delete=False) as handle:
            temporary = Path(handle.name)
            _ = handle.write(report.model_dump_json(indent=2).encode() + b"\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def measure_model(
    client: httpx.AsyncClient, settings: Settings, match: waldo.Match
) -> ModelBenchmark:
    """Reuse game scoring and cooldowns; bill late responses but never award late points."""
    while not match.ended:
        now = perf_counter()
        match.tick(now)
        if match.ended:
            break
        player = match.players["jev"]
        if player.feedback is not None:
            await asyncio.sleep(min(player.ready_at - now, match.remaining(now)))
            continue
        match.calls += 1
        try:
            result = await waldo.infer_model(
                client, settings, match.puzzle("jev"), match.requested_model
            )
        except JevError as exc:
            match.failures += 1
            match.unpriced += 1
            match.model_error = exc.message
            match.ended = True
            break
        match.record_result(result)
        now = perf_counter()
        match.tick(now)
        _ = match.submit(
            "jev",
            player.round,
            result.box,
            now,
            result.confidence,
            result.elapsed_ms,
            invalid_answer=result.box is None,
        )
    run = match.result()
    return ModelBenchmark(
        model=run.model,
        label=run.label,
        status="completed" if run.status == "completed" else "error",
        run=run,
        error=match.model_error,
    )


async def benchmark(settings: Settings, path: Path = REPORT_PATH) -> BenchmarkReport:
    """Start all models together, keep each sequential, and save every outcome as it finishes."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90, connect=10),
        headers={"Content-Type": "application/json"},
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=30),
    ) as client:
        models = (
            await waldo_gateway.available_models(client, settings)
            if settings.ai_gateway_api_key.get_secret_value()
            else []
        )
        if settings.typesafe_api_key.get_secret_value():
            models.append(
                waldo_gateway.ModelOption(
                    id=waldo.MODEL,
                    label="Jev",
                    input_price=0.042,
                    output_price=0,
                    provider="typesafe",
                )
            )
        if not models:
            raise JevError(503, "No configured image models are available to benchmark.")
        puzzles = waldo.playable_puzzles("sprint")
        for puzzle in puzzles:
            _ = await asyncio.to_thread(waldo.image_bytes, puzzle.id)
        report = BenchmarkReport(
            seed=randbelow(2**31),
            deck=waldo.deck_fingerprint(),
            results=[ModelBenchmark(model=model.id, label=model.label) for model in models],
        )
        await asyncio.to_thread(save_report, report, path)
        matches = [
            waldo.Match(
                report.duration,
                "sprint",
                report.seed,
                0,
                requested_model=model.id,
                model=model.id,
                label=model.label,
            )
            for model in models
        ]
        started = perf_counter()
        for match in matches:
            match.started = started
        lock = asyncio.Lock()

        async def measure(index: int, match: waldo.Match) -> None:
            """Persist safely when concurrent measurements complete in a different order."""
            outcome = await measure_model(client, settings, match)
            async with lock:
                report.results[index] = outcome
                await asyncio.to_thread(save_report, report, path)
            run = outcome.run
            print(
                f"{outcome.label}: {outcome.status}; "
                f"score={run.score if run else '—'}; "
                f"calls={run.calls if run else 0}; {outcome.error or ''}",
                flush=True,
            )

        print(f"Measuring {len(models)} models in parallel for {DURATION}s.", flush=True)
        await asyncio.gather(*(measure(index, match) for index, match in enumerate(matches)))
        report.finished_at = timestamp()
        await asyncio.to_thread(save_report, report, path)
        return report


def main() -> None:
    """Run an explicitly requested paid benchmark using server-only environment credentials."""
    try:
        report = asyncio.run(benchmark(Settings()))
    except JevError as exc:
        raise SystemExit(exc.message) from None
    print(f"Saved {len(report.results)} model measurements to {REPORT_PATH}.")


if __name__ == "__main__":
    main()

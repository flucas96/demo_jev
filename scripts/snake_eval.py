"""Opt-in live comparison of Snake observations; evaluation labels never enter model requests."""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from statistics import median

import httpx
from pydantic import BaseModel

from jev_demo.pricing import estimate_cost_usd
from jev_demo.service import JevError, Settings
from jev_demo.snake import (
    SIZE,
    Cell,
    Direction,
    SnakeRequest,
    SnakeResponse,
    World,
    format_request,
    infer,
)
from jev_demo.snake import ObservationFormat as Variant


@dataclass(frozen=True)
class Case:
    """Store a valid frozen board independently of its presentation."""

    name: str
    snake: tuple[Cell, ...]
    direction: Direction
    food: Cell

    def world(self) -> World:
        """Restore identical physics for each model and offline scoring attempt."""
        world = World(42)
        world.snake = list(self.snake)
        world.direction = self.direction
        world.food = self.food
        return world


VARIANTS = (
    Variant("baseline"),
    Variant("spacing", spacing=True),
    Variant("named_head", named_head=True),
    Variant("coordinates", spacing=True, coordinates=True),
    Variant("explicit_rules", explicit_rules=True),
    Variant("combined_board", True, True, True, True),
    Variant("combined_with_neighbors", True, True, True, True, True),
)
BASE_CASES = (
    Case("food_ahead", ((4, 5), (3, 5), (2, 5)), "right", (7, 5)),
    Case("food_behind", ((7, 4), (6, 4), (5, 4), (4, 4)), "right", (0, 4)),
    Case("wall_turn", ((9, 5), (8, 5), (7, 5)), "right", (9, 1)),
    Case("body_detour", ((4, 4), (4, 5), (5, 5), (5, 4), (5, 3), (4, 3), (3, 3)), "up", (7, 4)),
    Case("tail_exit", ((0, 0), (1, 0), (1, 1), (0, 1)), "left", (0, 4)),
)
DIRECTIONS: tuple[Direction, ...] = ("up", "right", "down", "left")


def rotate(cell: Cell) -> Cell:
    """Rotate coordinates clockwise without changing game difficulty."""
    return SIZE - 1 - cell[1], cell[0]


def cases() -> list[Case]:
    """Cover five situations in all four orientations to reveal directional bias."""
    result: list[Case] = []
    for original in BASE_CASES:
        case = original
        for quarter in range(4):
            result.append(
                Case(f"{original.name}_{quarter * 90}", case.snake, case.direction, case.food)
            )
            direction = DIRECTIONS[(DIRECTIONS.index(case.direction) + 1) % 4]
            case = Case(
                case.name, tuple(rotate(cell) for cell in case.snake), direction, rotate(case.food)
            )
    return result


def make_variant(settings: Settings, case: Case, variant: Variant) -> SnakeRequest:
    """Use the same observation formatter as the live game for reproducible comparisons."""
    return format_request(settings, case.world(), variant)


def outcome(case: Case, direction: Direction) -> tuple[bool, bool]:
    """Measure immediate collision and Manhattan progress offline, not full-game optimality."""
    world = case.world()
    before = sum(abs(a - b) for a, b in zip(case.snake[0], case.food, strict=True))
    world.step(direction)
    legal = world.phase != "lost"
    after = sum(abs(a - b) for a, b in zip(world.snake[0], case.food, strict=True))
    return legal, legal and after < before


class Result(BaseModel):
    """Keep requests and real responses auditable, with evaluator-only labels separate."""

    case: str
    variant: str
    repeat: int
    request: SnakeRequest
    response: SnakeResponse | None = None
    error: str | None = None
    latency_ms: float | None = None
    legal: bool | None = None
    progress: bool | None = None
    progress_possible: bool
    cost_usd: float | None = None


class Summary(BaseModel):
    """Report simple descriptive metrics without claiming statistical significance."""

    variant: str
    calls: int
    responses: int
    errors: int
    legal_moves: int
    progress_moves: int
    progress_opportunities: int
    median_latency_ms: float | None
    input_tokens: int
    estimated_cost_usd: float


class Report(BaseModel):
    """Persist the full experiment without secrets or provider headers."""

    created_at: str
    model: str
    repeats: int
    notes: str
    summaries: list[Summary]
    results: list[Result]


def summarize(results: list[Result]) -> list[Summary]:
    """Group successful decisions and preserve failures as a separate count."""
    summaries: list[Summary] = []
    for variant in VARIANTS:
        rows = [row for row in results if row.variant == variant.name]
        valid = [row for row in rows if row.response is not None]
        latencies = [row.latency_ms for row in valid if row.latency_ms is not None]
        summaries.append(
            Summary(
                variant=variant.name,
                calls=len(rows),
                responses=len(valid),
                errors=len(rows) - len(valid),
                legal_moves=sum(row.legal is True for row in valid),
                progress_moves=sum(row.progress is True for row in valid if row.progress_possible),
                progress_opportunities=sum(row.progress_possible for row in valid),
                median_latency_ms=median(latencies) if latencies else None,
                input_tokens=sum(
                    row.response.usage.input_tokens for row in valid if row.response is not None
                ),
                estimated_cost_usd=sum(row.cost_usd or 0 for row in rows),
            )
        )
    return summaries


async def evaluate(repeats: int, output: Path) -> None:
    """Interleave bounded live requests and checkpoint every response to avoid losing evidence."""
    settings = Settings(typesafe_model="jev-1.13.0")
    jobs = [
        (case, variant, repeat)
        for case in cases()
        for variant in VARIANTS
        for repeat in range(repeats)
    ]
    Random(20260924).shuffle(jobs)
    report = Report(
        created_at=datetime.now(UTC).isoformat(),
        model=settings.typesafe_model,
        repeats=repeats,
        summaries=[],
        results=[],
        notes="20 constructed boards: five situations rotated four ways. Repeats share boards "
        "and are not independent evidence. Legal means no immediate collision. Progress means "
        "a legal move decreasing Manhattan food distance, only where such a move exists. "
        "These metrics do not establish long-horizon planning or full-game performance. "
        "Coordinates include spacing. Combined board uses spacing, head label, coordinates "
        "and explicit rules. Neighbor variant adds factual adjacent-cell contents. "
        "All evaluation labels stay outside requests. Concurrency: 4. No retries.",
    )
    semaphore = asyncio.Semaphore(4)
    checkpoint = asyncio.Lock()
    async with httpx.AsyncClient(
        timeout=30, headers={"Content-Type": "application/json"}
    ) as client:

        async def run(case: Case, variant: Variant, repeat: int) -> None:
            """Capture one inference and score the executed move without modifying it."""
            request = make_variant(settings, case, variant)
            row = Result(
                case=case.name,
                variant=variant.name,
                repeat=repeat,
                request=request,
                progress_possible=any(outcome(case, action)[1] for action in DIRECTIONS),
            )
            async with semaphore:
                try:
                    response, latency = await infer(client, settings, request)
                    row.response, row.latency_ms = response, latency
                    row.legal, row.progress = outcome(case, response.answers.direction.choice)
                    row.cost_usd = estimate_cost_usd(response.model, response.usage.input_tokens)
                except JevError as exc:
                    row.error = exc.message
                async with checkpoint:
                    report.results.append(row)
                    report.summaries = summarize(report.results)
                    await asyncio.to_thread(
                        output.write_text, report.model_dump_json(indent=2) + "\n"
                    )
                    if len(report.results) % 20 == 0:
                        print(f"Completed {len(report.results)}/{len(jobs)} calls", flush=True)

        await asyncio.gather(*(run(*job) for job in jobs))
    print("\n".join(summary.model_dump_json() for summary in report.summaries), flush=True)


def main() -> None:
    """Run a small paid experiment only on explicit invocation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2, choices=range(1, 4))
    args = parser.parse_args()
    output = Path(str(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(evaluate(int(args.repeats), output))


if __name__ == "__main__":
    main()

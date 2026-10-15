"""Opt-in live regression cases for ambiguous runner observations, never run by pytest."""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from jev_demo.runner.inference import infer, make_request
from jev_demo.runner.world import ACTION_SECONDS, Action, Encounter, World
from jev_demo.service import JevError, Settings


@dataclass(frozen=True)
class Case:
    """Define a reproducible snapshot and its independently specified desired move."""

    name: str
    kind: Literal["clear", "crate", "beam"]
    clearance: float
    until_contact: float
    posture: Action
    expected: Action
    jump_remaining: float = 0.8

    def world(self) -> World:
        """Construct a frozen observation without advancing physics or calling an oracle."""
        world = World(1, "jev", "evaluation")
        world.time = 10
        world.action = self.posture
        world.action_started = world.time - (ACTION_SECONDS - self.jump_remaining)
        world.current = Encounter(
            1,
            world.time + self.until_contact - 0.32,
            self.kind,
            30,
            self.clearance,
            104 if self.kind == "beam" else 24 if self.kind == "crate" else 0,
        )
        return world


CASES = (
    Case("clear-upright", "clear", 0, 2, "stand", "stand"),
    Case("clear-ducking", "clear", 0, 2, "duck", "stand"),
    Case("clear-mid-jump", "clear", 0, 2, "jump", "jump"),
    Case("distant-crate", "crate", 0, 2, "stand", "stand"),
    Case("distant-low-screen", "beam", 28, 2, "stand", "stand"),
    Case("near-crate-upright", "crate", 0, 0.65, "stand", "jump"),
    Case("near-crate-ducking", "crate", 0, 0.65, "duck", "jump"),
    Case("near-crate-mid-jump", "crate", 0, 0.2, "jump", "jump"),
    Case("near-low-screen-upright", "beam", 28, 0.65, "stand", "duck"),
    Case("near-low-screen-ducking", "beam", 28, 0.65, "duck", "duck"),
    Case("near-low-screen-mid-jump", "beam", 28, 0.2, "jump", "duck"),
    Case("crossing-low-screen-upright", "beam", 28, -0.1, "stand", "duck"),
    Case("crossing-low-screen-ducking", "beam", 28, -0.1, "duck", "duck"),
    Case("crossing-low-screen-mid-jump", "beam", 28, -0.1, "jump", "duck"),
    Case("near-high-screen-upright", "beam", 53, 0.65, "stand", "stand"),
    Case("near-high-screen-mid-jump", "beam", 53, 0.2, "jump", "stand"),
    Case("crossing-crate-mid-jump", "crate", 0, -0.1, "jump", "jump"),
)


async def evaluate_cases(repeats: int) -> list[dict[str, object]]:
    """Record real responses and prompt metadata without credentials or client headers."""
    settings = Settings()
    results: list[dict[str, object]] = []
    async with httpx.AsyncClient(
        timeout=30, headers={"Content-Type": "application/json"}
    ) as client:
        for case in CASES:
            world = case.world()
            request = make_request(settings, world.observation(world.current))
            for repeat in range(repeats):
                row: dict[str, object] = {
                    "case": case.name,
                    "repeat": repeat,
                    "expected": case.expected,
                    "request": request.model_dump(mode="json"),
                }
                try:
                    response, latency = await infer(client, settings, request)
                    choice = response.answers.action.choice
                    row.update(
                        response=response.model_dump(mode="json"),
                        correct=choice == case.expected,
                        latency_ms=latency,
                    )
                    print(f"{case.name}: {choice} (expected {case.expected})", flush=True)
                except JevError as exc:
                    row.update(error=exc.message, correct=False)
                    print(f"{case.name}: {exc.message}", flush=True)
                results.append(row)
    return results


def main() -> None:
    """Run a small paid live evaluation only when explicitly invoked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", default=2, type=int, choices=range(1, 6))
    args = parser.parse_args()
    results = asyncio.run(evaluate_cases(int(args.repeats)))
    correct = sum(row["correct"] is True for row in results)
    output = Path(str(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"correct": correct, "total": len(results), "results": results}, indent=2) + "\n"
    )
    print(f"{correct}/{len(results)} correct; saved {output}")


if __name__ == "__main__":
    main()

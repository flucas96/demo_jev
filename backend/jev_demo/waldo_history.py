"""Local, atomic persistence for paired comparisons and server-scored leaderboard runs."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from secrets import randbelow
from typing import Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field


class Comparison(BaseModel):
    """A server-owned schedule that fixes model, duration, order, and scoring references."""

    id: str
    model: str
    duration: int
    seed: int
    deck: str
    next_stage: Literal[1, 2, 3] = 1


class Run(BaseModel):
    """A scored run with explicit completeness and cost provenance."""

    id: str
    comparison_id: str | None
    stage: int
    created_at: str
    duration: int
    seed: int
    deck: str
    model: str
    resolved_model: str
    label: str
    human_score: int
    human_hits: int
    human_misses: int
    score: int
    hits: int
    misses: int
    calls: int
    completed: int
    failures: int
    cost_usd: float | None
    cost_partial: bool
    cost_basis: str
    average_ms: float | None
    status: Literal["completed", "stopped", "error", "disconnected"]


class ComparisonInput(BaseModel):
    """Only a known model and bounded duration are supplied by the browser."""

    model: str = Field(min_length=1, max_length=100)
    duration: int = Field(default=60, ge=15, le=180)


def timestamp() -> str:
    """Use UTC so stored history is independent of the server's local timezone."""
    return datetime.now(UTC).isoformat()


class History:
    """Open a short-lived connection per operation; SQLite commits each run and phase together."""

    def __init__(self, path: Path) -> None:
        """Defer filesystem work until the first history operation."""
        self.path = path

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        """Close connections reliably and serialize updates with SQLite transactions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                _ = connection.execute(
                    "CREATE TABLE IF NOT EXISTS comparisons "
                    "(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
                _ = connection.execute(
                    "CREATE TABLE IF NOT EXISTS runs "
                    "(id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL)"
                )
                yield connection
        finally:
            connection.close()

    def create(self, model: str, duration: int, deck: str) -> Comparison:
        """Generate the order once for both rounds; clients never supply scoring data."""
        comparison = Comparison(
            id=str(uuid4()), model=model, duration=duration, seed=randbelow(2**31), deck=deck
        )
        with self.connection() as connection:
            _ = connection.execute(
                "INSERT INTO comparisons VALUES (?, ?)",
                (comparison.id, comparison.model_dump_json()),
            )
        return comparison

    def get(self, comparison_id: str) -> Comparison | None:
        """Resolve only a stored comparison, never client-provided models or seed overrides."""
        with self.connection() as connection:
            row = cast(
                tuple[str] | None,
                connection.execute(
                    "SELECT payload FROM comparisons WHERE id = ?", (comparison_id,)
                ).fetchone(),
            )
        return Comparison.model_validate_json(row[0]) if row else None

    def save(self, run: Run) -> None:
        """Insert once and advance a completed comparison in the same transaction."""
        with self.connection() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                (run.id, run.created_at, run.model_dump_json()),
            ).rowcount
            if inserted and run.comparison_id and run.status == "completed":
                row = cast(
                    tuple[str] | None,
                    connection.execute(
                        "SELECT payload FROM comparisons WHERE id = ?", (run.comparison_id,)
                    ).fetchone(),
                )
                if row:
                    comparison = Comparison.model_validate_json(row[0])
                    if comparison.next_stage == run.stage:
                        comparison.next_stage = 2 if run.stage == 1 else 3
                        _ = connection.execute(
                            "UPDATE comparisons SET payload = ? WHERE id = ?",
                            (comparison.model_dump_json(), comparison.id),
                        )

    def runs(self) -> list[Run]:
        """Return the most recent 500 runs; scoring and ranking never trust browser submissions."""
        with self.connection() as connection:
            rows = cast(
                list[tuple[str]],
                connection.execute(
                    "SELECT payload FROM runs ORDER BY created DESC LIMIT 500"
                ).fetchall(),
            )
        return [Run.model_validate_json(row[0]) for row in rows]

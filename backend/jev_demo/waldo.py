"""Live image localization, independent box scoring, and a timed human–Jev race."""

import asyncio
import base64
import os
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from random import Random
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Literal, Self
from uuid import uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .models import Probability, Usage
from .pricing import estimate_cost_usd
from .service import JevError, Settings, post_evaluation
from .waldo_annotations import Annotation, Crop, denormalize, normalize

MODEL = "jev-1.14.0"
ASSETS = Path(__file__).parent / "assets" / "waldo"
HEAD_COVERAGE = 0.5
BOX_PRECISION = 0.55
BODY_PADDING = 0.2
ANSWER_PADDING = 0.30
FEEDBACK_SECONDS = 0.45
MAX_MISSES = 3
type Mode = Literal["sprint", "classic"]
type PlayerId = Literal["human", "jev"]


class Point(BaseModel):
    """A normalized human click within the displayed image."""

    model_config = ConfigDict(extra="forbid")
    x: Probability
    y: Probability


class Box(BaseModel):
    """Normalized image edges, independent of display scale and drag direction."""

    model_config = ConfigDict(extra="forbid")
    left: Probability
    right: Probability
    top: Probability
    bottom: Probability

    @model_validator(mode="after")
    def ordered_edges(self) -> Self:
        """Reject empty, reversed, or nonfinite rectangles before scoring."""
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("A box must have positive width and height.")
        return self

    @property
    def area(self) -> float:
        """Return the fraction of image area covered by this rectangle."""
        return (self.right - self.left) * (self.bottom - self.top)

    def padded(self, fraction: float) -> Box:
        """Expand each edge relative to the target size, clipped to the actual image."""
        dx = (self.right - self.left) * fraction
        dy = (self.bottom - self.top) * fraction
        return Box(
            left=max(0, self.left - dx),
            right=min(1, self.right + dx),
            top=max(0, self.top - dy),
            bottom=min(1, self.bottom + dy),
        )


def intersection(candidate: Box, reference: Box) -> float:
    """Return the shared normalized area of two rectangles."""
    return max(
        0.0, min(candidate.right, reference.right) - max(candidate.left, reference.left)
    ) * max(0.0, min(candidate.bottom, reference.bottom) - max(candidate.top, reference.top))


def overlap(candidate: Box, reference: Box) -> float:
    """Report body IoU for inspection; head-only hits do not need to match body proportions."""
    shared = intersection(candidate, reference)
    return shared / (candidate.area + reference.area - shared)


class Puzzle(BaseModel):
    """A reviewed local image and an annotation never transmitted to Jev."""

    id: str
    mode: Mode
    width: int
    height: int
    reference: Box
    head: Box
    source_id: int
    source_crop: Crop
    generated: bool = False
    title: str = ""

    def public(self) -> dict[str, object]:
        """Expose only display metadata, without the solution or source annotation."""
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "title": self.title or f"Bild {self.id.split('-')[1]}",
            "url": f"/api/waldo/images/{self.id}?v=2",
        }

    def accepts(self, candidate: Box) -> bool:
        """Accept a recognizable head or body with padding, rejecting broad or headless guesses."""
        return (
            intersection(candidate.padded(ANSWER_PADDING), self.head) / self.head.area
            >= HEAD_COVERAGE
            and intersection(candidate, self.reference.padded(BODY_PADDING)) / candidate.area
            >= BOX_PRECISION
        )

    def accepts_click(self, point: Point) -> bool:
        """Accept a click on the visible target with the displayed body tolerance."""
        area = self.reference.padded(BODY_PADDING)
        return area.left <= point.x <= area.right and area.top <= point.y <= area.bottom

    def review(self) -> dict[str, object]:
        """Expose exact scoring geometry only through the explicit reference-review view."""
        return {
            **self.public(),
            "reference": self.reference.model_dump(),
            "head": self.head.model_dump(),
            "tolerance": self.reference.padded(BODY_PADDING).model_dump(),
        }


ANNOTATIONS = ASSETS / "reviewed-annotations.json"


def apply_annotation(puzzle: Puzzle, annotation: Annotation) -> None:
    """Project the canonical source annotation onto either view of the same scene."""
    puzzle.reference = Box.model_validate(normalize(annotation.body, puzzle.source_crop))
    puzzle.head = Box.model_validate(normalize(annotation.head, puzzle.source_crop))


def load_puzzles() -> list[Puzzle]:
    """Restore saved user corrections as well as the initially reviewed references."""
    puzzles = TypeAdapter(list[Puzzle]).validate_json((ASSETS / "manifest.json").read_bytes())
    annotations = {
        item.source_id: item
        for item in TypeAdapter(list[Annotation]).validate_json(ANNOTATIONS.read_bytes())
    }
    for puzzle in puzzles:
        apply_annotation(puzzle, annotations[puzzle.source_id])
    return puzzles


class ReferenceCorrection(BaseModel):
    """A user-reviewed body and a head fully contained in that body."""

    model_config = ConfigDict(extra="forbid")
    reference: Box
    head: Box

    @model_validator(mode="after")
    def contained_head(self) -> Self:
        """Keep contradictory annotations from silently changing the scoring rule."""
        if intersection(self.head, self.reference) < self.head.area * (1 - 1e-8):
            raise ValueError("Die Kopfbox muss innerhalb der Körperbox liegen.")
        return self


def save_correction(puzzle: Puzzle, correction: ReferenceCorrection) -> None:
    """Atomically persist one source annotation and update both views without touching images."""

    def source(box: Box) -> tuple[float, float, float, float]:
        """Convert edited edges to the original source coordinate system."""
        return denormalize((box.left, box.top, box.right, box.bottom), puzzle.source_crop)

    updated = Annotation(
        source_id=puzzle.source_id, body=source(correction.reference), head=source(correction.head)
    )
    related = [item for item in PUZZLES if item.source_id == puzzle.source_id]
    for item in related:
        ReferenceCorrection(
            reference=Box.model_validate(normalize(updated.body, item.source_crop)),
            head=Box.model_validate(normalize(updated.head, item.source_crop)),
        )
    annotations = TypeAdapter(list[Annotation]).validate_json(ANNOTATIONS.read_bytes())
    annotations = [updated if item.source_id == puzzle.source_id else item for item in annotations]
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=ASSETS, prefix=".annotations-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(TypeAdapter(list[Annotation]).dump_json(annotations, indent=2) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ANNOTATIONS)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    for item in related:
        apply_annotation(item, updated)


PUZZLES = load_puzzles()
BY_ID = {puzzle.id: puzzle for puzzle in PUZZLES}


def playable_puzzles(mode: Mode) -> list[Puzzle]:
    """Use the generated mixture; legacy mode URLs cannot reintroduce archived originals."""
    return [puzzle for puzzle in PUZZLES if puzzle.generated]


@lru_cache(maxsize=48)
def image_bytes(puzzle_id: str) -> bytes:
    """Load only allowlisted assets, shared byte-for-byte by browser and model."""
    if puzzle_id not in BY_ID and puzzle_id != "target":
        raise ValueError("Unknown puzzle.")
    return (ASSETS / f"{puzzle_id}.jpg").read_bytes()


class BoxQuestion(BaseModel):
    """The new primitive has instructions and deliberately has no criteria."""

    type: Literal["box"] = "box"
    instructions: str = "Where is Waldo in `scene`?"


class ImageAsset(BaseModel):
    """An inline image using the documented TypeSafe asset contract."""

    type: Literal["image"] = "image"
    format: Literal["jpg"] = "jpg"
    data_base64: str


class BoxRequest(BaseModel):
    """An inspectable request containing only image evidence and the target description."""

    model: str = MODEL
    state: dict[str, str]
    assets: dict[str, ImageAsset]
    questions: dict[str, BoxQuestion]


class BoxAnswer(BaseModel):
    """The actual provider rectangle and its reported confidence."""

    type: Literal["box"]
    box: Box
    confidence: Probability


class BoxAnswers(BaseModel):
    """A stable key for the single localization question."""

    waldo: BoxAnswer


class BoxResponse(BaseModel):
    """Validate localization and usage before touching a score or cost counter."""

    model: str
    answers: BoxAnswers
    usage: Usage


def make_request(puzzle: Puzzle) -> BoxRequest:
    """Never pass the reference box, puzzle ID, filename, or past correctness to the model."""
    reference = str(uuid4())
    return BoxRequest(
        state={"scene": reference},
        assets={
            reference: ImageAsset(
                data_base64=base64.b64encode(image_bytes(puzzle.id)).decode("ascii")
            )
        },
        questions={"waldo": BoxQuestion()},
    )


async def infer(
    client: httpx.AsyncClient, settings: Settings, puzzle: Puzzle
) -> tuple[BoxResponse, float]:
    """Time one real image request with experimental images enabled and no hidden retry."""
    payload = make_request(puzzle)
    content, elapsed = await post_evaluation(
        client, settings, payload.model_dump_json(), image_input=True
    )
    try:
        return BoxResponse.model_validate_json(content), elapsed
    except ValueError as exc:
        raise JevError(502, "Jev hat keine gültige Box geliefert. Bitte erneut versuchen.") from exc


class Move(BaseModel):
    """Bind every drag to the displayed round so delayed events cannot score a new image."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["box", "click", "skip", "stop", "retry"]
    round: int = Field(default=0, ge=0)
    box: Box | None = None
    point: Point | None = None


@dataclass
class Player:
    """Keep each competitor's progress and feedback independent."""

    round: int = 0
    score: int = 0
    hits: int = 0
    misses: int = 0
    streak: int = 0
    ready_at: float = 0
    advance: bool = False
    feedback: dict[str, object] | None = None


@dataclass
class Match:
    """Own authoritative time, shuffled course, scoring, and reported model usage."""

    duration: int
    mode: Mode
    seed: int
    started: float
    players: dict[PlayerId, Player] = field(
        default_factory=lambda: {"human": Player(), "jev": Player()}
    )
    course: list[Puzzle] = field(init=False)
    calls: int = 0
    completed: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0
    unpriced: int = 0
    latencies: list[float] = field(default_factory=list)
    model: str = MODEL
    model_error: str | None = None
    ended: bool = False
    aborted: bool = False

    def __post_init__(self) -> None:
        """Give both players the same reproducibly shuffled course."""
        self.course = playable_puzzles(self.mode)
        Random(self.seed).shuffle(self.course)

    def puzzle(self, player: PlayerId) -> Puzzle:
        """Repeat the finite deck so a fast player never runs out before time expires."""
        return self.course[self.players[player].round % len(self.course)]

    def remaining(self, now: float) -> float:
        """Use server monotonic time, never a client-supplied timestamp."""
        return max(0, self.started + self.duration - now)

    def tick(self, now: float) -> None:
        """Release result animations and freeze the game at its deadline."""
        if self.remaining(now) == 0:
            self.ended = True
        for player in self.players.values():
            if not self.ended and player.feedback is not None and now >= player.ready_at:
                if player.advance:
                    player.round += 1
                    player.streak = 0
                player.feedback = None
                player.advance = False

    def submit(
        self,
        who: PlayerId,
        round_id: int,
        box: Box | None,
        now: float,
        confidence: float | None = None,
        elapsed_ms: float | None = None,
        *,
        point: Point | None = None,
    ) -> bool:
        """Score a human click or model box with shared cooldown and advancement rules."""
        player = self.players[who]
        if (
            self.ended
            or self.remaining(now) == 0
            or player.round != round_id
            or player.feedback is not None
            or (point is not None and who != "human")
        ):
            return False
        iou = overlap(box, self.puzzle(who).reference) if box is not None else 0
        correct = (
            self.puzzle(who).accepts_click(point)
            if point is not None
            else box is not None and self.puzzle(who).accepts(box)
        )
        skipped = box is None and point is None
        player.score += 1 if correct else -1
        player.hits += int(correct)
        player.misses += int(not correct)
        player.streak = 0 if correct else player.streak + 1
        player.advance = correct or skipped or player.streak >= MAX_MISSES
        player.ready_at = now + FEEDBACK_SECONDS
        player.feedback = {
            "correct": correct,
            "skipped": skipped,
            "point": point.model_dump() if point else None,
            "iou": round(iou, 4),
            "box": box.model_dump() if box else None,
            "scoring_box": box.padded(ANSWER_PADDING).model_dump() if box else None,
            "confidence": confidence,
            "elapsed_ms": elapsed_ms,
            "advance": player.advance,
        }
        return True

    def record_usage(self, response: BoxResponse, elapsed_ms: float) -> None:
        """Account for actual usage even when a response is too late to earn a point."""
        self.completed += 1
        self.model = response.model
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        estimate = estimate_cost_usd(response.model, response.usage.input_tokens)
        self.unpriced += int(estimate is None)
        self.cost += estimate or 0
        self.latencies.append(elapsed_ms)

    def snapshot(self, now: float) -> dict[str, object]:
        """Publish scores and genuine telemetry without exposing future solutions."""
        human, jev = self.players["human"], self.players["jev"]
        winner = (
            "draw" if human.score == jev.score else "human" if human.score > jev.score else "jev"
        )
        return {
            "type": "state",
            "remaining_ms": round(self.remaining(now) * 1000),
            "duration": self.duration,
            "ended": self.ended,
            "aborted": self.aborted,
            "winner": winner if self.ended else None,
            "model_error": self.model_error,
            "players": {
                who: {
                    "round": p.round,
                    "score": p.score,
                    "hits": p.hits,
                    "misses": p.misses,
                    "puzzle": self.puzzle(who).public(),
                    "feedback": p.feedback,
                }
                for who, p in self.players.items()
            },
            "metrics": {
                "calls": self.calls,
                "completed": self.completed,
                "failures": self.failures,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost,
                "cost_partial": self.calls > self.completed or self.unpriced > 0,
                "last_ms": self.latencies[-1] if self.latencies else None,
                "average_ms": sum(self.latencies) / len(self.latencies) if self.latencies else None,
                "latencies": self.latencies[-24:],
                "model": self.model,
            },
        }


async def play(
    socket: WebSocket,
    client: httpx.AsyncClient,
    settings: Settings,
    duration: int,
    mode: Mode,
    seed: int,
) -> None:
    """Run one fair clock with independent turns, disconnect cancellation, and bounded calls."""
    match = Match(duration, mode, seed, perf_counter())
    receiver: asyncio.Task[str] | None = None
    inference: asyncio.Task[tuple[BoxResponse, float]] | None = None
    inference_round = 0
    try:
        receiver = asyncio.create_task(socket.receive_text())
        while not match.ended:
            now = perf_counter()
            match.tick(now)
            if inference is not None and inference.done():
                try:
                    response, elapsed = inference.result()
                    match.record_usage(response, elapsed)
                    match.submit(
                        "jev",
                        inference_round,
                        response.answers.waldo.box,
                        now,
                        response.answers.waldo.confidence,
                        elapsed,
                    )
                except JevError as exc:
                    match.failures += 1
                    match.model_error = exc.message
                inference = None
            if receiver.done():
                raw = receiver.result()
                try:
                    move = Move.model_validate_json(raw)
                    if move.type == "stop":
                        match.ended = match.aborted = True
                    elif move.type == "retry":
                        match.model_error = None
                    elif move.type == "click" and move.point is not None:
                        match.submit("human", move.round, None, now, point=move.point)
                    elif move.type == "skip" or move.box is not None:
                        match.submit(
                            "human", move.round, move.box if move.type == "box" else None, now
                        )
                except ValueError:
                    pass
                receiver = asyncio.create_task(socket.receive_text())
            if (
                not match.ended
                and inference is None
                and match.model_error is None
                and match.players["jev"].feedback is None
            ):
                match.calls += 1
                inference_round = match.players["jev"].round
                inference = asyncio.create_task(infer(client, settings, match.puzzle("jev")))
            await socket.send_json(match.snapshot(now))
            if not match.ended:
                pending: set[asyncio.Task[object]] = {receiver}
                if inference is not None:
                    pending.add(inference)
                await asyncio.wait(pending, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        tasks = [task for task in (receiver, inference) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, WebSocketDisconnect, JevError):
                await task
        with suppress(RuntimeError, WebSocketDisconnect):
            await socket.close()

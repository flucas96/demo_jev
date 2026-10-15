"""Live image localization, independent box scoring, and a timed human–Jev race."""

import asyncio
import base64
import hashlib
import os
from collections import defaultdict
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

from . import waldo_gateway
from .models import Probability, Usage
from .pricing import estimate_cost_usd
from .service import JevError, Settings, post_evaluation
from .waldo_annotations import Annotation, Crop, denormalize, normalize
from .waldo_geometry import Box, Point, intersection, overlap
from .waldo_history import History, Run, timestamp

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

    @property
    def background(self) -> str:
        """Group original scenes and placed-target variants by their shared scenery."""
        return self.title.split(" · ", 1)[0] or self.id

    def public(self) -> dict[str, object]:
        """Expose only display metadata, without the solution or source annotation."""
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "title": english_title(self.title) if self.title else "Search scene",
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


def english_title(title: str) -> str:
    """Translate scene labels without changing stable asset IDs or annotations."""
    labels = {
        "Am Bahnhof": "Train station",
        "Auf dem Markt": "Market square",
        "Im Stadtpark": "City park",
        "Im Museum": "Museum",
        "Am Hafen": "Harbor",
        "Beim Straßenfest": "Street festival",
        "Am belebten Strand": "Busy beach",
        "Im botanischen Garten": "Botanical garden",
        "Am Flughafen": "Airport",
        "Auf dem Rathausplatz": "Town square",
        "Auf dem Jahrmarkt": "Funfair",
        "Auf der Buchmesse": "Book fair",
    }
    base, separator, variant = title.partition(" · ")
    return labels.get(base, base) + separator + variant


def shuffled_course(puzzles: list[Puzzle], seed: int) -> list[Puzzle]:
    """Shuffle deterministically while changing backgrounds on every turn, including wraparound."""
    random = Random(seed)
    groups: dict[str, list[Puzzle]] = defaultdict(list)
    for puzzle in puzzles:
        groups[puzzle.background].append(puzzle.model_copy(deep=True))
    for group in groups.values():
        random.shuffle(group)
    course: list[Puzzle] = []
    previous = ""
    while groups:
        eligible = [key for key in groups if key != previous]
        if not eligible:
            raise ValueError("The deck needs more distinct backgrounds to avoid repetition.")
        key = max(eligible, key=lambda key: (len(groups[key]), random.random()))
        course.append(groups[key].pop())
        previous = key
        if not groups[key]:
            del groups[key]
    if len(course) > 2 and course[-1].background == course[0].background:
        last = course[-1].background
        index = next(
            i
            for i in range(1, len(course) - 2)
            if last not in (course[i - 1].background, course[i + 1].background)
            and course[i].background not in (course[-2].background, course[0].background)
        )
        course[index], course[-1] = course[-1], course[index]
    return course


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
            raise ValueError("The head box must be inside the body box.")
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


def deck_fingerprint() -> str:
    """Identify the image identities and scoring references used by both comparison rounds."""
    data = TypeAdapter(list[Puzzle]).dump_json(playable_puzzles("sprint"))
    return hashlib.sha256(b"waldo-v3-background-rotation" + data).hexdigest()[:16]


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
        raise JevError(502, "Jev returned an invalid box. Please try again.") from exc


async def infer_model(
    client: httpx.AsyncClient, settings: Settings, puzzle: Puzzle, model: str
) -> waldo_gateway.Localization:
    """Normalize provider telemetry while keeping Jev's native confidence distinct."""
    if model != MODEL:
        return await waldo_gateway.infer(client, settings, model, image_bytes(puzzle.id))
    response, elapsed = await infer(client, settings, puzzle)
    return waldo_gateway.Localization(
        response.model,
        response.answers.waldo.box,
        response.answers.waldo.confidence,
        response.usage,
        elapsed,
        estimate_cost_usd(response.model, response.usage.input_tokens),
        "estimate",
    )


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
    run_id: str = field(default_factory=lambda: str(uuid4()))
    comparison_id: str | None = None
    stage: int = 1
    requested_model: str = MODEL
    label: str = "Jev"
    created_at: str = field(default_factory=timestamp)
    deck: str = field(default_factory=deck_fingerprint)
    cost_sources: set[str] = field(default_factory=set)
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
        self.course = shuffled_course(playable_puzzles(self.mode), self.seed)

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
        invalid_answer: bool = False,
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
        skipped = box is None and point is None and not invalid_answer
        player.score += 1 if correct else -1
        player.hits += int(correct)
        player.misses += int(not correct)
        player.streak = 0 if correct else player.streak + 1
        player.advance = who == "jev" or correct or skipped or player.streak >= MAX_MISSES
        player.ready_at = now if who == "jev" and not correct else now + FEEDBACK_SECONDS
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
        self.record_result(
            waldo_gateway.Localization(
                response.model,
                response.answers.waldo.box,
                response.answers.waldo.confidence,
                response.usage,
                elapsed_ms,
                estimate_cost_usd(response.model, response.usage.input_tokens),
                "estimate",
            )
        )

    def record_result(self, result: waldo_gateway.Localization) -> None:
        """Retain billed usage even for invalid boxes and answers arriving after the deadline."""
        self.completed += 1
        self.model = result.model
        if result.usage is not None:
            self.input_tokens += result.usage.input_tokens
            self.output_tokens += result.usage.output_tokens
        self.unpriced += int(result.cost_usd is None)
        self.cost += result.cost_usd or 0
        self.cost_sources.add(result.cost_basis)
        self.latencies.append(result.elapsed_ms)

    @property
    def cost_basis(self) -> str:
        """Explain when a total mixes gateway charges and local estimates."""
        return (
            next(iter(self.cost_sources))
            if len(self.cost_sources) == 1
            else ("mixed" if self.cost_sources else "unknown")
        )

    def result(self, disconnected: bool = False) -> Run:
        """Create a leaderboard record solely from authoritative server state."""
        human, ai = self.players["human"], self.players["jev"]
        status = (
            "disconnected"
            if disconnected
            else "stopped"
            if self.aborted
            else ("error" if self.model_error or self.completed == 0 else "completed")
        )
        return Run(
            id=self.run_id,
            comparison_id=self.comparison_id,
            stage=self.stage,
            created_at=self.created_at,
            duration=self.duration,
            seed=self.seed,
            deck=self.deck,
            model=self.requested_model,
            resolved_model=self.model,
            label=self.label,
            human_score=human.score,
            human_hits=human.hits,
            human_misses=human.misses,
            score=ai.score,
            hits=ai.hits,
            misses=ai.misses,
            calls=self.calls,
            completed=self.completed,
            failures=self.failures,
            cost_usd=None if self.unpriced and not self.cost else self.cost,
            cost_partial=self.calls > self.completed or self.unpriced > 0,
            cost_basis=self.cost_basis,
            average_ms=sum(self.latencies) / len(self.latencies) if self.latencies else None,
            status=status,
        )

    def snapshot(self, now: float) -> dict[str, object]:
        """Publish scores and genuine telemetry without exposing future solutions."""
        human, jev = self.players["human"], self.players["jev"]
        winner = (
            "draw" if human.score == jev.score else "human" if human.score > jev.score else "jev"
        )
        return {
            "type": "state",
            "run_id": self.run_id,
            "comparison_id": self.comparison_id,
            "stage": self.stage,
            "model_label": self.label,
            "status": self.result().status if self.ended else None,
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
                "cost_usd": None if self.unpriced and not self.cost else self.cost,
                "cost_basis": self.cost_basis,
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
    *,
    model: str = MODEL,
    history: History | None = None,
    comparison_id: str | None = None,
    stage: int = 1,
) -> None:
    """Run one fair clock with independent turns, disconnect cancellation, and bounded calls."""
    label = "Jev" if model == MODEL else waldo_gateway.BY_MODEL[model].label
    match = Match(
        duration,
        mode,
        seed,
        perf_counter(),
        requested_model=model,
        model=model,
        label=label,
        comparison_id=comparison_id,
        stage=stage,
    )
    disconnected = False
    saved = False
    receiver: asyncio.Task[str] | None = None
    inference: asyncio.Task[waldo_gateway.Localization] | None = None
    inference_round = 0
    try:
        receiver = asyncio.create_task(socket.receive_text())
        while not match.ended:
            now = perf_counter()
            match.tick(now)
            if inference is not None and inference.done():
                try:
                    result = inference.result()
                    match.record_result(result)
                    match.submit(
                        "jev",
                        inference_round,
                        result.box,
                        now,
                        result.confidence,
                        result.elapsed_ms,
                        invalid_answer=result.box is None,
                    )
                except JevError as exc:
                    match.failures += 1
                    match.model_error = exc.message
                inference = None
                match.tick(now)
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
                inference = asyncio.create_task(
                    infer_model(client, settings, match.puzzle("jev"), model)
                )
            if match.ended and history is not None:
                await asyncio.to_thread(history.save, match.result())
                saved = True
            await socket.send_json(match.snapshot(now))
            if not match.ended:
                pending: set[asyncio.Task[object]] = {receiver}
                if inference is not None:
                    pending.add(inference)
                await asyncio.wait(pending, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        disconnected = True
    finally:
        tasks = [task for task in (receiver, inference) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, WebSocketDisconnect, JevError):
                await task
        if history is not None and not saved:
            await asyncio.to_thread(
                history.save, match.result(disconnected=disconnected or not match.ended)
            )
        with suppress(RuntimeError, WebSocketDisconnect):
            await socket.close()

"""Answer-driven Snake with a character-only board and unmodified Jev decisions."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from random import Random
from typing import Literal, Self

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, model_validator

from .models import ChoiceQuestion, Probability, Usage
from .pricing import estimate_cost_usd
from .service import JevError, Settings, post_evaluation

type Direction = Literal["up", "right", "down", "left"]
type Cell = tuple[int, int]
type Phase = Literal["running", "lost", "won", "stopped"]
SIZE = 10
VECTORS: dict[Direction, Cell] = {"up": (0, -1), "right": (1, 0), "down": (0, 1), "left": (-1, 0)}
HEADS: dict[Direction, str] = {"up": "^", "right": ">", "down": "v", "left": "<"}


class SnakeChoice(BaseModel):
    """Require a complete, internally consistent distribution over absolute directions."""

    choice: Direction
    confidence: Probability
    probabilities: dict[Direction, Probability]

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        """Reject malformed decisions instead of silently substituting a safe move."""
        if set(self.probabilities) != set(VECTORS):
            raise ValueError("Expected four directions.")
        if abs(sum(self.probabilities.values()) - 1) > 0.015:
            raise ValueError("Probabilities must sum to one.")
        if self.probabilities[self.choice] < max(self.probabilities.values()) - 0.001:
            raise ValueError("Choice must have maximal probability.")
        return self


class SnakeAnswers(BaseModel):
    """Name the model's movement decision."""

    direction: SnakeChoice


class SnakeResponse(BaseModel):
    """Validate the model response and retain its reported usage."""

    model: str
    answers: SnakeAnswers
    usage: Usage


class SnakeRequest(BaseModel):
    """Keep the exact board and fixed rules inspectable without credentials."""

    model: str
    state: str
    questions: dict[str, ChoiceQuestion]


def make_request(settings: Settings, board: str) -> SnakeRequest:
    """Send only the character grid as state, without computed routes or safe-move hints."""
    return SnakeRequest(
        model=settings.typesafe_model,
        state=board,
        questions={
            "direction": ChoiceQuestion(
                instructions=(
                    "Play Snake. Choose the absolute direction for the next move. "
                    "The state is the whole board viewed from above: # wall, . empty, "
                    "* food, o body, T tail. The head is ^ > v <, pointing in its current "
                    "direction. Up is the previous row; right is the next column. "
                    "Collect food to grow. Hitting a wall or body ends the game; no wrapping. "
                    "Do not reverse into your neck. The tail vacates its cell on a non-eating "
                    "move, so entering that cell is legal. Prefer survival, then food. "
                    "The board stays still while you think. Your answer moves the snake "
                    "exactly one cell, then you receive the updated board."
                ),
                criteria={
                    "up": "Move one cell up: previous row, same column.",
                    "right": "Move one cell right: same row, next column.",
                    "down": "Move one cell down: next row, same column.",
                    "left": "Move one cell left: same row, previous column.",
                },
            )
        },
    )


async def infer(
    client: httpx.AsyncClient, settings: Settings, request: SnakeRequest
) -> tuple[SnakeResponse, float]:
    """Use the shared live transport and never invent a fallback response."""
    content, elapsed = await post_evaluation(client, settings, request.model_dump_json())
    try:
        return SnakeResponse.model_validate_json(content), elapsed
    except ValueError as exc:
        raise JevError(502, "Jev returned an invalid Snake direction.") from exc


@dataclass
class World:
    """Own movement and seeded food placement independently of model inference."""

    seed: int
    snake: list[Cell] = field(default_factory=lambda: [(4, 5), (3, 5), (2, 5)])
    direction: Direction = "right"
    food: Cell | None = None
    steps: int = 0
    score: int = 0
    phase: Phase = "running"
    reason: str | None = None
    rng: Random = field(init=False)

    def __post_init__(self) -> None:
        """Create a reproducible course with food only in unoccupied cells."""
        self.rng = Random(self.seed)
        self.place_food()

    def place_food(self) -> None:
        """Choose uniformly from free cells, or finish a completely filled board."""
        occupied = set(self.snake)
        free = [(x, y) for y in range(SIZE) for x in range(SIZE) if (x, y) not in occupied]
        self.food = self.rng.choice(free) if free else None
        if not free:
            self.phase, self.reason = "won", "Every cell filled."

    def board(self) -> str:
        """Render the complete observation, including boundaries and heading, as ASCII."""
        grid = [["."] * SIZE for _ in range(SIZE)]
        if self.food is not None:
            grid[self.food[1]][self.food[0]] = "*"
        for x, y in self.snake:
            grid[y][x] = "o"
        tail_x, tail_y = self.snake[-1]
        grid[tail_y][tail_x] = "T"
        head_x, head_y = self.snake[0]
        grid[head_y][head_x] = HEADS[self.direction]
        border = "#" * (SIZE + 2)
        return "\n".join([border, *("#" + "".join(row) + "#" for row in grid), border])

    def step(self, direction: Direction) -> None:
        """Apply the chosen direction exactly, allowing the tail to vacate before collision."""
        if self.phase != "running":
            return
        x, y = self.snake[0]
        dx, dy = VECTORS[direction]
        head = (x + dx, y + dy)
        self.direction = direction
        self.steps += 1
        eating = head == self.food
        body = self.snake if eating else self.snake[:-1]
        if not (0 <= head[0] < SIZE and 0 <= head[1] < SIZE):
            self.phase, self.reason = "lost", "Wall collision."
        elif head in body:
            self.phase, self.reason = "lost", "Body collision."
        else:
            self.snake.insert(0, head)
            if eating:
                self.score += 1
                self.place_food()
            else:
                self.snake.pop()


@dataclass(frozen=True)
class ObservationFormat:
    """Describe representation changes without evaluating candidate moves."""

    name: str
    spacing: bool = False
    named_head: bool = False
    coordinates: bool = False
    explicit_rules: bool = False
    neighbors: bool = False


STRUCTURED_OBSERVATION = ObservationFormat("combined_with_neighbors", True, True, True, True, True)


def format_request(settings: Settings, world: World, variant: ObservationFormat) -> SnakeRequest:
    """Change only notation and fixed rules; never send legal-move or progress scores."""
    request = make_request(settings, world.board())
    question = request.questions["direction"]
    board = world.board()
    metadata: list[str] = []
    if variant.named_head:
        board = board.replace(HEADS[world.direction], "H")
        question.instructions = question.instructions.replace(
            "The head is ^ > v <, pointing in its current direction.",
            "H marks the head; Current direction states its heading.",
        )
        metadata.append(f"Current direction: {world.direction.upper()}")
    if variant.coordinates:
        lines = board.splitlines()
        board = (
            "    "
            + " ".join(f"{i:2}" for i in range(len(lines[0])))
            + "\n"
            + "\n".join(
                f"{row:2}  " + " ".join(f"{char:>2}" for char in line)
                for row, line in enumerate(lines)
            )
        )
        metadata.append("Rows are labeled on the left; columns above. Labels include the walls.")
    elif variant.spacing:
        board = "\n".join(" ".join(line) for line in board.splitlines())
    if variant.explicit_rules:
        question.criteria = {
            direction: description + " Choose this direction only if its destination is empty, "
            "food, or the tail cell that vacates on this move. Do not enter a wall or body. "
            "Prefer survival, then food."
            for direction, description in question.criteria.items()
        }
    if variant.neighbors:
        head_x, head_y = world.snake[0]
        labels: list[str] = []
        cells = world.board().splitlines()
        names = {"#": "wall", ".": "empty", "o": "body", "T": "tail", "*": "food"}
        for direction, (dx, dy) in VECTORS.items():
            labels.append(
                f"{direction.upper()} of head: {names[cells[head_y + dy + 1][head_x + dx + 1]]}"
            )
        metadata.append("Adjacent cell contents (one cell from head):\n" + "\n".join(labels))
    request.state = "\n\n".join([*metadata, board])
    return request


class SnakeFrame(BaseModel):
    """Expose current physics separately from the exact board most recently sent to Jev."""

    type: Literal["frame"] = "frame"
    phase: Phase
    reason: str | None
    seed: int
    size: int = SIZE
    snake: list[Cell]
    food: Cell | None
    direction: Direction
    score: int
    steps: int
    board: str
    sent_board: str | None = None
    sent_step: int | None = None
    decision_step: int | None = None
    requests: int = 0
    responses: int = 0
    thinking: bool = False
    decision: SnakeChoice | None = None
    latency_ms: float | None = None
    input_tokens: int = 0
    estimated_cost_usd: float | None = 0
    request: SnakeRequest | None = None
    response_request: SnakeRequest | None = None
    response: SnakeResponse | None = None


class Command(BaseModel):
    """Accept a stop command while a decision is pending."""

    type: Literal["stop"]


async def play(socket: WebSocket, client: httpx.AsyncClient, settings: Settings, seed: int) -> None:
    """Move exactly once per validated answer, with no movement clock or stale board."""
    world = World(seed)
    frame = SnakeFrame(
        phase=world.phase,
        reason=None,
        seed=seed,
        snake=world.snake,
        food=world.food,
        direction=world.direction,
        score=0,
        steps=0,
        board=world.board(),
    )
    control = asyncio.create_task(socket.receive_text())
    pending: asyncio.Task[tuple[SnakeResponse, float]] | None = None
    try:
        while world.phase == "running":
            frame.request = format_request(settings, world, STRUCTURED_OBSERVATION)
            frame.sent_board = frame.request.state
            frame.sent_step = world.steps
            frame.requests += 1
            frame.thinking = True
            pending = asyncio.create_task(infer(client, settings, frame.request))
            async with asyncio.timeout(1):
                await socket.send_text(frame.model_dump_json())
            await asyncio.wait({control, pending}, return_when=asyncio.FIRST_COMPLETED)
            if control.done():
                raw = control.result()
                if len(raw) > 1024:
                    raise ValueError("Control too large.")
                Command.model_validate_json(raw)
                world.phase, world.reason = "stopped", "Run stopped."
            else:
                try:
                    response, elapsed = pending.result()
                    frame.response = response
                    frame.response_request = frame.request
                    frame.decision = response.answers.direction
                    frame.decision_step = world.steps
                    frame.latency_ms = elapsed
                    frame.responses += 1
                    frame.input_tokens += response.usage.input_tokens
                    cost = estimate_cost_usd(response.model, response.usage.input_tokens)
                    frame.estimated_cost_usd = (
                        frame.estimated_cost_usd + cost
                        if frame.estimated_cost_usd is not None and cost is not None
                        else None
                    )
                    world.step(response.answers.direction.choice)
                except JevError as exc:
                    world.phase, world.reason = "stopped", exc.message
                pending = None
            frame.thinking = False
            frame.phase, frame.reason = world.phase, world.reason
            frame.snake, frame.food = list(world.snake), world.food
            frame.direction, frame.steps, frame.score = world.direction, world.steps, world.score
            frame.board = world.board()
        async with asyncio.timeout(1):
            await socket.send_text(frame.model_dump_json())
    except WebSocketDisconnect, OSError, TimeoutError:
        pass
    except ValueError:
        with suppress(WebSocketDisconnect, OSError, RuntimeError):
            await socket.send_json({"type": "error", "message": "Invalid Snake control."})
    finally:
        control.cancel()
        if pending is not None:
            pending.cancel()
        await asyncio.gather(
            control, *([pending] if pending is not None else []), return_exceptions=True
        )

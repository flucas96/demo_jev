"""Real-time WebSocket sessions with immediate actions and a continuously adjustable clock."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from ..pricing import estimate_cost_usd
from ..service import JevError, Settings
from .inference import infer, make_request
from .world import LOOKAHEAD, Action, Challenge, DecisionView, Encounter, Mode, World

ENDLESS_ACCELERATION = 0.01


@dataclass
class GameClock:
    """Integrate game time without changing measured real-world inference latency."""

    pace: float = 1.0
    game_time: float = 0.0
    acceleration: float = 0.0
    sampled_at: float = field(default_factory=perf_counter)

    def sample(self, now: float | None = None) -> float:
        """Accumulate elapsed time at the previous speed before any speed change."""
        current = perf_counter() if now is None else now
        elapsed = max(0, current - self.sampled_at)
        self.game_time += elapsed * self.pace + 0.5 * self.acceleration * elapsed**2
        self.pace += self.acceleration * elapsed
        self.sampled_at = current
        return self.game_time

    def set_pace(self, pace: float, now: float | None = None) -> None:
        """Change speed continuously without teleporting obstacles or altering distance."""
        self.sample(now)
        self.pace = pace


class Command(BaseModel):
    """Bound the small set of browser controls accepted during a round."""

    type: Literal["action", "speed", "stop", "interrupt"]
    action: Action | None = None
    encounter_id: int | None = Field(default=None, ge=1)
    pace: float | None = Field(default=None, ge=0.5, le=2, allow_inf_nan=False)


async def decide_encounter(
    world: World,
    encounter: Encounter,
    clock: GameClock,
    client: httpx.AsyncClient,
    settings: Settings,
    changed: asyncio.Event | None = None,
    *,
    continuous: bool = False,
) -> None:
    """Apply a fresh response immediately and retain a matched request/response for inspection."""
    payload = make_request(settings, world.observation(encounter))
    request_json = payload.model_dump_json(indent=2)
    jumping_at_request = world.action_started if world.action == "jump" else None
    next_crate_jump = (
        encounter.kind == "crate"
        and world.jump_encounter_id is not None
        and encounter.id != world.jump_encounter_id
        and encounter.contact_start - world.time <= LOOKAHEAD + world.response_seconds * world.pace
    )
    world.requests += 1
    world.thinking = True
    if changed is not None:
        changed.set()
    try:
        response, elapsed = await infer(client, settings, payload)
        world.response_seconds = 0.7 * world.response_seconds + 0.3 * elapsed / 1000
        world.responses += 1
        world.input_tokens += response.usage.input_tokens
        world.output_tokens += response.usage.output_tokens
        cost = estimate_cost_usd(response.model, response.usage.input_tokens)
        world.cost = world.cost + cost if world.cost is not None and cost is not None else None
        world.model = response.model
        observed_at = clock.sample()
        world.pace = clock.pace
        world.advance(observed_at)
        choice = response.answers.action.choice
        expired_jump = (
            continuous
            and choice == "jump"
            and jumping_at_request is not None
            and (world.action != "jump" or world.action_started != jumping_at_request)
            and not next_crate_jump
        )
        accepted = not expired_jump and world.choose(
            encounter.id, choice, observed_at, continuous=continuous
        )
        probabilities = {
            str(key): value for key, value in response.answers.action.probabilities.items()
        }
        response_json = response.model_dump_json(indent=2)
        world.last_decision = DecisionView(
            id=encounter.id,
            status="ready" if accepted else "missed",
            action=choice,
            seconds_left=max(0, encounter.deadline - world.time) / world.pace,
            probabilities=probabilities,
            confidence=response.answers.action.confidence,
            latency_ms=elapsed,
            request=request_json,
            response=response_json,
            error=None if accepted else "The observed obstacle or jump has already passed.",
        )
        if accepted:
            encounter.request = request_json
            encounter.response = response_json
            encounter.latency_ms = elapsed
            encounter.probabilities = probabilities
            encounter.confidence = response.answers.action.confidence
    except JevError as exc:
        world.advance(clock.sample())
        if continuous:
            world.errors += 1
        else:
            world.fail(encounter.id, exc.message)
        world.last_decision = DecisionView(
            id=encounter.id,
            status="error",
            action=None,
            seconds_left=0,
            probabilities={},
            confidence=None,
            latency_ms=None,
            request=request_json,
            response=None,
            error=exc.message,
        )
    finally:
        world.thinking = False
        if changed is not None:
            changed.set()


async def control_continuously(
    world: World,
    clock: GameClock,
    client: httpx.AsyncClient,
    settings: Settings,
    changed: asyncio.Event,
) -> None:
    """Start the next request on each answer, with exactly one upstream call in flight."""
    while world.phase == "running":
        world.advance(clock.sample())
        world.pace = clock.pace
        if world.phase != "running":
            break
        await decide_encounter(
            world, world.current, clock, client, settings, changed, continuous=True
        )
        if world.last_decision is not None and world.last_decision.status == "error":
            await asyncio.sleep(0.5)
        else:
            # Yield execution without adding a delay between successful requests.
            await asyncio.sleep(0)


async def receive_controls(
    socket: WebSocket, world: World, clock: GameClock, changed: asyncio.Event
) -> None:
    """Apply manual moves and speed changes immediately, including while Jev is thinking."""
    try:
        while world.phase == "running":
            raw = await socket.receive_text()
            if len(raw) > 1024:
                world.interrupt("Invalid control message.")
                return
            try:
                command = Command.model_validate_json(raw)
            except ValidationError:
                world.interrupt("Invalid control message.")
                return
            world.advance(clock.sample())
            world.pace = clock.pace
            if command.type == "speed" and command.pace is not None and world.challenge == "timed":
                clock.set_pace(command.pace)
                world.pace = command.pace
            elif command.type in ("stop", "interrupt"):
                world.interrupt("Stopped." if command.type == "stop" else "Tab hidden. Run ended.")
            elif (
                command.type == "action"
                and world.mode == "manual"
                and command.action is not None
                and command.encounter_id is not None
            ):
                world.choose(command.encounter_id, command.action, clock.game_time)
            changed.set()
    except WebSocketDisconnect:
        world.interrupt("Connection closed.")
    finally:
        changed.set()


async def play(
    socket: WebSocket,
    client: httpx.AsyncClient,
    settings: Settings,
    seed: int,
    mode: Mode,
    pace: float = 1.0,
    challenge: Challenge = "timed",
) -> None:
    """Push immediate decision frames in addition to regular 20 Hz physics snapshots."""
    world = World(seed, mode, uuid4().hex, challenge)
    world.pace = pace
    clock = GameClock(pace=pace, acceleration=ENDLESS_ACCELERATION if challenge == "endless" else 0)
    changed = asyncio.Event()
    controls = asyncio.create_task(receive_controls(socket, world, clock, changed))
    inference = (
        asyncio.create_task(control_continuously(world, clock, client, settings, changed))
        if mode == "jev"
        else None
    )
    previous = perf_counter()
    try:
        while True:
            changed.clear()
            now = perf_counter()
            if now - previous > 0.75:
                world.interrupt("Server stalled. Replay to start a fair run.")
            previous = now
            world.advance(clock.sample(now))
            world.pace = clock.pace
            world.begin_observation()
            async with asyncio.timeout(1):
                await socket.send_text(world.frame().model_dump_json())
            if world.phase != "running":
                break
            with suppress(TimeoutError):
                await asyncio.wait_for(changed.wait(), timeout=0.05)
    except WebSocketDisconnect, TimeoutError, OSError:
        world.interrupt("Connection lost.")
    finally:
        pending = [controls] + ([inference] if inference is not None else [])
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

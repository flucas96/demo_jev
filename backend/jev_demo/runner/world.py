"""Seeded runner physics, procedural encounters, and one-shot scoring in Python."""

import json
import random
from dataclasses import dataclass, field
from math import floor
from typing import Literal

from pydantic import BaseModel

type Action = Literal["stand", "jump", "duck"]
type Mode = Literal["jev", "manual"]
type Challenge = Literal["timed", "endless"]
type Status = Literal["upcoming", "pending", "ready", "missed", "error"]
ACTIONS: tuple[Action, ...] = ("stand", "jump", "duck")
SPEED = 120.0
SCENE_WIDTH = 640.0
SPAWN_MARGIN = 32.0
PLAYER_X = 132.0
PLAYER_WIDTH = 20.0
HEIGHT = 40.0
DUCK_HEIGHT = 19.0
JUMP_HEIGHT = 66.0
ACTION_SECONDS = 1.8
LOOKAHEAD = 0.9
POINTS_PER_PIXEL: dict[Action, float] = {"stand": 0.1, "duck": 0.02, "jump": 0.0}
STEP = 1 / 60
ROUND_SECONDS = 60.0
HISTORY_LIMIT = 50


def body(action: Action, age: float) -> tuple[float, float]:
    """Return the bottom and height in pixels, with positive vertical coordinates upward."""
    if action == "jump" and 0 <= age < ACTION_SECONDS:
        progress = age / ACTION_SECONDS
        return 4 * JUMP_HEIGHT * progress * (1 - progress), HEIGHT
    return (0.0, DUCK_HEIGHT) if action == "duck" else (0.0, HEIGHT)


@dataclass
class Encounter:
    """A generated geometry with one observation window and collision outcome."""

    id: int
    trigger: float
    kind: Literal["clear", "crate", "beam"]
    width: float
    bottom: float
    top: float
    status: Status = "upcoming"
    selected: Action | None = None
    observed: bool = False
    resolved: bool = False
    request: str | None = None
    error: str | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    latency_ms: float | None = None
    response: str | None = None

    @property
    def deadline(self) -> float:
        """Reject decisions arriving after physical contact starts."""
        return self.contact_start

    @property
    def contact_start(self) -> float:
        """Start horizontal overlap after the selected animation has begun."""
        return self.trigger + 0.32

    @property
    def contact_end(self) -> float:
        """Include both body width and obstacle width in the crossing interval."""
        return self.contact_start + (self.width + PLAYER_WIDTH) / SPEED

    def x(self, time: float) -> float:
        """Place the obstacle's left edge in the fixed camera's coordinate system."""
        return PLAYER_X + PLAYER_WIDTH / 2 + (self.contact_start - time) * SPEED

    def collision(self, action: Action, time: float, action_started: float | None = None) -> bool:
        """Test physical overlap using the same body envelope as the visible runner."""
        if self.kind == "clear" or not self.contact_start <= time <= self.contact_end:
            return False
        bottom, height = body(
            action, time - (self.trigger if action_started is None else action_started)
        )
        return bottom < self.top and bottom + height > self.bottom

    def safe(self, action: Action) -> bool:
        """Evaluate an action privately over the full overlap interval, including endpoints."""
        samples = int((self.contact_end - self.contact_start) / STEP) + 2
        return not any(
            self.collision(
                action,
                min(self.contact_end, self.contact_start + sample * STEP),
            )
            for sample in range(samples + 1)
        )

    def optimal(self) -> Action:
        """Prefer upright when safe, otherwise select a surviving maneuver for evaluation."""
        return next(action for action in ACTIONS if self.safe(action))


class ObstacleView(BaseModel):
    """Public drawing geometry; no oracle action is exposed before resolution."""

    id: int
    kind: str
    x: float
    width: float
    bottom: float
    top: float
    trigger_in: float
    resolved: bool


class Trace(BaseModel):
    """An encounter's outcome, distinguished from inference transport failure."""

    id: int
    kind: str
    action: Action | None
    expected: Action
    status: Status
    collision: bool
    optimal: bool
    reward: int
    latency_ms: float | None
    request: str | None
    response: str | None
    error: str | None
    collision_reason: str | None = None


class DecisionView(BaseModel):
    """Current choice and its remaining deadline for the player-facing overlay."""

    id: int
    status: Status
    action: Action | None
    seconds_left: float
    probabilities: dict[str, float]
    confidence: float | None
    latency_ms: float | None
    request: str | None
    response: str | None
    error: str | None


class Frame(BaseModel):
    """An authoritative world snapshot, interpolated only for rendering in the browser."""

    type: Literal["frame"] = "frame"
    run_id: str
    seed: int
    mode: Mode
    time: float
    duration: float | None = ROUND_SECONDS
    challenge: Challenge = "timed"
    collisions: int = 0
    phase: Literal["running", "finished", "interrupted"]
    reason: str | None
    score: int
    lives: int
    action: Action
    action_age: float
    player_y: float
    player_height: float
    speed: float = SPEED
    pace: float = 1.0
    distance_m: float = 0.0
    jump_duration: float = ACTION_SECONDS
    hit: bool
    obstacles: list[ObstacleView]
    decision: DecisionView | None
    history: list[Trace]
    presented: int
    timely: int
    correct: int
    misses: int
    errors: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    model: str | None
    thinking: bool = False
    requests: int = 0
    responses: int = 0


class World:
    """Own a real-time run without allowing model work to advance or pause it."""

    def __init__(self, seed: int, mode: Mode, run_id: str, challenge: Challenge = "timed") -> None:
        """Initialize independent seeded geometry and a recovered upright runner."""
        self.seed = seed
        self.mode: Mode = mode
        self.challenge: Challenge = challenge
        self.duration = ROUND_SECONDS if challenge == "timed" else None
        self.run_id = run_id
        self.rng = random.Random(seed)
        self.time = 0.0
        self.phase: Literal["running", "finished", "interrupted"] = "running"
        self.reason: str | None = None
        self.score = 0.0
        self.pace = 1.0
        self.lives = 3
        self.action: Action = "stand"
        self.action_started = -2.0
        self.jump_encounter_id: int | None = None
        self.hit_until = -1.0
        self.history: list[Trace] = []
        self.past: list[Encounter] = []
        first_trigger = (SCENE_WIDTH + SPAWN_MARGIN - PLAYER_X - PLAYER_WIDTH / 2) / SPEED - 0.32
        self.current = self.generate(1, first_trigger)
        self.following = self.generate_following(self.current)
        self.presented = 0
        self.timely = 0
        self.correct = 0
        self.misses = 0
        self.errors = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost: float | None = 0.0
        self.model: str | None = None
        self.thinking = False
        self.requests = 0
        self.responses = 0
        self.last_decision: DecisionView | None = None
        self.response_seconds = 0.3

    def generate(self, encounter_id: int, trigger: float) -> Encounter:
        """Sample fair random geometry without programming a sequence of correct actions."""
        roll = self.rng.random()
        if roll < 0.1:
            return Encounter(encounter_id, trigger, "clear", 30, 0, 0)
        width = self.rng.uniform(22, 38)
        if roll < 0.55:
            result = Encounter(encounter_id, trigger, "crate", width, 0, self.rng.uniform(18, 28))
        else:
            clearance = self.rng.uniform(25, 33) if self.rng.random() < 0.85 else 53.0
            result = Encounter(encounter_id, trigger, "beam", width, clearance, 104)
        if not any(result.safe(action) for action in ACTIONS):
            raise ValueError("Generated an encounter without a safe move.")
        return result

    def generate_following(self, encounter: Encounter) -> Encounter:
        """Prepare one encounter ahead while it is still beyond the right edge."""
        return self.generate(encounter.id + 1, encounter.trigger + self.rng.uniform(2.5, 2.8))

    def observation(self, encounter: Encounter) -> str:
        """Describe geometry and body envelopes, never the evaluator's preferred action."""
        until_contact = encounter.contact_start - self.time
        response_delay = self.response_seconds * self.pace if self.mode == "jev" else 0.0
        obstacle = (
            None
            if encounter.kind == "clear"
            else {
                "kind": "ground_crate" if encounter.kind == "crate" else "overhead_screen",
                "structure": "solid crate resting on the road"
                if encounter.kind == "crate"
                else "hanging overhead screen with open passage underneath",
                "width_px": round(encounter.width, 2),
                "bottom_above_ground_px": round(encounter.bottom, 2),
                "top_above_ground_px": round(encounter.top, 2),
                "passage_underneath_px": round(encounter.bottom, 2),
                "phase": "crossing"
                if until_contact <= 0
                else "approaching"
                if until_contact - response_delay <= LOOKAHEAD
                else "distant",
                "game_seconds_until_contact": round(max(0, until_contact), 3),
                "estimated_game_seconds_until_contact_on_response": round(
                    max(0, until_contact - response_delay), 3
                ),
                "game_seconds_until_fully_passed": round(
                    max(0, encounter.contact_end - self.time), 3
                ),
            }
        )
        return json.dumps(
            {
                "units": "pixels above the road; all durations are game seconds",
                "next_obstacle": obstacle,
                "runner": {
                    "current_posture": self.action,
                    "estimated_response_delay_game_seconds": round(response_delay, 3),
                    "jump_seconds_remaining": round(
                        max(0, ACTION_SECONDS - (self.time - self.action_started)), 3
                    )
                    if self.action == "jump"
                    else 0,
                },
                "body_dimensions": {
                    "stand": {"feet_height": 0, "head_height": HEIGHT},
                    "duck": {"feet_height": 0, "head_height": DUCK_HEIGHT},
                    "jump": {
                        "peak_feet_height": JUMP_HEIGHT,
                        "body_height": HEIGHT,
                        "duration_game_seconds": ACTION_SECONDS,
                    },
                },
                "motion_rules": "Stand and duck immediately put the feet on the road, even "
                "during a jump. Jump while airborne continues the existing arc without "
                "restarting it. An overhead screen blocks the space ABOVE its passage; "
                "its top height is NOT the clearance. Keep the body below the passage "
                "throughout crossing. A ground crate blocks the road; clear its top.",
                "points_per_meter_travelled": {"stand": 1, "duck": 0.2, "jump": 0},
                "collision_penalty": -25,
                "objective": "Avoid collisions and maximize distance points. Your action begins "
                "immediately when your response arrives. There is no reward for choosing a move.",
            },
            separators=(",", ":"),
        )

    def begin_observation(self) -> Encounter | None:
        """Open exactly one request window for the active encounter when it reaches lookahead."""
        encounter = self.current
        if self.phase != "running" or encounter.observed:
            return None
        if self.time < encounter.contact_start - LOOKAHEAD or (
            self.duration is not None and encounter.contact_end > self.duration
        ):
            return None
        self.presented += 1
        encounter.observed = True
        if encounter.request is None:
            encounter.request = self.observation(encounter)
        encounter.status = "ready" if self.mode == "manual" or encounter.selected else "pending"
        if self.mode == "manual":
            encounter.selected = self.action
        return encounter

    def choose(
        self, encounter_id: int, action: Action, observed_at: float, *, continuous: bool = False
    ) -> bool:
        """Accept only a current, on-time action; never retroactively repair a collision."""
        self.advance(observed_at)
        encounter = self.current
        if (
            self.phase != "running"
            or encounter.id != encounter_id
            or (
                not continuous
                and (
                    encounter.status not in ("pending", "ready")
                    or observed_at >= encounter.deadline
                )
            )
        ):
            return False
        encounter.selected = action
        encounter.status = "ready"
        if action != self.action:
            self.action_started = self.time
            if action == "jump":
                self.jump_encounter_id = encounter.id
        self.action = action
        return True

    def fail(self, encounter_id: int, message: str) -> None:
        """Record a provider failure without selecting a hidden substitute action."""
        if self.current.id == encounter_id and self.current.status == "pending":
            self.current.status = "error"
            self.current.error = message
            self.errors += 1

    def interrupt(self, reason: str) -> None:
        """End a run whose connection or presentation can no longer support fair execution."""
        if self.phase == "running":
            self.phase = "interrupted"
            self.reason = reason

    def resolve(self, encounter: Encounter, collision: bool) -> None:
        """Award one outcome and generate the next obstacle only as the course progresses."""
        encounter.resolved = True
        selected = encounter.selected if encounter.status == "ready" else None
        optimal = selected == encounter.optimal() and not collision
        reward = -25 if collision else 0
        collision_reason = None
        if collision and encounter.kind == "crate" and self.action == "jump":
            collision_reason = (
                "Jump too late"
                if self.time - self.action_started < ACTION_SECONDS / 2
                else "Landed too soon"
            )
        self.score += reward
        if collision:
            self.lives -= 1
            self.hit_until = self.time + 0.4
        if selected is not None:
            self.timely += 1
            self.correct += int(optimal)
        self.history.append(
            Trace(
                id=encounter.id,
                kind=encounter.kind,
                action=selected,
                expected=encounter.optimal(),
                status=encounter.status,
                collision=collision,
                optimal=optimal,
                reward=reward,
                latency_ms=encounter.latency_ms,
                request=encounter.request,
                response=encounter.response,
                error=encounter.error,
                collision_reason=collision_reason,
            )
        )
        self.history = self.history[-HISTORY_LIMIT:]
        self.past.append(encounter)
        self.past = self.past[-2:]
        if self.lives == 0:
            self.phase = "finished"
            self.reason = "Three collisions. Try the same course again."
        else:
            self.current = self.following
            self.following = self.generate_following(self.current)

    def advance(self, target: float) -> None:
        """Advance fixed physics steps independently of inference and browser frame rate."""
        limit = target if self.duration is None else min(target, self.duration)
        while self.phase == "running" and self.time + STEP <= limit:
            self.time += STEP
            encounter = self.current
            if self.time >= encounter.deadline and encounter.status == "pending":
                encounter.status = "missed"
                encounter.error = "Jev missed the decision deadline."
                self.misses += 1
            if self.action == "jump" and self.time - self.action_started >= ACTION_SECONDS:
                self.action = "stand"
            self.score += SPEED * STEP * POINTS_PER_PIXEL[self.action]
            if (
                not encounter.resolved
                and self.time >= encounter.contact_start
                and (self.duration is None or encounter.contact_end <= self.duration)
            ):
                collision = encounter.collision(self.action, self.time, self.action_started)
                if collision or self.time > encounter.contact_end:
                    self.resolve(encounter, collision)
        if self.duration is not None and target >= self.duration and self.phase == "running":
            self.time = self.duration
            self.phase = "finished"
            self.reason = "Round complete."

    def frame(self) -> Frame:
        """Serialize the current world and trace without exposing future reference answers."""
        bottom, height = body(self.action, self.time - self.action_started)
        encounter = self.current
        decision = (
            None
            if encounter.status == "upcoming"
            else DecisionView(
                id=encounter.id,
                status=encounter.status,
                action=encounter.selected,
                seconds_left=max(0, encounter.deadline - self.time) / self.pace,
                probabilities=encounter.probabilities,
                confidence=encounter.confidence,
                latency_ms=encounter.latency_ms,
                request=encounter.request,
                response=encounter.response,
                error=encounter.error,
            )
        )
        return Frame(
            run_id=self.run_id,
            seed=self.seed,
            mode=self.mode,
            time=self.time,
            duration=self.duration,
            challenge=self.challenge,
            collisions=3 - self.lives,
            phase=self.phase,
            reason=self.reason,
            score=floor(self.score),
            lives=self.lives,
            action=self.action,
            action_age=self.time - self.action_started,
            speed=SPEED * self.pace,
            pace=self.pace,
            distance_m=SPEED * self.time / 10,
            player_y=bottom,
            player_height=height,
            hit=self.time < self.hit_until,
            obstacles=[
                ObstacleView(
                    id=item.id,
                    kind=item.kind,
                    x=item.x(self.time),
                    width=item.width,
                    bottom=item.bottom,
                    top=item.top,
                    trigger_in=item.trigger - self.time,
                    resolved=item.resolved,
                )
                for item in [*self.past, self.current, self.following]
                if item.x(self.time) > -80
            ],
            decision=self.last_decision if self.mode == "jev" and self.last_decision else decision,
            thinking=self.thinking,
            requests=self.requests,
            responses=self.responses,
            history=self.history,
            presented=self.presented,
            timely=self.timely,
            correct=self.correct,
            misses=self.misses,
            errors=self.errors,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=self.cost,
            model=self.model,
        )

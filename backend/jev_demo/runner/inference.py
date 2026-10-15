"""A single Jev Choice request for the runner, independent of Jira's three-question schema."""

from typing import Self

import httpx
from pydantic import BaseModel, model_validator

from ..models import ChoiceQuestion, Probability, Usage
from ..service import JevError, Settings, post_evaluation
from .world import ACTIONS, HEIGHT, LOOKAHEAD, Action


class RunnerChoice(BaseModel):
    """Validate the action and its complete probability distribution before execution."""

    choice: Action
    confidence: Probability
    probabilities: dict[Action, Probability]

    @model_validator(mode="after")
    def validate_choice(self) -> Self:
        """Reject missing, inconsistent, or non-normalized action probabilities."""
        if set(self.probabilities) != set(ACTIONS):
            raise ValueError("Expected all three actions.")
        if abs(sum(self.probabilities.values()) - 1) > 0.015:
            raise ValueError("Probabilities must sum to one.")
        if self.probabilities[self.choice] < max(self.probabilities.values()) - 0.001:
            raise ValueError("The selected action must have maximal probability.")
        return self


class RunnerAnswers(BaseModel):
    """Keep the application-defined action identifier in the provider response."""

    action: RunnerChoice


class RunnerResponse(BaseModel):
    """Retain validated usage and the resolved model for transparent cost estimates."""

    model: str
    answers: RunnerAnswers
    usage: Usage


class RunnerRequest(BaseModel):
    """Send only numerical world observations and one Choice question."""

    model: str
    state: str
    questions: dict[str, ChoiceQuestion]


def make_request(settings: Settings, state: str) -> RunnerRequest:
    """Describe the game objective without revealing the private physics oracle."""
    return RunnerRequest(
        model=settings.typesafe_model,
        state=state,
        questions={
            "action": ChoiceQuestion(
                instructions="Select the posture to apply NOW. Each response acts immediately; "
                "another observation follows. Obstacle phase is distant, approaching "
                f"(within {LOOKAHEAD:g} game seconds at estimated response arrival), "
                "or crossing (still overlapping). Phase already accounts for measured API "
                "delay and game speed: use phase for urgency, not the raw contact countdown. "
                "Check distance FIRST: if the obstacle is null or its phase is distant, "
                "choose stand when grounded, or jump only to finish an existing airborne "
                "jump. A distant crate/screen does not require avoiding yet. "
                "Only for approaching/crossing obstacles: an OVERHEAD SCREEN requires fitting "
                "UNDER its passage, even if currently jumping. Cancel the jump when needed. "
                "Otherwise continue an airborne jump until landing. When on the road, "
                "remain upright on clear/distant road and jump for an approaching ground "
                "crate. Maintain clearance until fully past the obstacle. Avoid collisions "
                "first; then maximize distance points.",
                criteria={
                    "stand": "Upright on the road: choose when grounded and next_obstacle is "
                    "null or distant. Also choose for an approaching/crossing overhead screen "
                    f"with passage_underneath_px >= {HEIGHT:g}, cancelling any jump. "
                    "Earns 1 point per metre.",
                    "jump": "Only when ALREADY AIRBORNE or a ground crate has phase "
                    "approaching/crossing (contact is near when the response arrives). "
                    "A distant crate while grounded does NOT qualify. Also "
                    "continue an existing airborne jump when no overhead screen is "
                    "approaching/crossing. Do not initiate a jump on clear/distant road. "
                    "Jump is unsuitable for an approaching/crossing overhead screen, "
                    "regardless of current posture. Earns zero points.",
                    "duck": "Only when an overhead screen has phase approaching/crossing "
                    "(contact is near when the response arrives). A distant "
                    "screen does NOT qualify. Go UNDER the screen whose "
                    f"passage_underneath_px < {HEIGHT:g}. Applies from EVERY posture, including "
                    "mid-jump: duck cancels the jump and crouches on the road immediately. "
                    "Keep ducking until fully past the screen. Earns 0.2 points per metre.",
                },
            )
        },
    )


async def infer(
    client: httpx.AsyncClient, settings: Settings, payload: RunnerRequest
) -> tuple[RunnerResponse, float]:
    """Perform real inference; a malformed response never becomes an invented action."""
    content, elapsed = await post_evaluation(client, settings, payload.model_dump_json())
    try:
        return RunnerResponse.model_validate_json(content), elapsed
    except ValueError as exc:
        raise JevError(502, "Jev returned an invalid action response.") from exc

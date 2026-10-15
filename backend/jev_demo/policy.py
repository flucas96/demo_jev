"""Inspectable business rules composed from independent Jev answers."""

from typing import Literal

from .models import Decision, JevResponse, Scenario


def validate_answers(scenario: Scenario, response: JevResponse) -> None:
    """Ensure returned alternatives match the preset that was actually evaluated."""
    if set(response.answers.choice.probabilities) != set(scenario.questions.choice.criteria):
        raise ValueError("Choice alternatives do not match the scenario.")
    if len(response.answers.score.probabilities) != len(scenario.questions.score.criteria):
        raise ValueError("Score levels do not match the scenario.")


def decide(scenario: Scenario, response: JevResponse, threshold: float) -> Decision:
    """Apply transparent demo policy without making any external changes."""
    validate_answers(scenario, response)
    choice, score, noul = response.answers.choice, response.answers.score, response.answers.noul
    confidence_reason = (
        f"Choice confidence {choice.confidence:.0%}; review threshold {threshold:.0%}."
    )

    def result(
        action: Literal["route", "review", "escalate"],
        destination: str,
        label: str,
        reasons: list[str],
    ) -> Decision:
        """Build a validated policy result with the active threshold."""
        return Decision(
            action=action,
            destination=destination,
            label=label,
            reasons=reasons,
            threshold=threshold,
        )

    if scenario.id == "triage":
        if noul.noul >= 0.85 and score.score >= 3 and score.confidence >= threshold:
            return result(
                "escalate",
                "Incident review",
                "Escalate to incident review",
                [
                    f"P(active outage) {noul.noul:.0%} meets the 85% incident gate.",
                    f"Impact {score.score:.2f}/4 with {score.confidence:.0%} score confidence.",
                    "A human confirms the incident; this demo does not page an on-call engineer.",
                ],
            )
        if noul.noul >= 0.85:
            return result(
                "review",
                "Incident review",
                "Review the possible outage",
                [
                    f"P(active outage) {noul.noul:.0%} meets the 85% incident gate.",
                    f"Impact {score.score:.2f}/4 or score confidence {score.confidence:.0%} "
                    "does not meet the escalation gate.",
                    "Uncertain impact keeps the possible outage with an incident reviewer.",
                ],
            )
        if choice.confidence < threshold or choice.choice == "other":
            return result(
                "review",
                "Triage queue",
                "Hold for human review",
                [
                    confidence_reason,
                    "The owning team is uncertain or outside the configured team list.",
                ],
            )
        return result(
            "route",
            choice.choice.title(),
            f"Route to {choice.choice.title()}",
            [
                confidence_reason,
                "Team confidence meets policy; Jira assignment is simulated.",
            ],
        )

    if scenario.id == "review":
        if choice.choice == "contradicted" or noul.noul >= 0.75:
            return result(
                "escalate",
                "Editorial review",
                "Flag response for correction",
                [
                    f"Verdict: {choice.choice}; P(unsupported claim) {noul.noul:.0%}.",
                    "An unsupported promise or contradiction blocks automatic approval.",
                ],
            )
        if (
            choice.choice != "supported"
            or choice.confidence < threshold
            or score.confidence < threshold
            or score.score < 3
            or noul.noul > 0.2
        ):
            return result(
                "review",
                "Support reviewer",
                "Review the evidence",
                [
                    confidence_reason,
                    "Approval needs supported content, both confidence gates, support ≥3/4, "
                    "and P(unsupported claim) ≤20%.",
                ],
            )
        return result(
            "route",
            "Approved draft",
            "Draft passes evidence checks",
            [
                confidence_reason,
                "All evidence gates passed. The demo does not send the reply.",
            ],
        )

    if (
        choice.choice == "irrelevant"
        or choice.confidence < threshold
        or score.confidence < threshold
        or score.score < 2
        or noul.noul < 0.7
    ):
        return result(
            "review",
            "Search queue",
            "Keep searching or review",
            [
                confidence_reason,
                f"Relevance {score.score:.2f}/4; P(component match) {noul.noul:.0%}.",
                "Shortlisting needs relevance ≥2, both confidence gates, and component match ≥70%.",
            ],
        )
    return result(
        "route",
        "Runbook shortlist",
        "Add to the runbook shortlist",
        [
            confidence_reason,
            f"Relevance {score.score:.2f}/4 and component match {noul.noul:.0%} meet policy.",
            "A suggested runbook is not executed by this demo.",
        ],
    )

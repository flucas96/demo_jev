"""Exercise live transport boundaries and deterministic policy behavior."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from math import floor

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from jev_demo.app import create_app
from jev_demo.catalog import SCENARIOS
from jev_demo.models import (
    Answers,
    ChoiceAnswer,
    Decision,
    Evaluation,
    JevResponse,
    NoulAnswer,
    ScoreAnswer,
    Usage,
)
from jev_demo.service import Settings

DUMMY_KEY = "test-only-private-key"
PRIVATE_ERROR = "provider-internal-message-with-private-data"
JSON_OBJECT = TypeAdapter(dict[str, object])
type TransportHandler = Callable[[httpx.Request], httpx.Response]


def answer(
    scenario_id: str = "triage",
    *,
    model: str = "jev-latest",
    choice: str | None = None,
    choice_confidence: float = 0.85,
    score: float = 2.5,
    score_confidence: float = 0.9,
    noul: float = 0.1,
) -> JevResponse:
    """Build a valid provider answer while varying individual policy signals."""
    scenario = SCENARIOS[scenario_id]
    selected = choice if choice is not None else next(iter(scenario.questions.choice.criteria))
    alternatives = scenario.questions.choice.criteria
    probabilities = {
        option: 0.9 if option == selected else 0.1 / (len(alternatives) - 1)
        for option in alternatives
    }
    score_probabilities = dict.fromkeys(
        (str(level) for level in range(len(scenario.questions.score.criteria))), 0.0
    )
    lower = floor(score)
    fraction = score - lower
    score_probabilities[str(lower)] = 1 - fraction
    if fraction:
        score_probabilities[str(lower + 1)] = fraction
    return JevResponse(
        model=model,
        answers=Answers(
            choice=ChoiceAnswer(
                type="choice",
                choice=selected,
                confidence=choice_confidence,
                probabilities=probabilities,
            ),
            score=ScoreAnswer(
                type="score",
                score=score,
                confidence=score_confidence,
                probabilities=score_probabilities,
                legend={
                    str(index): criterion
                    for index, criterion in enumerate(scenario.questions.score.criteria)
                },
            ),
            noul=NoulAnswer(type="noul", noul=noul),
        ),
        usage=Usage(input_tokens=123, output_tokens=17),
    )


@contextmanager
def mock_client(handler: TransportHandler, *, key: str = DUMMY_KEY) -> Generator[httpx.Client]:
    """Run an isolated app that cannot contact the real provider or use its credential."""
    settings = Settings.model_construct(
        typesafe_api_key=SecretStr(key), typesafe_model="jev-latest"
    )
    with TestClient(create_app(settings, httpx.MockTransport(handler))) as client:
        yield client


def never_request(_request: httpx.Request) -> httpx.Response:
    """Fail if a local-only operation reaches the upstream transport."""
    raise AssertionError("This operation must not contact TypeSafe.")


def assert_safe_failure(response: httpx.Response, status_code: int) -> None:
    """Check a failed evaluation contains neither a fabricated result nor provider secrets."""
    assert response.status_code == status_code
    assert set(JSON_OBJECT.validate_json(response.content)) == {"detail"}
    assert DUMMY_KEY not in response.text
    assert PRIVATE_ERROR not in response.text
    assert "Bearer" not in response.text


@pytest.mark.parametrize("text", ["  Login fails for one workspace.  ", "a" * 16000])
def test_evaluate_sends_all_three_primitives_and_keeps_auth_upstream(text: str) -> None:
    """A single live request uses the documented URL and returns typed, credential-free results."""
    requests: list[httpx.Request] = []
    provider_answer = answer()

    def respond(request: httpx.Request) -> httpx.Response:
        """Record the outbound request and return a valid model response."""
        requests.append(request)
        return httpx.Response(200, json=provider_answer.model_dump(mode="json"))

    with mock_client(respond) as client:
        response = client.post(
            "/api/evaluate",
            json={"scenario_id": "triage", "text": text},
        )
        health = client.get("/api/health")

    assert response.status_code == 200
    result = Evaluation.model_validate_json(response.content)
    assert result.source == "live"
    assert result.response == provider_answer
    assert result.elapsed_ms >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["Authorization"] == f"Bearer {DUMMY_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    body = JSON_OBJECT.validate_json(request.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "jev-latest"
    assert body["state"] == text.strip()
    assert body == result.request.model_dump(mode="json", exclude_none=True)
    questions = JSON_OBJECT.validate_python(body["questions"])
    assert set(questions) == {"choice", "score", "noul"}
    assert result.request.questions.choice.type == "choice"
    assert result.request.questions.score.type == "score"
    assert result.request.questions.noul.type == "noul"
    assert result.request.questions.noul.criteria is not None
    assert set(result.request.questions.noul.criteria) == {"true", "false"}
    assert DUMMY_KEY not in response.text + health.text
    assert f"Bearer {DUMMY_KEY}" not in response.text
    assert '"authorization":' not in response.text.lower()
    assert "Authorization" not in response.headers


def test_missing_key_stops_before_contacting_provider() -> None:
    """An unconfigured server returns an actionable failure without pretending to evaluate."""
    with mock_client(never_request, key="") as client:
        response = client.post(
            "/api/evaluate", json={"scenario_id": "triage", "text": "Login fails."}
        )
        health = client.get("/api/health")
    assert_safe_failure(response, 503)
    assert JSON_OBJECT.validate_json(health.content)["configured"] is False


@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(401, 502), (403, 502), (429, 503), (529, 503), (500, 502)],
)
def test_upstream_http_failures_are_safe_and_never_fall_back(
    upstream_status: int, expected_status: int
) -> None:
    """Provider failures expose only a safe local error, including when its body leaks a key."""
    requests: list[httpx.Request] = []

    def fail(request: httpx.Request) -> httpx.Response:
        """Return a provider failure with content that must remain server-side."""
        requests.append(request)
        return httpx.Response(upstream_status, text=f"{PRIVATE_ERROR} Bearer {DUMMY_KEY}")

    with mock_client(fail) as client:
        response = client.post(
            "/api/evaluate", json={"scenario_id": "triage", "text": "Login fails."}
        )
    assert_safe_failure(response, expected_status)
    assert len(requests) == 1


@pytest.mark.parametrize("timeout", [True, False])
def test_transport_failures_do_not_expose_exception_details(timeout: bool) -> None:
    """Timeout and connectivity exceptions remain safe even with sensitive exception messages."""

    def fail(request: httpx.Request) -> httpx.Response:
        """Raise a transport error instead of returning an HTTP response."""
        error = httpx.ReadTimeout if timeout else httpx.ConnectError
        raise error(f"{PRIVATE_ERROR} {DUMMY_KEY}", request=request)

    with mock_client(fail) as client:
        response = client.post(
            "/api/evaluate", json={"scenario_id": "triage", "text": "Login fails."}
        )
    assert_safe_failure(response, 504 if timeout else 502)


@pytest.mark.parametrize("malformed", ["invalid-json", "wrong-scenario", "contradiction"])
def test_malformed_provider_answers_do_not_create_decisions(malformed: str) -> None:
    """Invalid JSON, mismatched alternatives, and inconsistent distributions fail closed."""

    def respond(_request: httpx.Request) -> httpx.Response:
        """Return a syntactically or semantically invalid provider result."""
        if malformed == "invalid-json":
            return httpx.Response(200, text=f"{PRIVATE_ERROR} {DUMMY_KEY}")
        provider_answer = answer("review" if malformed == "wrong-scenario" else "triage")
        if malformed == "contradiction":
            provider_answer.answers.score.score = 4
        return httpx.Response(200, json=provider_answer.model_dump(mode="json"))

    with mock_client(respond) as client:
        response = client.post(
            "/api/evaluate", json={"scenario_id": "triage", "text": "Login fails."}
        )
    assert_safe_failure(response, 502)


@pytest.mark.parametrize("text", ["", " \n\t ", "a" * 16001])
def test_invalid_input_is_rejected_before_inference(text: str) -> None:
    """Blank and oversized text cannot consume provider calls."""
    with mock_client(never_request) as client:
        response = client.post("/api/evaluate", json={"scenario_id": "triage", "text": text})
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["/api/evaluate", "/api/policy"])
def test_unknown_scenarios_are_rejected(endpoint: str) -> None:
    """Neither live inference nor replay silently assigns unknown presets a default policy."""
    payload: dict[str, object] = {"scenario_id": "unknown"}
    if endpoint == "/api/evaluate":
        payload["text"] = "Login fails."
    else:
        payload.update(threshold=0.8, response=answer().model_dump(mode="json"))
    with mock_client(never_request) as client:
        response = client.post(endpoint, json=payload)
    assert response.status_code == 404


def test_threshold_replay_uses_the_same_answer_without_provider_calls() -> None:
    """Changing the threshold across a confidence boundary changes policy without inference."""
    cached_answer = answer(choice="identity", choice_confidence=0.85).model_dump(mode="json")
    with mock_client(never_request, key="") as client:
        responses = [
            client.post(
                "/api/policy",
                json={"scenario_id": "triage", "response": cached_answer, "threshold": threshold},
            )
            for threshold in (0.85, 0.851)
        ]
    assert all(response.status_code == 200 for response in responses)
    at_boundary, above_boundary = (
        Decision.model_validate_json(response.content) for response in responses
    )
    assert at_boundary.action == "route"
    assert at_boundary.destination == "Identity"
    assert above_boundary.action == "review"


def test_increasing_threshold_keeps_possible_outage_with_incident_review() -> None:
    """A stricter confidence threshold can defer escalation but cannot route away an outage."""
    cached_answer = answer(choice_confidence=0.99, score=3.5, score_confidence=0.85, noul=0.95)
    at_boundary, above_boundary, maximum_threshold = (
        replay("triage", cached_answer, threshold=threshold) for threshold in (0.85, 0.851, 1.0)
    )
    assert at_boundary.action == "escalate"
    assert above_boundary.action == maximum_threshold.action == "review"
    assert all(
        decision.destination == "Incident review"
        for decision in (at_boundary, above_boundary, maximum_threshold)
    )


@pytest.mark.parametrize(
    ("choice", "choice_confidence", "score", "score_confidence", "noul", "expected"),
    [
        ("platform", 0.9, 3.0, 0.8, 0.85, "escalate"),
        ("platform", 0.9, 3.0, 0.799, 0.85, "review"),
        ("platform", 0.9, 2.999, 0.9, 0.85, "review"),
        ("platform", 0.9, 3.0, 0.9, 0.849, "route"),
        ("other", 0.99, 2.0, 0.9, 0.1, "review"),
    ],
)
def test_triage_requires_all_incident_gates(
    choice: str,
    choice_confidence: float,
    score: float,
    score_confidence: float,
    noul: float,
    expected: str,
) -> None:
    """Incident escalation requires outage probability, impact, and score confidence together."""
    provider_answer = answer(
        choice=choice,
        choice_confidence=choice_confidence,
        score=score,
        score_confidence=score_confidence,
        noul=noul,
    )
    decision = replay("triage", provider_answer)
    assert decision.action == expected
    if noul >= 0.85:
        assert decision.destination == "Incident review"


@pytest.mark.parametrize(
    ("choice", "choice_confidence", "score", "score_confidence", "noul", "expected"),
    [
        ("supported", 0.8, 3.0, 0.8, 0.2, "route"),
        ("supported", 0.799, 3.0, 0.8, 0.2, "review"),
        ("supported", 0.8, 3.0, 0.799, 0.2, "review"),
        ("supported", 0.8, 2.999, 0.8, 0.2, "review"),
        ("supported", 0.8, 3.0, 0.8, 0.201, "review"),
        ("insufficient", 0.9, 4.0, 0.9, 0.1, "review"),
        ("contradicted", 0.9, 4.0, 0.9, 0.1, "escalate"),
        ("supported", 0.9, 4.0, 0.9, 0.75, "escalate"),
    ],
)
def test_reply_verification_requires_every_approval_gate(
    choice: str,
    choice_confidence: float,
    score: float,
    score_confidence: float,
    noul: float,
    expected: str,
) -> None:
    """A reply passes only with supported claims and every confidence and evidence gate met."""
    provider_answer = answer(
        "review",
        choice=choice,
        choice_confidence=choice_confidence,
        score=score,
        score_confidence=score_confidence,
        noul=noul,
    )
    assert replay("review", provider_answer).action == expected


@pytest.mark.parametrize(
    ("choice", "choice_confidence", "score", "score_confidence", "noul", "expected"),
    [
        ("mitigation", 0.8, 2.0, 0.8, 0.7, "route"),
        ("diagnostic", 0.8, 2.0, 0.8, 0.7, "route"),
        ("mitigation", 0.799, 2.0, 0.8, 0.7, "review"),
        ("mitigation", 0.8, 2.0, 0.799, 0.7, "review"),
        ("mitigation", 0.8, 1.999, 0.8, 0.7, "review"),
        ("mitigation", 0.8, 2.0, 0.8, 0.699, "review"),
        ("irrelevant", 0.99, 4.0, 0.99, 0.99, "review"),
    ],
)
def test_runbook_shortlist_requires_every_relevance_gate(
    choice: str,
    choice_confidence: float,
    score: float,
    score_confidence: float,
    noul: float,
    expected: str,
) -> None:
    """A runbook can enter the shortlist only after all relevance and component checks pass."""
    provider_answer = answer(
        "search",
        choice=choice,
        choice_confidence=choice_confidence,
        score=score,
        score_confidence=score_confidence,
        noul=noul,
    )
    assert replay("search", provider_answer).action == expected


def replay(scenario_id: str, response: JevResponse, *, threshold: float = 0.8) -> Decision:
    """Exercise the public policy endpoint while making outbound access a test failure."""
    with mock_client(never_request, key="") as client:
        result = client.post(
            "/api/policy",
            json={
                "scenario_id": scenario_id,
                "response": response.model_dump(mode="json"),
                "threshold": threshold,
            },
        )
    assert result.status_code == 200
    return Decision.model_validate_json(result.content)

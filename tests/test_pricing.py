"""Keep published input-token estimates separate from unsupported pricing and provider bills."""

import httpx
import pytest
from test_workbench import answer, mock_client

from jev_demo.models import Evaluation
from jev_demo.pricing import estimate_cost_usd


@pytest.mark.parametrize(
    ("model", "input_tokens", "expected"),
    [
        ("jev-1.13.0", 1_000_000, 0.042),
        ("jev-1.14.0", 1_000_000, 0.042),
        ("jev-1.13.0", 0, 0.0),
        ("jev-latest", 1_000_000, None),
        ("jev-2.0.0", 1_000_000, None),
        (None, 1_000_000, None),
    ],
)
def test_estimate_requires_a_known_resolved_model(
    model: str | None, input_tokens: int, expected: float | None
) -> None:
    """Apply the published price only to its exact versioned model, including zero usage."""
    assert estimate_cost_usd(model, input_tokens) == expected


@pytest.mark.parametrize("output_tokens", [0, 1_000_000])
def test_evaluation_prices_resolved_input_usage_once_and_output_is_free(output_tokens: int) -> None:
    """One three-question request is priced once using the returned model and input usage."""
    provider_answer = answer(model="jev-1.13.0")
    provider_answer.usage.input_tokens = 1_000_000
    provider_answer.usage.output_tokens = output_tokens

    def respond(_request: httpx.Request) -> httpx.Response:
        """Resolve the configured alias to the known priced version."""
        return httpx.Response(200, json=provider_answer.model_dump(mode="json"))

    with mock_client(respond) as client:
        response = client.post(
            "/api/evaluate", json={"scenario_id": "triage", "text": "The login page fails."}
        )
    assert response.status_code == 200
    evaluation = Evaluation.model_validate_json(response.content)
    assert evaluation.request.model == "jev-latest"
    assert evaluation.response.model == "jev-1.13.0"
    assert evaluation.estimated_cost_usd == 0.042

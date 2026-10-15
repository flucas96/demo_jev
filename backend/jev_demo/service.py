"""Small async TypeSafe adapter with strict response validation and safe errors."""

from pathlib import Path
from time import perf_counter

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import EvaluateRequest, Evaluation, JevRequest, JevResponse, Scenario
from .policy import decide
from .pricing import estimate_cost_usd

API_URL = "https://api.typesafe.ai/v1/systemone"


class Settings(BaseSettings):
    """Load server-only credentials from environment variables or the ignored .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    typesafe_api_key: SecretStr = SecretStr("")
    typesafe_model: str = "jev-latest"
    ai_gateway_api_key: SecretStr = SecretStr("")
    ai_gateway_base_url: str = "https://ai-gateway.eraneos.com/v1"
    waldo_history_path: Path | None = Path(".local/waldo.sqlite3")


class JevError(Exception):
    """A safe, user-facing failure that never includes headers or provider bodies."""

    def __init__(self, status_code: int, message: str) -> None:
        """Retain the local HTTP status and a credential-free explanation."""
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def post_evaluation(
    client: httpx.AsyncClient, settings: Settings, payload: str, *, image_input: bool = False
) -> tuple[bytes, float]:
    """Send a typed request using shared credential handling and safe transport errors."""
    if not settings.typesafe_api_key.get_secret_value():
        raise JevError(503, "Configure TYPESAFE_API_KEY on the server.")
    started = perf_counter()
    headers = {"Authorization": f"Bearer {settings.typesafe_api_key.get_secret_value()}"}
    if image_input:
        headers["TypeSafe-Danger-Zone-Images"] = "true"
    try:
        upstream = await client.post(
            API_URL,
            headers=headers,
            content=payload,
        )
    except httpx.TimeoutException as exc:
        raise JevError(504, "TypeSafe did not respond in time. Try again.") from exc
    except httpx.RequestError as exc:
        raise JevError(
            502, "Could not reach TypeSafe. Check the server's network connection."
        ) from exc
    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    if upstream.status_code in (401, 403):
        raise JevError(502, "TypeSafe rejected the server API key. Check TYPESAFE_API_KEY.")
    if upstream.status_code in (429, 529):
        raise JevError(
            503, "TypeSafe is busy or the rate limit was reached. Wait briefly and retry."
        )
    if upstream.is_error:
        raise JevError(502, f"TypeSafe returned HTTP {upstream.status_code}. Try again later.")
    return upstream.content, elapsed_ms


async def evaluate(
    client: httpx.AsyncClient, settings: Settings, scenario: Scenario, request: EvaluateRequest
) -> Evaluation:
    """Evaluate three primitives in one request and compose the returned policy."""
    if not settings.typesafe_api_key.get_secret_value():
        raise JevError(503, "Set TYPESAFE_API_KEY in the server's .env file, then restart it.")
    payload = JevRequest(
        model=settings.typesafe_model, state=request.text, questions=scenario.questions
    )
    content, elapsed_ms = await post_evaluation(
        client, settings, payload.model_dump_json(exclude_none=True)
    )
    try:
        response = JevResponse.model_validate_json(content)
        decision = decide(scenario, response, request.threshold)
    except ValueError as exc:
        raise JevError(
            502, "TypeSafe returned an unexpected response. No routing decision was made."
        ) from exc
    return Evaluation(
        request=payload,
        response=response,
        elapsed_ms=elapsed_ms,
        decision=decision,
        estimated_cost_usd=estimate_cost_usd(response.model, response.usage.input_tokens),
    )

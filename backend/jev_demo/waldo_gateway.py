"""Image localization through the gateway, preserving reported usage and request cost."""

import base64
import math
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .models import Usage
from .service import JevError, Settings
from .waldo_geometry import Box

DEFAULT_MODEL = "claude-opus-5-5"
PROMPT = (
    "Where is Waldo in this image? Return only JSON with left, top, right, bottom: "
    "the bounding box of Waldo, normalized to [0,1] relative to the full image. "
    "Origin is the top-left. Do not include explanations."
)


class ModelOption(BaseModel):
    """A vision-capable model and published gateway list prices dated 2026-10-15."""

    id: str
    label: str
    input_price: float
    output_price: float
    provider: Literal["gateway", "typesafe"] = "gateway"


GATEWAY_MODELS = [
    ModelOption(id=id, label=label, input_price=input_price, output_price=output_price)
    for id, label, input_price, output_price in [
        (DEFAULT_MODEL, "Claude Opus 5.5", 4.4, 22.0),
        ("claude-opus-5", "Claude Opus 5", 5.5, 27.5),
        ("claude-opus-4-5", "Claude Opus 4.5", 5.5, 27.5),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5", 2.2, 11.0),
        ("claude-sonnet-5", "Claude Sonnet 5", 2.2, 11.0),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5", 3.3, 16.5),
        ("claude-haiku-4-5", "Claude Haiku 4.5", 1.1, 5.5),
        ("gemini-3.8-flash", "Gemini 3.8 Flash", 0.83, 4.13),
        ("gemini-3.5-flash", "Gemini 3.5 Flash", 1.5, 9.0),
        ("gemini-3.1-flash-lite-preview", "Gemini 3.1 Flash Lite", 0.25, 1.5),
        ("gemini-3-flash-preview", "Gemini 3 Flash", 0.5, 3.0),
        ("gemini-3-pro-preview", "Gemini 3 Pro", 2.0, 12.0),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", 1.25, 10.0),
        ("gpt-6-luna", "GPT-6 Luna", 0.1, 0.5),
        ("gpt-6-sol", "GPT-6 Sol", 2.0, 10.0),
        ("gpt-5.1", "GPT-5.1", 1.25, 10.0),
    ]
]
BY_MODEL = {model.id: model for model in GATEWAY_MODELS}


@dataclass(frozen=True)
class Localization:
    """One model response; missing geometry is a scored miss, never a fabricated box."""

    model: str
    box: Box | None
    confidence: float | None
    usage: Usage | None
    elapsed_ms: float
    cost_usd: float | None
    cost_basis: Literal["gateway", "estimate", "unknown"]


class ModelId(BaseModel):
    """The public identifier from the gateway's accessible-model list."""

    id: str


class ModelList(BaseModel):
    """Keep internal gateway metadata out of the browser."""

    data: list[ModelId]


class GatewayUsage(BaseModel):
    """Only provider-reported token counts are considered usage."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class Message(BaseModel):
    """A plain text completion; refusals and empty content cannot become valid geometry."""

    content: str | None = None


class Choice(BaseModel):
    """A single non-streaming model completion."""

    message: Message


class Completion(BaseModel):
    """Validate the gateway response envelope before interpreting its generated JSON."""

    model: str
    choices: list[Choice] = Field(min_length=1)
    usage: GatewayUsage | None = None


def headers(settings: Settings) -> dict[str, str]:
    """Build server-only authentication, without ever returning it to the interface."""
    key = settings.ai_gateway_api_key.get_secret_value()
    if not key:
        raise JevError(503, "Configure AI_GATEWAY_API_KEY on the server.")
    return {"Authorization": f"Bearer {key}"}


def check_response(response: httpx.Response) -> None:
    """Avoid exposing upstream error bodies or credential-bearing request objects."""
    if response.status_code in (401, 403):
        raise JevError(502, "The gateway rejected the key or model access.")
    if response.status_code in (402, 429):
        raise JevError(
            503, "Gateway budget or request limit reached. Check your account in the portal."
        )
    if response.is_error:
        raise JevError(502, f"Gateway unavailable (HTTP {response.status_code}).")


async def available_models(client: httpx.AsyncClient, settings: Settings) -> list[ModelOption]:
    """Intersect key-accessible models with the catalogue's verified image capabilities."""
    try:
        response = await client.get(
            f"{settings.ai_gateway_base_url.rstrip('/')}/models", headers=headers(settings)
        )
    except httpx.RequestError as exc:
        raise JevError(502, "The gateway model catalogue is unreachable.") from exc
    check_response(response)
    try:
        ids = {item.id for item in ModelList.model_validate_json(response.content).data}
    except ValueError as exc:
        raise JevError(502, "The gateway model catalogue returned an unexpected format.") from exc
    return [model for model in GATEWAY_MODELS if model.id in ids]


def response_cost(response: httpx.Response) -> float | None:
    """Prefer the gateway's per-call cost, including provider cache charges."""
    try:
        cost = float(response.headers["x-litellm-response-cost"])
    except KeyError, ValueError:
        return None
    return cost if math.isfinite(cost) and cost >= 0 else None


async def infer(
    client: httpx.AsyncClient, settings: Settings, model: str, image: bytes
) -> Localization:
    """Ask once for a normalized box using identical unmarked image bytes and no position hints."""
    if model not in BY_MODEL:
        raise JevError(422, "This model is not enabled for image localization.")
    payload = {
        "model": model,
        "max_tokens": 256,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64,"
                            + base64.b64encode(image).decode("ascii")
                        },
                    },
                ],
            }
        ],
    }
    started = perf_counter()
    try:
        response = await client.post(
            f"{settings.ai_gateway_base_url.rstrip('/')}/chat/completions",
            headers=headers(settings),
            json=payload,
            timeout=90,
        )
    except httpx.TimeoutException as exc:
        raise JevError(504, "The gateway did not respond in time.") from exc
    except httpx.RequestError as exc:
        raise JevError(502, "The gateway connection was interrupted.") from exc
    elapsed = round((perf_counter() - started) * 1000, 1)
    check_response(response)
    try:
        completion = Completion.model_validate_json(response.content)
    except ValueError as exc:
        raise JevError(502, "The gateway returned an invalid response.") from exc
    content = (completion.choices[0].message.content or "").strip()
    if content.startswith("```") and content.endswith("```"):
        content = "\n".join(content.splitlines()[1:-1])
    try:
        box = Box.model_validate_json(content)
    except ValueError:
        box = None
    usage = (
        Usage(
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
        )
        if completion.usage
        else None
    )
    cost = response_cost(response)
    basis: Literal["gateway", "estimate", "unknown"] = "gateway" if cost is not None else "unknown"
    if cost is None and usage is not None:
        price = BY_MODEL[model]
        cost = (
            usage.input_tokens * price.input_price + usage.output_tokens * price.output_price
        ) / 1e6
        basis = "estimate"
    return Localization(completion.model, box, None, usage, elapsed, cost, basis)

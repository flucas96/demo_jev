"""Published TypeSafe pricing verified at https://docs.typesafe.ai/models on 2026-10-15."""


def estimate_cost_usd(model: str | None, input_tokens: int) -> float | None:
    """Estimate known-model input usage in USD; output tokens are free and aliases are unpriced."""
    if model not in {"jev-1.13.0", "jev-1.14.0"}:
        return None
    return input_tokens * 0.042 / 1_000_000

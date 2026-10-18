"""Token usage and what it costs."""

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from arl import ROOT

MODELS_FILE = ROOT / "config" / "models.yaml"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0          # all input tokens, cached ones included
    cached_input_tokens: int = 0   # the part of input_tokens read from the prompt cache
    output_tokens: int = 0         # all output tokens, reasoning ones included
    reasoning_tokens: int = 0      # the part of output_tokens spent on reasoning

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(*(a + b for a, b in zip(asdict(self).values(), asdict(other).values())))


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""
    input: float
    cached_input: float
    output: float


def load_models(path: Path = MODELS_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def price_for(model: str, path: Path = MODELS_FILE) -> Price:
    models = load_models(path)["models"]
    if model not in models:
        raise KeyError(f"No price for model '{model}' in {path}. Add it before running.")
    entry = models[model]
    return Price(entry["input"], entry["cached_input"], entry["output"])


def cost_usd(usage: Usage, price: Price) -> float:
    fresh_input = usage.input_tokens - usage.cached_input_tokens
    return (
        fresh_input * price.input
        + usage.cached_input_tokens * price.cached_input
        + usage.output_tokens * price.output
    ) / 1_000_000

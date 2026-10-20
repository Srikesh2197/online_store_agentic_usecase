"""Model config and what a call costs."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from arl import ROOT
from arl.llm.types import Usage

MODELS_FILE = ROOT / "config" / "models.yaml"


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""
    input: float
    cached_input: float
    output: float
    cache_write: float | None = None   # None: writing to the cache costs the input price


def load_models(path: Path = MODELS_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def model_entry(model: str, path: Path = MODELS_FILE) -> dict:
    models = load_models(path)["models"]
    if model not in models:
        raise KeyError(f"No entry for model '{model}' in {path}. Add it before running.")
    return models[model]


def price_for(model: str, path: Path = MODELS_FILE) -> Price:
    entry = model_entry(model, path)
    return Price(entry["input"], entry["cached_input"], entry["output"], entry.get("cache_write"))


def cost_usd(usage: Usage, price: Price) -> float:
    fresh_input = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    cache_write = price.input if price.cache_write is None else price.cache_write
    return (
        fresh_input * price.input
        + usage.cached_input_tokens * price.cached_input
        + usage.cache_write_tokens * cache_write
        + usage.output_tokens * price.output
    ) / 1_000_000

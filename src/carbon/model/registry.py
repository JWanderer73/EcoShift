"""Model registry: name -> class. Choose the model with CARBON_MODEL."""

from __future__ import annotations

from carbon.model.base import Model
from carbon.model.models import HourOfDayMean, SeasonalNaive

MODELS: dict[str, type[Model]] = {
    SeasonalNaive.name: SeasonalNaive,
    HourOfDayMean.name: HourOfDayMean,
}


def get_model_class(name: str) -> type[Model]:
    try:
        return MODELS[name]
    except KeyError:
        raise ValueError(f"Unknown model '{name}'. Available: {', '.join(sorted(MODELS))}") from None


def load_model(d: dict) -> Model:
    return get_model_class(d["name"]).from_params(d["params"])

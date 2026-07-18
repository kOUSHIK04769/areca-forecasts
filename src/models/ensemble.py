"""
src/models/ensemble.py
=======================
Combines predictions from whichever models were successfully trained
(tree models always; Prophet/LSTM/GRU only if data volume allowed).
Weighting is inverse-CV-MAE: a model that historically errs less gets
more say in the blended price. This also naturally handles the case
where only 2-3 models are available - weights renormalize automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ModelPrediction:
    name: str
    predicted_price: float
    cv_mae: float


def compute_weights(predictions: list[ModelPrediction]) -> dict[str, float]:
    inv_errors = {p.name: 1.0 / max(p.cv_mae, 1e-6) for p in predictions}
    total = sum(inv_errors.values())
    return {name: val / total for name, val in inv_errors.items()}


def blend(predictions: list[ModelPrediction]) -> dict:
    if not predictions:
        raise ValueError("No model predictions to ensemble.")
    weights = compute_weights(predictions)
    blended_price = sum(p.predicted_price * weights[p.name] for p in predictions)

    # Confidence: models that agree with each other (low spread relative to
    # price level) AND have low historical error both raise confidence.
    prices = np.array([p.predicted_price for p in predictions])
    spread_pct = (prices.std() / max(prices.mean(), 1)) * 100
    avg_mae_pct = np.mean([p.cv_mae for p in predictions]) / max(blended_price, 1) * 100

    # Simple bounded scoring: starts at 95, penalized by disagreement and error.
    confidence = 95 - (spread_pct * 4) - (avg_mae_pct * 2)
    confidence = float(np.clip(confidence, 35, 96))

    # With a single model there is no cross-model disagreement signal at all,
    # so "confidence" is really just "low historical error" - cap it so the
    # UI doesn't imply an ensemble-strength guarantee it can't back up.
    single_model = len(predictions) == 1
    if single_model:
        confidence = float(min(confidence, 70.0))

    return {
        "blended_price": round(float(blended_price), 2),
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "model_predictions": {p.name: round(p.predicted_price, 2) for p in predictions},
        "confidence_pct": round(confidence, 1),
        "spread_pct": round(float(spread_pct), 2),
        "single_model": single_model,
    }

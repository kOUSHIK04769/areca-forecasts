"""
src/models/train.py
====================
Trains the model zoo on the engineered feature matrix and saves each
trained model to disk. Honest data-volume gating:

  rows >= 20   -> XGBoost, RandomForest, LightGBM (tree models cope
                  fine with small tabular data)
  rows >= 60   -> + Prophet (needs a usable trend/seasonality window)
  rows >= 180  -> + LSTM, GRU (sequence models; anything less and they
                  will just overfit / memorize)

Each model reports its own TimeSeriesSplit cross-validated MAE, which
`ensemble.py` uses to weight the blend (lower error = more weight).
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit

from config import MODEL_DIR, settings
from src.features.engineering import FEATURE_COLUMNS
from src.logging_setup import get_logger

log = get_logger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class TrainedModel:
    name: str
    estimator: object
    cv_mae: float
    feature_columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))


def _make_supervised(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Target = next day's modal_price. Drops the last row (no label yet) and
    any rows where required features are still NaN (early history warm-up)."""
    data = df.copy()
    data["target"] = data["modal_price"].shift(-1)
    data = data.dropna(subset=["target"])
    X = data[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median(numeric_only=True)).fillna(0.0)
    y = data["target"]
    return X, y


def _cv_splits(n_rows: int) -> int:
    # Need at least splits+1 samples per fold; shrink gracefully on short history.
    max_splits = max(2, min(settings.cv_splits, n_rows // 5))
    return max_splits


def _cv_mae(estimator, X: pd.DataFrame, y: pd.Series) -> float:
    n_splits = _cv_splits(len(X))
    if len(X) <= n_splits:
        # Not enough rows for CV at all - fall back to in-sample MAE, flagged clearly.
        estimator.fit(X, y)
        preds = estimator.predict(X)
        return float(mean_absolute_error(y, preds))

    tscv = TimeSeriesSplit(n_splits=n_splits)
    errors = []
    for train_idx, test_idx in tscv.split(X):
        model_clone = estimator.__class__(**estimator.get_params())
        model_clone.fit(X.iloc[train_idx], y.iloc[train_idx])
        preds = model_clone.predict(X.iloc[test_idx])
        errors.append(mean_absolute_error(y.iloc[test_idx], preds))
    return float(np.mean(errors))


def train_random_forest(X: pd.DataFrame, y: pd.Series) -> TrainedModel:
    base = RandomForestRegressor(random_state=42, n_jobs=-1)
    param_dist = {
        "n_estimators": [100, 200, 300],
        "max_depth": [3, 5, 8, None],
        "min_samples_leaf": [1, 2, 4],
    }
    n_splits = _cv_splits(len(X))
    if len(X) > n_splits * 2:
        search = RandomizedSearchCV(
            base, param_dist, n_iter=6, cv=TimeSeriesSplit(n_splits=n_splits),
            scoring="neg_mean_absolute_error", random_state=42, n_jobs=-1,
        )
        search.fit(X, y)
        best = search.best_estimator_
    else:
        best = base
        best.fit(X, y)
    mae = _cv_mae(best, X, y)
    return TrainedModel("random_forest", best, mae)


def train_xgboost(X: pd.DataFrame, y: pd.Series) -> TrainedModel | None:
    try:
        from xgboost import XGBRegressor
    except ImportError:
        log.warning("xgboost not installed (`pip install xgboost`) - skipping this model.")
        return None
    base = XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.9, colsample_bytree=0.9, random_state=42,
    )
    base.fit(X, y)
    mae = _cv_mae(base, X, y)
    return TrainedModel("xgboost", base, mae)


def train_lightgbm(X: pd.DataFrame, y: pd.Series) -> TrainedModel | None:
    try:
        from lightgbm import LGBMRegressor
    except ImportError:
        log.warning("lightgbm not installed (`pip install lightgbm`) - skipping this model.")
        return None
    base = LGBMRegressor(n_estimators=200, max_depth=5, learning_rate=0.05, random_state=42, verbose=-1)
    base.fit(X, y)
    mae = _cv_mae(base, X, y)
    return TrainedModel("lightgbm", base, mae)


def train_prophet(price_df: pd.DataFrame) -> TrainedModel | None:
    if len(price_df) < settings.min_rows_for_prophet:
        log.info(
            "Skipping Prophet - only %d rows of history (need >= %d).",
            len(price_df), settings.min_rows_for_prophet,
        )
        return None
    try:
        from prophet import Prophet
    except ImportError:
        log.warning("prophet not installed (`pip install prophet`) - skipping this model.")
        return None

    ts = price_df.rename(columns={"date": "ds", "modal_price": "y"})[["ds", "y"]]
    model = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
    model.fit(ts)

    # crude walk-forward MAE on the last 20% as a holdout
    split = int(len(ts) * 0.8)
    holdout_model = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
    holdout_model.fit(ts.iloc[:split])
    future = holdout_model.make_future_dataframe(periods=len(ts) - split)
    forecast = holdout_model.predict(future)
    preds = forecast.iloc[split:]["yhat"].values
    actual = ts.iloc[split:]["y"].values
    mae = float(mean_absolute_error(actual, preds)) if len(actual) else float("nan")

    return TrainedModel("prophet", model, mae, feature_columns=[])


def train_sequence_model(price_df: pd.DataFrame, kind: str) -> TrainedModel | None:
    """LSTM or GRU on the raw price series. Gated behind min_rows_for_deep_learning."""
    if len(price_df) < settings.min_rows_for_deep_learning:
        log.info(
            "Skipping %s - only %d rows of history (need >= %d for a sequence model "
            "to learn signal instead of noise).",
            kind.upper(), len(price_df), settings.min_rows_for_deep_learning,
        )
        return None
    try:
        import tensorflow as tf
        from sklearn.preprocessing import MinMaxScaler
    except ImportError:
        log.warning("tensorflow not installed (`pip install tensorflow`) - skipping %s.", kind.upper())
        return None

    window = 14
    prices = price_df["modal_price"].values.reshape(-1, 1)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(prices)

    X, y = [], []
    for i in range(window, len(scaled)):
        X.append(scaled[i - window:i, 0])
        y.append(scaled[i, 0])
    X, y = np.array(X), np.array(y)
    X = X.reshape((X.shape[0], X.shape[1], 1))

    layer_cls = tf.keras.layers.LSTM if kind == "lstm" else tf.keras.layers.GRU
    model = tf.keras.Sequential([
        layer_cls(32, input_shape=(window, 1)),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(1),
    ])
    model.compile(optimizer="adam", loss="mae")

    split = int(len(X) * 0.85)
    model.fit(X[:split], y[:split], epochs=50, batch_size=8, verbose=0)

    preds_scaled = model.predict(X[split:], verbose=0).flatten()
    preds = scaler.inverse_transform(preds_scaled.reshape(-1, 1)).flatten()
    actual = scaler.inverse_transform(y[split:].reshape(-1, 1)).flatten()
    mae = float(mean_absolute_error(actual, preds)) if len(actual) else float("nan")

    return TrainedModel(kind, {"model": model, "scaler": scaler, "window": window}, mae, feature_columns=[])


def train_all(feature_df: pd.DataFrame, price_df: pd.DataFrame) -> list[TrainedModel]:
    X, y = _make_supervised(feature_df)
    trained: list[TrainedModel] = []

    if len(X) < settings.min_rows_for_tree_models:
        log.warning(
            "Only %d usable rows - below the %d-row minimum for reliable tree-model "
            "training. Predictions will be low-confidence until more history accumulates.",
            len(X), settings.min_rows_for_tree_models,
        )

    for fn in (train_random_forest, train_xgboost, train_lightgbm):
        result = fn(X, y) if fn is train_random_forest else fn(X, y)
        if result is not None:
            trained.append(result)
            log.info("Trained %s | CV MAE = %.1f", result.name, result.cv_mae)

    prophet_result = train_prophet(price_df)
    if prophet_result:
        trained.append(prophet_result)
        log.info("Trained prophet | MAE = %.1f", prophet_result.cv_mae)

    for kind in ("lstm", "gru"):
        seq_result = train_sequence_model(price_df, kind)
        if seq_result:
            trained.append(seq_result)
            log.info("Trained %s | MAE = %.1f", kind, seq_result.cv_mae)

    if not trained:
        raise RuntimeError("No model could be trained - check data volume and installed packages.")

    return trained


def save_models(trained: list[TrainedModel]) -> None:
    manifest = []
    for tm in trained:
        if tm.name in ("lstm", "gru"):
            path = MODEL_DIR / f"{tm.name}.keras"
            tm.estimator["model"].save(path)
            joblib.dump(tm.estimator["scaler"], MODEL_DIR / f"{tm.name}_scaler.joblib")
        elif tm.name == "prophet":
            path = MODEL_DIR / f"{tm.name}.joblib"
            joblib.dump(tm.estimator, path)
        else:
            path = MODEL_DIR / f"{tm.name}.joblib"
            joblib.dump(tm.estimator, path)
        manifest.append({"name": tm.name, "cv_mae": tm.cv_mae, "feature_columns": tm.feature_columns})

    (MODEL_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Saved %d models to %s", len(trained), MODEL_DIR)


def run_training_pipeline(feature_df: pd.DataFrame, price_df: pd.DataFrame) -> list[TrainedModel]:
    trained = train_all(feature_df, price_df)
    save_models(trained)
    return trained

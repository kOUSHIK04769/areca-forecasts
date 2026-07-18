"""
src/models/predict.py
======================
Loads whatever models were saved by train.py and produces:
  - tomorrow's price + confidence
  - a 7-day recursive forecast (each day's prediction feeds the next
    day's features - standard walk-forward approach for short series)
  - the full Buy/Hold/Sell + explanation via src/explain.py

This is the single function the API and Streamlit dashboard both call,
so there is exactly one prediction code path (no duplicated logic).
"""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from config import MODEL_DIR, settings
from src.data import market, weather as weather_mod, news as news_mod
from src.explain import build_recommendation
from src.features.engineering import FEATURE_COLUMNS, build_feature_matrix
from src.logging_setup import get_logger
from src.models.ensemble import ModelPrediction, blend

log = get_logger(__name__)


def load_manifest() -> list[dict]:
    manifest_path = MODEL_DIR / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("No trained models found. Run `python -m automation.retrain` first.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _predict_tree_model(name: str, feature_row: pd.DataFrame) -> float:
    model = joblib.load(MODEL_DIR / f"{name}.joblib")
    X = feature_row[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(0.0)
    return float(model.predict(X)[0])


def _predict_prophet(periods: int = 1) -> list[float]:
    model = joblib.load(MODEL_DIR / "prophet.joblib")
    future = model.make_future_dataframe(periods=periods)
    forecast = model.predict(future)
    return forecast["yhat"].tail(periods).tolist()


def _predict_sequence(name: str, recent_prices: np.ndarray, steps: int = 1) -> list[float]:
    import tensorflow as tf  # local import: only needed if lstm/gru were trained

    model = tf.keras.models.load_model(MODEL_DIR / f"{name}.keras")
    scaler = joblib.load(MODEL_DIR / f"{name}_scaler.joblib")
    window = 14

    series = list(recent_prices[-window:])
    preds = []
    for _ in range(steps):
        scaled = scaler.transform(np.array(series[-window:]).reshape(-1, 1)).reshape(1, window, 1)
        next_scaled = model.predict(scaled, verbose=0)[0][0]
        next_price = float(scaler.inverse_transform([[next_scaled]])[0][0])
        preds.append(next_price)
        series.append(next_price)
    return preds


def _gather_external_signals() -> tuple[dict, dict]:
    weather = weather_mod.fetch_weather()
    news = news_mod.fetch_news_sentiment()
    return weather, news


def _predict_one_day(feature_df: pd.DataFrame, price_series: pd.Series, manifest: list[dict]) -> dict:
    latest_row = feature_df.iloc[[-1]]
    predictions: list[ModelPrediction] = []

    for entry in manifest:
        name, cv_mae = entry["name"], entry["cv_mae"]
        try:
            if name in ("random_forest", "xgboost", "lightgbm"):
                price = _predict_tree_model(name, latest_row)
            elif name == "prophet":
                price = _predict_prophet(periods=1)[0]
            elif name in ("lstm", "gru"):
                price = _predict_sequence(name, price_series.values, steps=1)[0]
            else:
                continue
            predictions.append(ModelPrediction(name=name, predicted_price=price, cv_mae=cv_mae))
        except Exception as exc:  # noqa: BLE001
            log.warning("Prediction failed for model %s: %s", name, exc)

    if not predictions:
        raise RuntimeError("All models failed to predict - check model files under models/.")

    return blend(predictions)


def predict_tomorrow_and_week() -> dict:
    price_df = market.load_history_df()
    weather, news = _gather_external_signals()
    manifest = load_manifest()

    current_price = float(price_df["modal_price"].iloc[-1])
    working_price_df = price_df.copy()

    daily_forecasts = []
    for day_offset in range(1, settings.forecast_horizon_days + 1):
        feature_df = build_feature_matrix(working_price_df, weather=weather, news=news)
        result = _predict_one_day(feature_df, working_price_df["modal_price"], manifest)

        forecast_date = (working_price_df["date"].iloc[-1] + pd.Timedelta(days=1))
        daily_forecasts.append({
            "date": forecast_date.date().isoformat(),
            "predicted_price": result["blended_price"],
            "confidence_pct": result["confidence_pct"],
            "model_predictions": result["model_predictions"],
        })

        # Walk the series forward with the blended prediction so day+2's
        # features (moving averages etc.) reflect day+1's forecast.
        new_row = pd.DataFrame([{
            "date": forecast_date,
            "market": working_price_df["market"].iloc[-1],
            "variety": working_price_df["variety"].iloc[-1],
            "min_price": np.nan,
            "max_price": np.nan,
            "modal_price": result["blended_price"],
            "source": "forecast",
        }])
        working_price_df = pd.concat([working_price_df, new_row], ignore_index=True)

        if day_offset == 1:
            tomorrow = daily_forecasts[0]
            latest_feature_row = feature_df.iloc[-1]

    recommendation = build_recommendation(
        latest_row=latest_feature_row,
        current_price=current_price,
        predicted_tomorrow_price=tomorrow["predicted_price"],
        confidence_pct=tomorrow["confidence_pct"],
        weather=weather,
        news=news,
        single_model=len(tomorrow["model_predictions"]) == 1,
    )

    trend_start, trend_end = current_price, daily_forecasts[-1]["predicted_price"]
    monthly_trend_pct = (trend_end - trend_start) / trend_start * 100 if trend_start else 0.0

    return {
        "current_price": current_price,
        "tomorrow": tomorrow,
        "seven_day_forecast": daily_forecasts,
        "monthly_trend_pct_7d_proxy": round(monthly_trend_pct, 2),
        "market_direction": recommendation.direction,
        "recommendation": recommendation.action,
        "risk_level": recommendation.risk,
        "reasons": recommendation.reasons,
        "weather_used": weather,
        "news_used": news,
        "data_rows_used": len(price_df),
        "models_used": [m["name"] for m in manifest],
    }

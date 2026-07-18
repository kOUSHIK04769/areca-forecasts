"""
src/explain.py
===============
Turns the latest feature row + ensemble output into:
  - a plain-English list of reasons ("why")
  - a market direction (Bullish / Bearish / Sideways)
  - a Buy / Hold / Sell recommendation
  - a Low / Medium / High risk label

This is intentionally RULE-BASED on top of the ML output, not another
black box - so every recommendation traces back to a readable reason,
which is what you asked "explain why" to mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Recommendation:
    direction: str
    action: str
    risk: str
    reasons: list[str] = field(default_factory=list)


def _pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100


def build_recommendation(
    latest_row: pd.Series,
    current_price: float,
    predicted_tomorrow_price: float,
    confidence_pct: float,
    weather: dict | None = None,
    news: dict | None = None,
    single_model: bool = False,
) -> Recommendation:
    reasons: list[str] = []
    weather = weather or {}
    news = news or {}

    if single_model:
        reasons.append(
            "Only one model (RandomForest) is currently active - install xgboost/lightgbm "
            "and accumulate more history for Prophet/LSTM/GRU to join the ensemble and "
            "sharpen this confidence figure."
        )

    expected_move_pct = _pct_change(predicted_tomorrow_price, current_price)

    # --- Trend signals ---
    ma3, ma7 = latest_row.get("ma_3"), latest_row.get("ma_7")
    if pd.notna(ma3) and pd.notna(ma7):
        if ma3 > ma7:
            reasons.append(f"Short-term average (₹{ma3:,.0f}) is above the 7-day average (₹{ma7:,.0f}) - bullish crossover.")
        elif ma3 < ma7:
            reasons.append(f"Short-term average (₹{ma3:,.0f}) is below the 7-day average (₹{ma7:,.0f}) - bearish crossover.")

    rsi = latest_row.get("rsi_14")
    if pd.notna(rsi):
        if rsi >= 70:
            reasons.append(f"RSI at {rsi:.0f} indicates overbought conditions - pullback risk.")
        elif rsi <= 30:
            reasons.append(f"RSI at {rsi:.0f} indicates oversold conditions - rebound potential.")

    macd_hist = latest_row.get("macd_hist")
    if pd.notna(macd_hist):
        if macd_hist > 0:
            reasons.append("MACD histogram positive - upward momentum building.")
        elif macd_hist < 0:
            reasons.append("MACD histogram negative - downward momentum building.")

    # --- Supply/demand ---
    if latest_row.get("is_festival_window"):
        name = latest_row.get("festival_name")
        reasons.append(f"Within pre-festival demand window{f' ({name})' if name else ''} - demand typically firms up.")

    rainfall = weather.get("rainfall_mm")
    if weather.get("is_live") and rainfall is not None:
        if rainfall > 10:
            reasons.append(f"{rainfall:.0f}mm rainfall forecast - may disrupt drying/arrivals, tightening near-term supply.")
        elif rainfall == 0:
            reasons.append("Dry weather forecast - normal harvesting/drying conditions expected.")

    sentiment = news.get("sentiment_score", 0.0)
    if news.get("is_live") and abs(sentiment) > 0.15:
        if sentiment > 0:
            reasons.append(f"News sentiment positive ({sentiment:+.2f}) - export/demand headlines skew favorable.")
        else:
            reasons.append(f"News sentiment negative ({sentiment:+.2f}) - policy/oversupply headlines skew unfavorable.")

    if not weather.get("is_live"):
        reasons.append("Live weather data unavailable (no API key configured) - weather not factored into this call.")
    if not news.get("is_live"):
        reasons.append("Live news data unavailable - sentiment not factored into this call.")

    # --- Direction ---
    if expected_move_pct > 0.5:
        direction = "Bullish"
    elif expected_move_pct < -0.5:
        direction = "Bearish"
    else:
        direction = "Sideways"

    # --- Action ---
    if direction == "Bullish" and confidence_pct >= 65:
        action = "BUY"
    elif direction == "Bearish" and confidence_pct >= 65:
        action = "SELL"
    else:
        action = "HOLD"

    # --- Risk ---
    volatility_7 = latest_row.get("volatility_7")
    vol_pct = (volatility_7 / current_price * 100) if pd.notna(volatility_7) and current_price else 0
    if confidence_pct >= 75 and vol_pct < 2:
        risk = "LOW"
    elif confidence_pct >= 55 and vol_pct < 5:
        risk = "MEDIUM"
    else:
        risk = "HIGH"

    reasons.insert(0, f"Model expects a {expected_move_pct:+.2f}% move to ₹{predicted_tomorrow_price:,.0f} (confidence {confidence_pct:.0f}%).")

    return Recommendation(direction=direction, action=action, risk=risk, reasons=reasons)

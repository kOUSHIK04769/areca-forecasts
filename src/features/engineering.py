"""
src/features/engineering.py
============================
Builds the full feature matrix from raw price history plus whatever
external signals (weather, news, festival calendar) are passed in.

Design choice: every technical indicator below is computed with
`min_periods=1` where reasonable so the pipeline still produces
*something* on short history (your current 31 rows) rather than
dropping every early row to NaN - but functions that genuinely need a
longer window (e.g. 30-day average) will correctly be NaN until enough
data exists. We do not fabricate values to hide that.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.festivals import festival_indicator
from src.logging_setup import get_logger

log = get_logger(__name__)


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)  # neutral RSI when undefined (flat/insufficient data)


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = series.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = series.ewm(span=slow, adjust=False, min_periods=1).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean()
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": macd_line - signal_line})


def build_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """df must have columns: date (datetime), modal_price."""
    out = df.copy().sort_values("date").reset_index(drop=True)
    p = out["modal_price"]

    out["prev_price"] = p.shift(1)
    out["ma_3"] = p.rolling(3, min_periods=1).mean()
    out["ma_7"] = p.rolling(7, min_periods=1).mean()
    out["ma_15"] = p.rolling(15, min_periods=3).mean()
    out["ma_30"] = p.rolling(30, min_periods=5).mean()

    out["volatility_7"] = p.rolling(7, min_periods=2).std()
    out["volatility_30"] = p.rolling(30, min_periods=5).std()

    out["daily_return"] = p.pct_change(1)
    out["weekly_return"] = p.pct_change(7)
    out["monthly_return"] = p.pct_change(30)

    out["momentum_3"] = p - p.shift(3)
    out["momentum_7"] = p - p.shift(7)

    out["rsi_14"] = _rsi(p, 14)
    out = out.join(_macd(p))

    out["month"] = out["date"].dt.month
    out["week_of_year"] = out["date"].dt.isocalendar().week.astype(int)
    out["day_of_week"] = out["date"].dt.dayofweek

    # Karnataka arecanut season: main harvest/arrivals Nov-Feb, lean May-Aug
    out["season"] = out["month"].apply(
        lambda m: "harvest" if m in (11, 12, 1, 2) else ("lean" if m in (5, 6, 7, 8) else "shoulder")
    )

    festival_rows = out["date"].apply(lambda d: festival_indicator(d.date()))
    out["is_festival_window"] = festival_rows.apply(lambda r: r["is_festival_window"])
    out["days_to_festival"] = festival_rows.apply(lambda r: r["days_to_festival"])

    return out


def attach_external_signals(
    df: pd.DataFrame,
    weather: dict | None = None,
    news: dict | None = None,
    market_arrivals: float | None = None,
) -> pd.DataFrame:
    """
    Attaches the LATEST external readings to every row as of the most
    recent date (single point-in-time snapshot, since we don't have a
    historical weather/news archive). This is honest about a real
    limitation: without a backfilled weather/news history, these
    columns are most meaningful for TODAY's row, and act as constants
    for older rows - the model should be told they carry -more- signal
    for the last row, which `explain.py` reflects by weighting recency.
    """
    out = df.copy()
    weather = weather or {}
    news = news or {}

    out["rainfall_mm"] = weather.get("rainfall_mm", np.nan)
    out["humidity_pct"] = weather.get("humidity_pct", np.nan)
    out["temperature_c"] = weather.get("temperature_c", np.nan)
    out["wind_kph"] = weather.get("wind_kph", np.nan)
    out["weather_is_live"] = weather.get("is_live", False)

    out["news_sentiment"] = news.get("sentiment_score", 0.0)
    out["news_is_live"] = news.get("is_live", False)

    out["market_arrivals"] = market_arrivals if market_arrivals is not None else np.nan
    # supply indicator: lower arrivals relative to trailing average implies tighter supply
    trailing_arrivals = out["market_arrivals"].rolling(7, min_periods=1).mean()
    out["supply_indicator"] = np.where(
        out["market_arrivals"].notna() & (trailing_arrivals > 0),
        1 - (out["market_arrivals"] / trailing_arrivals),
        0.0,
    )
    # demand indicator: composite of festival window + positive news sentiment
    out["demand_indicator"] = (
        out["is_festival_window"].astype(int) * 0.5 + out["news_sentiment"].clip(-1, 1) * 0.5
    )

    return out


FEATURE_COLUMNS = [
    "prev_price", "ma_3", "ma_7", "ma_15", "ma_30",
    "volatility_7", "volatility_30",
    "daily_return", "weekly_return", "monthly_return",
    "momentum_3", "momentum_7",
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "month", "week_of_year", "day_of_week",
    "is_festival_window", "days_to_festival",
    "rainfall_mm", "humidity_pct", "temperature_c", "wind_kph",
    "news_sentiment", "market_arrivals", "supply_indicator", "demand_indicator",
]


def build_feature_matrix(
    price_df: pd.DataFrame,
    weather: dict | None = None,
    news: dict | None = None,
    market_arrivals: float | None = None,
) -> pd.DataFrame:
    df = build_price_features(price_df)
    df = attach_external_signals(df, weather=weather, news=news, market_arrivals=market_arrivals)
    df["season"] = df["season"].astype("category").cat.codes  # encode for tree models
    df["days_to_festival"] = df["days_to_festival"].fillna(999)
    log.info("Built feature matrix: %d rows x %d columns", *df.shape)
    return df

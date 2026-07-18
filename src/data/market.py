"""
src/data/market.py
===================
Thin wrapper around the ORIGINAL Shivamogga tracker
(`src/data/legacy_tracker.py`, your uploaded script, untouched).

We do not re-implement Agmarknet/MAMCOS scraping here — that logic
already exists and works. This module just:
  1. Calls your existing `get_today_price()` fetcher.
  2. Appends the reading to the shared history CSV (via pandas so the
     rest of the pipeline gets typed dataframes instead of raw dicts).
  3. Exposes `load_history_df()` for the feature engineering /
     modelling layers.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from config import HISTORY_CSV
from src.data import legacy_tracker as legacy
from src.logging_setup import get_logger

log = get_logger(__name__)


def fetch_today_reading() -> dict | None:
    """Delegates to the existing tracker's Agmarknet -> MAMCOS fallback chain."""
    reading = legacy.get_today_price()
    if reading is None:
        log.warning("No reading available from Agmarknet or MAMCOS today.")
    return reading


def load_history_df() -> pd.DataFrame:
    """Loads the shared price-history CSV as a clean, sorted dataframe."""
    if not HISTORY_CSV.exists():
        raise FileNotFoundError(
            f"{HISTORY_CSV} not found. Run the tracker at least once to seed history."
        )
    df = pd.read_csv(HISTORY_CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "modal_price"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df = df.reset_index(drop=True)
    return df


def append_reading(reading: dict) -> None:
    """Appends a new reading to history, replacing any existing row for today."""
    df = load_history_df() if HISTORY_CSV.exists() else pd.DataFrame(
        columns=["date", "market", "variety", "min_price", "max_price", "modal_price", "source"]
    )
    today = pd.Timestamp(reading["date"])
    df = df[df["date"] != today]
    new_row = pd.DataFrame([{**reading, "date": today}])
    df = pd.concat([df, new_row], ignore_index=True).sort_values("date")
    df.to_csv(HISTORY_CSV, index=False)
    log.info("Appended reading for %s: modal=%.0f", reading["date"], reading["modal_price"])


def run_daily_fetch() -> dict | None:
    """Full daily fetch-and-append cycle. Returns the reading, or None on failure."""
    reading = fetch_today_reading()
    if reading is None:
        return None
    reading.setdefault("date", date.today().isoformat())
    append_reading(reading)
    return reading

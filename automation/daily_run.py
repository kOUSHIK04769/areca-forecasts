"""
automation/daily_run.py
========================
The single script your scheduler (cron / Task Scheduler / Docker
healthcheck loop) calls once a day. It:

  1. Fetches today's price (your existing Agmarknet/MAMCOS tracker).
  2. Retrains all models on the updated history.
  3. Generates tomorrow + 7-day predictions.
  4. Sends a Telegram alert (if configured).
  5. Writes a JSON snapshot the API/dashboard read from, so the
     dashboard doesn't have to re-run inference on every page load.

Cron example (Linux/Mac), runs daily at 7:00 AM IST:
    0 7 * * * cd /path/to/areca-forecast && /path/to/venv/bin/python -m automation.daily_run

Windows: use Task Scheduler to run the same command daily.
"""

from __future__ import annotations

import json
from datetime import datetime

from config import REPORT_DIR
from src.data import market
from src.features.engineering import build_feature_matrix
from src.logging_setup import get_logger
from src.models.predict import predict_tomorrow_and_week
from src.models.train import run_training_pipeline
from src.notify.telegram import send_telegram_alert

log = get_logger("daily_run")


def main() -> None:
    log.info("=== Daily run starting: %s ===", datetime.now().isoformat())

    reading = market.run_daily_fetch()
    if reading is None:
        log.error("Could not fetch today's price from any source - aborting daily run.")
        return
    log.info("Fetched: %s modal=₹%.0f", reading["date"], reading["modal_price"])

    price_df = market.load_history_df()
    feature_df = build_feature_matrix(price_df)

    try:
        run_training_pipeline(feature_df, price_df)
    except RuntimeError as exc:
        log.error("Training failed: %s", exc)
        return

    prediction = predict_tomorrow_and_week()

    snapshot_path = REPORT_DIR / "latest_prediction.json"
    snapshot_path.write_text(json.dumps(prediction, indent=2, default=str), encoding="utf-8")
    log.info("Wrote prediction snapshot to %s", snapshot_path)

    send_telegram_alert(prediction)

    log.info(
        "=== Daily run complete: tomorrow=₹%.0f (%s, %.0f%% confidence) -> %s ===",
        prediction["tomorrow"]["predicted_price"],
        prediction["market_direction"],
        prediction["tomorrow"]["confidence_pct"],
        prediction["recommendation"],
    )


if __name__ == "__main__":
    main()

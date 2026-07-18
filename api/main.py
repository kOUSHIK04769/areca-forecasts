"""
api/main.py
===========
FastAPI server exposing the forecast to any device (phone, laptop,
another app) on your network or the internet.

Run locally:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

Then from your phone (same Wi-Fi): http://<your-pc-lan-ip>:8000/prediction
From anywhere: deploy this container (see Dockerfile) to a host with a
public IP/domain, or tunnel it locally with `ngrok http 8000` for quick
testing without deploying anywhere.

All write/refresh endpoints require the `X-API-Key` header, matching
APP_API_KEY in your .env - read-only prediction/history endpoints are
open by default (change `require_key=True` on them if you want the
whole API private).
"""

from __future__ import annotations

import json

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from config import REPORT_DIR, settings
from src.data import market
from src.models.predict import predict_tomorrow_and_week
from src.notify.telegram import send_telegram_alert

app = FastAPI(
    title="Shivamogga Arecanut Forecast API",
    description="AI-powered price prediction and Buy/Hold/Sell signals for Shivamogga arecanut.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your dashboard's origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/prediction")
def get_prediction(live: bool = False) -> dict:
    """
    By default returns the last snapshot written by the daily automation
    run (fast, no recompute). Pass ?live=true to force a fresh inference
    call (slower - fetches weather/news and re-runs all models).
    """
    if live:
        try:
            return predict_tomorrow_and_week()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    snapshot_path = REPORT_DIR / "latest_prediction.json"
    if not snapshot_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No prediction snapshot yet - run `python -m automation.daily_run` first, "
                   "or call /prediction?live=true.",
        )
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


@app.get("/history")
def get_history(days: int = 30) -> dict:
    df = market.load_history_df().tail(days)
    return {"rows": json.loads(df.to_json(orient="records", date_format="iso"))}


@app.post("/refresh", dependencies=[Depends(require_api_key)])
def refresh() -> dict:
    """Manually trigger fetch + predict (protected - requires X-API-Key)."""
    reading = market.run_daily_fetch()
    if reading is None:
        raise HTTPException(status_code=502, detail="Could not fetch today's price from any source.")
    prediction = predict_tomorrow_and_week()
    (REPORT_DIR / "latest_prediction.json").write_text(
        json.dumps(prediction, indent=2, default=str), encoding="utf-8"
    )
    return prediction


@app.post("/notify/telegram", dependencies=[Depends(require_api_key)])
def notify_telegram() -> dict:
    prediction = get_prediction(live=False)
    sent = send_telegram_alert(prediction)
    return {"sent": sent}

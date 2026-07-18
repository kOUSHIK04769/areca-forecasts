"""
src/data/weather.py
====================
Fetches current + short-range forecast weather for Shivamogga from
OpenWeatherMap (free tier). Rainfall/humidity feed the feature
engineering layer (rain -> lower arrivals -> price pressure).

IMPORTANT: without OPENWEATHER_API_KEY set in .env, this returns
`is_live=False` with neutral placeholder values rather than fabricating
numbers. Every caller must check `is_live` before trusting the figures.
"""

from __future__ import annotations

import json
from datetime import date

import requests

from config import WEATHER_CACHE, settings
from src.logging_setup import get_logger

log = get_logger(__name__)

NEUTRAL_READING = {
    "date": date.today().isoformat(),
    "rainfall_mm": 0.0,
    "humidity_pct": 70.0,
    "temperature_c": 27.0,
    "wind_kph": 10.0,
    "is_live": False,
}


def fetch_weather() -> dict:
    if not settings.openweather_api_key:
        log.info("OPENWEATHER_API_KEY not set - returning neutral weather placeholder.")
        return dict(NEUTRAL_READING)

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": settings.shivamogga_lat,
        "lon": settings.shivamogga_lon,
        "appid": settings.openweather_api_key,
        "units": "metric",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        reading = {
            "date": date.today().isoformat(),
            "rainfall_mm": payload.get("rain", {}).get("1h", 0.0),
            "humidity_pct": payload.get("main", {}).get("humidity", 70.0),
            "temperature_c": payload.get("main", {}).get("temp", 27.0),
            "wind_kph": payload.get("wind", {}).get("speed", 0.0) * 3.6,
            "is_live": True,
        }
        WEATHER_CACHE.write_text(json.dumps(reading), encoding="utf-8")
        return reading
    except Exception as exc:  # noqa: BLE001
        log.warning("Weather fetch failed (%s) - falling back to cache/neutral.", exc)
        if WEATHER_CACHE.exists():
            cached = json.loads(WEATHER_CACHE.read_text(encoding="utf-8"))
            cached["is_live"] = False
            return cached
        return dict(NEUTRAL_READING)

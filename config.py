"""
config.py
=========
Single source of truth for paths, thresholds and API credentials.
Values come from environment variables (see .env.example) so no secret
ever needs to be hard-coded or committed to git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is optional in production (env vars may be injected
    # directly by Docker / systemd), but recommended for local dev.
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"

for _dir in (DATA_DIR, MODEL_DIR, LOG_DIR, REPORT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

HISTORY_CSV = DATA_DIR / "areca_price_history.csv"
FEATURES_CSV = DATA_DIR / "areca_features.csv"
NEWS_CACHE = DATA_DIR / "news_cache.json"
WEATHER_CACHE = DATA_DIR / "weather_cache.json"


@dataclass(frozen=True)
class Settings:
    # --- Market identity (unchanged from the original tracker) ---
    state: str = "Karnataka"
    district: str = "Shivamogga"
    commodity: str = "Arecanut"

    # --- Model behaviour ---
    # Below this many rows of history, LSTM/GRU/Prophet are skipped
    # (they need real sequence length to learn anything meaningful)
    # and only tree-based + statistical models are used.
    min_rows_for_deep_learning: int = 180
    min_rows_for_prophet: int = 60
    min_rows_for_tree_models: int = 20
    forecast_horizon_days: int = 7
    cv_splits: int = 5  # for TimeSeriesSplit; auto-reduced if data is short

    # --- Weather API (OpenWeatherMap) ---
    openweather_api_key: str = field(default_factory=lambda: os.environ.get("OPENWEATHER_API_KEY", ""))
    shivamogga_lat: float = 13.9299
    shivamogga_lon: float = 75.5681

    # --- News API ---
    newsapi_key: str = field(default_factory=lambda: os.environ.get("NEWSAPI_KEY", ""))
    google_news_rss: str = (
        "https://news.google.com/rss/search?q=arecanut+OR+adike+price+Karnataka&hl=en-IN&gl=IN&ceid=IN:en"
    )

    # --- data.gov.in / Agmarknet ---
    data_gov_in_api_key: str = field(default_factory=lambda: os.environ.get("DATA_GOV_IN_API_KEY", ""))

    # --- Notifications ---
    telegram_bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    smtp_host: str = field(default_factory=lambda: os.environ.get("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.environ.get("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD", ""))
    alert_email_to: str = field(default_factory=lambda: os.environ.get("ALERT_EMAIL_TO", ""))
    discord_webhook_url: str = field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_URL", ""))

    # --- API server (for phone/other-device access) ---
    api_host: str = field(default_factory=lambda: os.environ.get("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.environ.get("API_PORT", "8000")))
    api_key: str = field(default_factory=lambda: os.environ.get("APP_API_KEY", "change-me"))


settings = Settings()

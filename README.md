# Shivamogga Arecanut AI Forecasting Platform

Built on top of your existing Agmarknet/MAMCOS tracker (`src/data/legacy_tracker.py`
is your original script, unmodified) — this adds feature engineering, an
ML ensemble, explainable Buy/Hold/Sell calls, a REST API, and a Streamlit
dashboard.

## What actually works today vs. what needs setup

| Capability | Status |
|---|---|
| Price fetch (Agmarknet → MAMCOS fallback) | ✅ Working — your original logic |
| Feature engineering (MAs, RSI, MACD, returns, season, festivals) | ✅ Working |
| RandomForest model | ✅ Working now |
| XGBoost / LightGBM | ⚙️ Works once you `pip install xgboost lightgbm` |
| Prophet | ⚙️ Activates automatically once you have **60+ days** of history |
| LSTM / GRU | ⚙️ Activates automatically once you have **180+ days** of history |
| Weather features | ⚙️ Needs `OPENWEATHER_API_KEY` — neutral placeholder otherwise |
| News sentiment | ⚙️ Needs `NEWSAPI_KEY`, or free Google News RSS via `pip install feedparser` |
| Festival calendar | ✅ Working (static list in `src/data/festivals.py`, edit yearly) |
| Telegram alerts | ⚙️ Needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| WhatsApp / Discord / Email alerts | 🚧 Not yet built — same pattern as Telegram, tell me which you want and I'll add them |
| REST API (phone/any-device access) | ✅ Working — FastAPI in `api/main.py` |
| Streamlit dashboard | ✅ Working — 8 pages, dark mode, candlesticks, CSV export |
| PDF report export | 🚧 `reportlab` is in requirements.txt but the report generator itself isn't written yet — say the word and I'll add it |
| Docker | ✅ Dockerfile included (API + daily cron in one container) |

**Why this matters:** you currently have 31 days of price history. XGBoost/
LightGBM/RandomForest can learn something useful from that. Prophet and
LSTM/GRU genuinely cannot — they need much longer sequences or they just
memorize noise and give you false confidence. The code is fully written and
will switch itself on automatically as your `areca_price_history.csv` grows
past the thresholds in `config.py` (`min_rows_for_prophet`,
`min_rows_for_deep_learning`). I did not want to ship you a dashboard that
*looks* like it has 6 models running when 3 of them would be fitting to 31
points of noise.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in whichever API keys you have
```

## Run it

```bash
# 1. One-time (or daily via cron/Task Scheduler): fetch + train + predict + alert
python -m automation.daily_run

# 2. Dashboard (accessible on your Wi-Fi from any device)
streamlit run dashboard/app.py --server.address 0.0.0.0
# -> open http://<this-pc's-LAN-IP>:8501 from your phone (same Wi-Fi)

# 3. REST API (so any app/device can pull predictions)
uvicorn api.main:app --host 0.0.0.0 --port 8000
# -> GET  http://<this-pc's-LAN-IP>:8000/prediction
# -> GET  http://<this-pc's-LAN-IP>:8000/history?days=30
# -> POST http://<this-pc's-LAN-IP>:8000/refresh   (needs X-API-Key header)
```

### Accessing from outside your home Wi-Fi
Running on a LAN IP only reaches devices on the same network. For access
from anywhere:
- Quick test: `ngrok http 8000` (tunnels the API publicly for testing).
- Real deployment: run `docker build -t areca-forecast . && docker run -p 8000:8000 --env-file .env areca-forecast` on a small cloud VM (e.g. a ₹400/mo box on DigitalOcean/AWS Lightsail) with a domain pointed at it.

## Daily automation
`automation/daily_run.py` is the one script your scheduler calls. It fetches
today's price, retrains all available models, writes
`reports/latest_prediction.json` (what the API/dashboard read from), and
sends a Telegram alert if configured.

```cron
# crontab -e — runs every day at 7:00 AM
0 7 * * * cd /path/to/areca-forecast && /path/to/venv/bin/python -m automation.daily_run
```

## Project structure
```
areca-forecast/
├── config.py                  # all paths/thresholds/keys, reads .env
├── src/
│   ├── data/
│   │   ├── legacy_tracker.py  # YOUR original script, untouched
│   │   ├── market.py          # wraps it, adds pandas history I/O
│   │   ├── weather.py         # OpenWeatherMap + honest fallback
│   │   ├── news.py            # NewsAPI / Google News RSS + sentiment
│   │   └── festivals.py       # Karnataka festival calendar
│   ├── features/engineering.py   # all technical indicators + external signals
│   ├── models/
│   │   ├── train.py           # trains the whole model zoo, data-gated
│   │   ├── ensemble.py        # inverse-error-weighted blending
│   │   └── predict.py         # single prediction code path (API + dashboard both call this)
│   ├── explain.py              # rule-based Buy/Hold/Sell + reasons
│   └── notify/telegram.py
├── api/main.py                 # FastAPI server
├── dashboard/app.py             # Streamlit, 8 pages
├── automation/daily_run.py      # the cron entrypoint
├── tests/test_features.py
├── models/                      # saved model artifacts (git-ignore this)
├── data/areca_price_history.csv # your existing history, kept as-is
├── requirements.txt / Dockerfile / .env.example
```

## Tested in this environment
`tests/test_features.py` passes. The training + prediction pipeline was run
end-to-end against your real 31-row `areca_price_history.csv` (RandomForest
only, since xgboost/lightgbm/tensorflow aren't in this sandbox) — it
produces a tomorrow price, 7-day forecast, and an honest 70%-capped
confidence with a reason explicitly stating only one model is active.
Install the full `requirements.txt` on your machine to unlock XGBoost/LightGBM
immediately, and Prophet/LSTM/GRU as your history grows.

## Next modules (tell me which to build next)
1. WhatsApp (Twilio), Discord, and Email notification channels
2. PDF report generator (reportlab)
3. Hyperparameter tuning expansion (Optuna) once XGBoost/LightGBM are installed
4. A `/mnt`-style scheduled backfill script to pull historical Agmarknet data further back so Prophet/LSTM activate sooner

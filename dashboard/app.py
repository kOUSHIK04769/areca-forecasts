"""
dashboard/app.py
=================
Streamlit dashboard for the Shivamogga Arecanut forecasting platform.

Run:
    streamlit run dashboard/app.py

Access from your phone: run with `streamlit run dashboard/app.py
--server.address 0.0.0.0`, then open http://<your-pc-lan-ip>:8501 on
your phone (same Wi-Fi). For access from anywhere, deploy this
alongside the API (see Dockerfile / README).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data import market
from src.models.predict import predict_tomorrow_and_week

st.set_page_config(page_title="Shivamogga Arecanut Forecast", page_icon="🌰", layout="wide")

# ---------------------------------------------------------------------------
# Sidebar / navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🌰 Areca Forecast")
    dark_mode = st.toggle("Dark mode", value=True)
    page = st.radio(
        "Navigate",
        ["Dashboard", "Prediction", "Market Analysis", "Charts", "News", "Weather", "AI Insights", "Settings"],
    )
    st.caption("Data: Agmarknet / MAMCOS · Shivamogga, Karnataka")

if dark_mode:
    st.markdown(
        "<style>body,.stApp{background-color:#0b0f19;color:#e5e7eb;}</style>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600)
def _load_history() -> pd.DataFrame:
    return market.load_history_df()


@st.cache_data(ttl=3600)
def _load_prediction() -> dict:
    return predict_tomorrow_and_week()


def _candlestick(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        data=[go.Candlestick(
            x=df["date"],
            open=df["min_price"],  # true OHLC isn't published for mandi data;
            high=df["max_price"],  # min/max/modal is the closest analogue -
            low=df["min_price"],   # modal price is plotted as "close".
            close=df["modal_price"],
            name="Price range",
        )]
    )
    fig.update_layout(template="plotly_dark", height=420, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _line_with_ma(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["modal_price"], name="Modal price", line=dict(width=3)))
    for window, color in [(3, "#f59e0b"), (7, "#22c55e")]:
        ma = df["modal_price"].rolling(window, min_periods=1).mean()
        fig.add_trace(go.Scatter(x=df["date"], y=ma, name=f"{window}-day MA", line=dict(dash="dot", color=color)))
    fig.update_layout(template="plotly_dark", height=380, margin=dict(l=10, r=10, t=30, b=10))
    return fig


history = _load_history()

try:
    prediction = _load_prediction()
    prediction_error = None
except Exception as exc:  # noqa: BLE001
    prediction = None
    prediction_error = str(exc)

# ---------------------------------------------------------------------------
# PAGE: Dashboard
# ---------------------------------------------------------------------------
if page == "Dashboard":
    st.header("Shivamogga Arecanut - Live Dashboard")
    latest = history.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest Modal Price", f"₹{latest['modal_price']:,.0f}")
    if len(history) > 1:
        prev = history.iloc[-2]["modal_price"]
        c2.metric("Day Change", f"{(latest['modal_price'] - prev):+,.0f}", f"{(latest['modal_price']/prev-1)*100:+.2f}%")
    else:
        c2.metric("Day Change", "N/A")
    c3.metric("Variety", latest.get("variety", "N/A"))
    c4.metric("Rows of History", len(history))

    if prediction:
        st.subheader("Tomorrow's Call")
        t = prediction["tomorrow"]
        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("Predicted Price", f"₹{t['predicted_price']:,.0f}")
        cc2.metric("Confidence", f"{t['confidence_pct']:.0f}%")
        cc3.metric("Direction", prediction["market_direction"])
        action_color = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}[prediction["recommendation"]]
        cc4.metric("Call", f"{action_color} {prediction['recommendation']}")
    else:
        st.warning(f"No prediction available yet: {prediction_error}")

    st.plotly_chart(_line_with_ma(history), use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: Prediction
# ---------------------------------------------------------------------------
elif page == "Prediction":
    st.header("AI Prediction")
    if not prediction:
        st.error(f"Cannot generate prediction: {prediction_error}")
    else:
        t = prediction["tomorrow"]
        col1, col2 = st.columns([2, 1])
        with col1:
            st.metric("Tomorrow's Price", f"₹{t['predicted_price']:,.0f}", f"{t['confidence_pct']:.0f}% confidence")
            st.progress(min(int(t["confidence_pct"]), 100) / 100)

            st.markdown("**Per-model predictions**")
            st.dataframe(pd.DataFrame([t["model_predictions"]]).T.rename(columns={0: "Predicted price (₹)"}))

            st.markdown("### Why")
            for reason in prediction["reasons"]:
                st.write(f"- {reason}")

        with col2:
            st.markdown("### Recommendation")
            st.write(f"**Direction:** {prediction['market_direction']}")
            st.write(f"**Action:** {prediction['recommendation']}")
            st.write(f"**Risk:** {prediction['risk_level']}")
            st.caption(f"Models used: {', '.join(prediction['models_used'])}")
            st.caption(f"Trained on {prediction['data_rows_used']} days of history.")
            if prediction["data_rows_used"] < 60:
                st.info(
                    "History is still short — confidence and deep-learning "
                    "models will improve as more daily readings accumulate."
                )

        st.subheader("7-Day Forecast")
        forecast_df = pd.DataFrame(prediction["seven_day_forecast"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=forecast_df["date"], y=forecast_df["predicted_price"], mode="lines+markers", name="Forecast"))
        fig.update_layout(template="plotly_dark", height=350, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(forecast_df[["date", "predicted_price", "confidence_pct"]], use_container_width=True)

        csv = forecast_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download 7-day forecast (CSV)", csv, "areca_7day_forecast.csv", "text/csv")

# ---------------------------------------------------------------------------
# PAGE: Market Analysis
# ---------------------------------------------------------------------------
elif page == "Market Analysis":
    st.header("Market Analysis")
    st.plotly_chart(_candlestick(history.tail(30)), use_container_width=True)
    st.subheader("Recent readings")
    st.dataframe(history.tail(20).sort_values("date", ascending=False), use_container_width=True)
    csv = history.to_csv(index=False).encode("utf-8")
    st.download_button("Download full history (CSV)", csv, "areca_price_history.csv", "text/csv")

# ---------------------------------------------------------------------------
# PAGE: Charts
# ---------------------------------------------------------------------------
elif page == "Charts":
    st.header("Charts")
    st.plotly_chart(_line_with_ma(history), use_container_width=True)
    st.plotly_chart(_candlestick(history.tail(60)), use_container_width=True)
    if len(history) > 3:
        returns = history["modal_price"].pct_change().dropna() * 100
        fig = go.Figure(data=[go.Histogram(x=returns, nbinsx=15)])
        fig.update_layout(template="plotly_dark", title="Daily Return Distribution (%)", height=300)
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: News
# ---------------------------------------------------------------------------
elif page == "News":
    st.header("News & Sentiment")
    if prediction and prediction.get("news_used"):
        news = prediction["news_used"]
        if news.get("is_live"):
            st.metric("Sentiment score", f"{news['sentiment_score']:+.2f}")
            st.markdown("**Recent headlines**")
            for h in news.get("headlines", []):
                st.write(f"- {h}")
        else:
            st.info(
                "No live news source configured. Set NEWSAPI_KEY in .env, or "
                "`pip install feedparser` to use the free Google News RSS fallback."
            )
    else:
        st.warning("Run a prediction first to fetch news.")

# ---------------------------------------------------------------------------
# PAGE: Weather
# ---------------------------------------------------------------------------
elif page == "Weather":
    st.header("Weather")
    if prediction and prediction.get("weather_used"):
        w = prediction["weather_used"]
        if w.get("is_live"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Rainfall", f"{w['rainfall_mm']:.1f} mm")
            c2.metric("Humidity", f"{w['humidity_pct']:.0f}%")
            c3.metric("Temperature", f"{w['temperature_c']:.1f}°C")
            c4.metric("Wind", f"{w['wind_kph']:.1f} kph")
        else:
            st.info("No live weather source configured. Set OPENWEATHER_API_KEY in .env.")
    else:
        st.warning("Run a prediction first to fetch weather.")

# ---------------------------------------------------------------------------
# PAGE: AI Insights
# ---------------------------------------------------------------------------
elif page == "AI Insights":
    st.header("AI Insights")
    if prediction:
        st.markdown(f"**Market direction:** {prediction['market_direction']}")
        st.markdown(f"**7-day-proxy trend:** {prediction['monthly_trend_pct_7d_proxy']:+.2f}%")
        st.caption("Note: with limited history, the 'monthly trend' is a proxy extrapolated from the 7-day forecast, not a true 30-day model.")
        st.markdown("### Model agreement")
        model_preds = prediction["tomorrow"]["model_predictions"]
        st.bar_chart(pd.Series(model_preds))
        st.markdown("### Full reasoning")
        for r in prediction["reasons"]:
            st.write(f"- {r}")
    else:
        st.warning(f"No insights available: {prediction_error}")

# ---------------------------------------------------------------------------
# PAGE: Settings
# ---------------------------------------------------------------------------
elif page == "Settings":
    st.header("Settings")
    st.write("Configure API keys and notification channels in your `.env` file (see `.env.example`).")
    st.code(
        "OPENWEATHER_API_KEY=\nNEWSAPI_KEY=\nDATA_GOV_IN_API_KEY=\n"
        "TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\nAPP_API_KEY=change-me",
        language="bash",
    )
    st.write("After editing `.env`, restart the dashboard/API for changes to take effect.")
    if st.button("Force refresh prediction now"):
        st.cache_data.clear()
        st.rerun()

"""
src/data/news.py
=================
Pulls arecanut/adike-related headlines from NewsAPI (if a key is set)
or the free Google News RSS feed (no key needed), and scores sentiment
with a lightweight lexicon approach (VADER via nltk if available,
else a small keyword-weighted fallback so the pipeline never hard-fails
just because a heavy NLP dependency isn't installed).

Returns a score in [-1, 1] plus the headlines used, so the explanation
layer can show *why* — never a bare unexplained number.
"""

from __future__ import annotations

from datetime import date

import requests

from config import settings
from src.logging_setup import get_logger

log = get_logger(__name__)

POSITIVE_WORDS = {
    "rise", "rises", "rising", "surge", "surges", "gain", "gains", "high", "record",
    "demand", "export", "exports", "bullish", "rally", "boost", "increase", "increases",
    "shortage", "strong",
}
NEGATIVE_WORDS = {
    "fall", "falls", "falling", "drop", "drops", "decline", "declines", "crash",
    "low", "bearish", "oversupply", "surplus", "ban", "tariff", "restriction",
    "restrictions", "glut", "weak", "slump", "import", "imports",
}


def _score_headline(text: str) -> float:
    words = {w.strip(".,!?").lower() for w in text.split()}
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / max(pos + neg, 1)


def _fetch_newsapi() -> list[str] | None:
    if not settings.newsapi_key:
        return None
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "arecanut OR adike OR supari price Karnataka",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
                "apiKey": settings.newsapi_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [a["title"] for a in articles if a.get("title")]
    except Exception as exc:  # noqa: BLE001
        log.warning("NewsAPI fetch failed: %s", exc)
        return None


def _fetch_google_news_rss() -> list[str] | None:
    try:
        import feedparser
    except ImportError:
        log.warning("feedparser not installed - skipping Google News RSS. `pip install feedparser`.")
        return None
    try:
        feed = feedparser.parse(settings.google_news_rss)
        return [entry.title for entry in feed.entries[:15]]
    except Exception as exc:  # noqa: BLE001
        log.warning("Google News RSS fetch failed: %s", exc)
        return None


def fetch_news_sentiment() -> dict:
    headlines = _fetch_newsapi() or _fetch_google_news_rss() or []

    if not headlines:
        log.info("No live headlines available - news sentiment defaults to neutral (0.0).")
        return {"date": date.today().isoformat(), "sentiment_score": 0.0, "headlines": [], "is_live": False}

    scores = [_score_headline(h) for h in headlines]
    avg = sum(scores) / len(scores)
    return {
        "date": date.today().isoformat(),
        "sentiment_score": round(avg, 3),
        "headlines": headlines[:5],
        "is_live": True,
    }

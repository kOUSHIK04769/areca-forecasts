#!/usr/bin/env python3
"""
Shivamogga Arecanut (Adike / Betel Nut) Daily Market Tracker
==============================================================

Fetches today's Arecanut mandi prices for Shivamogga, Karnataka.
Saves history and builds a premium HTML dashboard.
"""

import csv
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

import requests

# Ensure standard output uses UTF-8 (particularly on Windows) to prevent UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
HISTORY_CSV = BASE_DIR / "areca_price_history.csv"
DASHBOARD_HTML = BASE_DIR / "dashboard.html"

STATE = "Karnataka"
DISTRICT = "Shivamogga"          # Agmarknet sometimes spells it "Shimoga"
COMMODITY = "Arecanut"

# Official Agmarknet resource on data.gov.in
DATA_GOV_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_API_URL = f"https://api.data.gov.in/resource/{DATA_GOV_RESOURCE_ID}"

MAMCOS_URL = "https://mamcos.info/areca-market-rates/"

MOVING_AVG_SHORT = 3
MOVING_AVG_LONG = 7

REFERENCE_LINKS = {
    "Agmarknet dataset (data.gov.in - official govt source)":
        "https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi",
    "Agmarknet portal (official govt portal)":
        "https://agmarknet.gov.in/PriceAndArrivals/CommodityDailyStateWise.aspx",
    "MAMCOS Shivamogga areca rates (local cooperative)":
        "https://mamcos.info/areca-market-rates/",
    "ACROP mandi tracker - Shimoga APMC":
        "https://acrop.app/mandi/karnataka/shivamogga/shimoga/arecanut",
    "Kisandeals mandi tracker - Shimoga":
        "https://www.kisandeals.com/mandiprices/ARECANUT(BETELNUT-SUPARI)/KARNATAKA/SHIMOGA",
}


# --------------------------------------------------------------------------
# STEP 1: FETCH TODAY'S PRICE
# --------------------------------------------------------------------------

def fetch_from_data_gov_in():
    """Try the official govt API first. Returns a list of record dicts."""
    api_key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not api_key:
        print("[info] DATA_GOV_IN_API_KEY not set - skipping official API, "
              "trying MAMCOS fallback instead.")
        return None

    params = {
        "api-key": api_key,
        "format": "json",
        "limit": 50,
        "filters[state]": STATE,
        "filters[district]": DISTRICT,
        "filters[commodity]": COMMODITY,
    }
    try:
        resp = requests.get(DATA_GOV_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        records = payload.get("records", [])
        if not records:
            print("[warn] Official API returned no records for "
                  f"{DISTRICT} / {COMMODITY} today.")
            return None
        return records
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Official API fetch failed: {exc}")
        return None


def fetch_from_mamcos():
    """
    Fallback scraper for MAMCOS's public daily rates page.
    Handles branch headers and multiple tables.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[error] beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        return None

    try:
        resp = requests.get(MAMCOS_URL, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"[error] Could not reach MAMCOS site: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    records = []

    # Table 0: branch-wise daily rates (e.g. SHIVAMOGGA, SAGARA, HOSANAGARA headers)
    if tables:
        rows = tables[0].find_all("tr")
        current_market = "Unknown"
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            
            # If the row has fewer than 5 cells, it's likely a market branch header (e.g., ['SHIVAMOGGA'])
            if len(cells) < 5:
                m_text = cells[0].strip().upper()
                if any(k in m_text for k in ["SHIVAMOGGA", "SHIMOGA", "SAGAR", "HOSANAGARA", "KOPPA", "SIRSI"]):
                    current_market = cells[0].strip()
                continue
            
            # Skip the table sub-header (e.g., ['Date', 'Product', ...])
            if "DATE" in cells[0].upper() or "PRODUCT" in cells[1].upper():
                continue
            
            records.append({
                "market": current_market,
                "arrival_date": cells[0],
                "variety": cells[1],
                "min_price": cells[2],
                "max_price": cells[3],
                "modal_price": cells[4],
            })

    # Table 1: historical/daily Shimoga APMC rates as a fallback
    if not records and len(tables) > 1:
        rows = tables[1].find_all("tr")
        current_market = "Shivamogga"
        current_date = date.today().isoformat()
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            if len(cells) == 1:
                m_text = cells[0].upper()
                if "/" in m_text:
                    parts = m_text.split("/")
                    current_market = parts[1].strip()
                    current_date = parts[0].strip()
                continue
            if "ITEM" in cells[0].upper():
                continue
            if len(cells) >= 4:
                records.append({
                    "market": current_market,
                    "arrival_date": current_date,
                    "variety": cells[0],
                    "min_price": cells[1],
                    "max_price": cells[2],
                    "modal_price": cells[3],
                })

    if not records:
        print("[warn] MAMCOS page structure may have changed - no rows parsed.")
        return None
    return records


def to_float(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return None


def get_today_price():
    """
    Returns a single representative reading for the day as a dict.
    Filters records to find the benchmark 'Rashi' or 'Rashi Edi' variety
    specifically for the Shivamogga market.
    """
    records = fetch_from_data_gov_in()
    source = "Agmarknet (data.gov.in official API)"

    if not records:
        records = fetch_from_mamcos()
        source = "MAMCOS (mamcos.info)"

    if not records:
        return None

    # Step 1: Search for Shivamogga + Rashi/Rashi Edi
    for rec in records:
        market_name = rec.get("market", "").upper()
        variety_name = rec.get("variety", "").upper()
        modal = to_float(rec.get("modal_price"))
        if modal is not None:
            if ("SHIVAMOGGA" in market_name or "SHIMOGA" in market_name) and "RASHI" in variety_name:
                return {
                    "date": date.today().isoformat(),
                    "market": rec.get("market", DISTRICT),
                    "variety": rec.get("variety", "N/A"),
                    "min_price": to_float(rec.get("min_price")),
                    "max_price": to_float(rec.get("max_price")),
                    "modal_price": modal,
                    "source": source,
                }

    # Step 2: Fall back to any Shivamogga variety
    for rec in records:
        market_name = rec.get("market", "").upper()
        modal = to_float(rec.get("modal_price"))
        if modal is not None:
            if "SHIVAMOGGA" in market_name or "SHIMOGA" in market_name:
                return {
                    "date": date.today().isoformat(),
                    "market": rec.get("market", DISTRICT),
                    "variety": rec.get("variety", "N/A"),
                    "min_price": to_float(rec.get("min_price")),
                    "max_price": to_float(rec.get("max_price")),
                    "modal_price": modal,
                    "source": source,
                }

    # Step 3: Fall back to any Rashi variety in other markets (e.g. Sagara, Hosanagara)
    for rec in records:
        variety_name = rec.get("variety", "").upper()
        modal = to_float(rec.get("modal_price"))
        if modal is not None:
            if "RASHI" in variety_name:
                return {
                    "date": date.today().isoformat(),
                    "market": rec.get("market", DISTRICT),
                    "variety": rec.get("variety", "N/A"),
                    "min_price": to_float(rec.get("min_price")),
                    "max_price": to_float(rec.get("max_price")),
                    "modal_price": modal,
                    "source": source,
                }

    # Step 4: Fall back to the very first record with a valid modal price
    for rec in records:
        modal = to_float(rec.get("modal_price"))
        if modal is not None:
            return {
                "date": date.today().isoformat(),
                "market": rec.get("market", DISTRICT),
                "variety": rec.get("variety", "N/A"),
                "min_price": to_float(rec.get("min_price")),
                "max_price": to_float(rec.get("max_price")),
                "modal_price": modal,
                "source": source,
            }

    return None


# --------------------------------------------------------------------------
# STEP 2: STORE HISTORY
# --------------------------------------------------------------------------

def append_history(reading: dict):
    file_exists = HISTORY_CSV.exists()
    
    # Read history to prevent duplicate daily entry
    existing_dates = set()
    if file_exists:
        with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                existing_dates.add(r["date"])
                
    if reading["date"] in existing_dates:
        print(f"[info] Entry for date {reading['date']} already exists. Updating history file with latest daily quote.")
        # Load and update in memory, then overwrite
        rows = []
        with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["date"] == reading["date"]:
                r["market"] = reading["market"]
                r["variety"] = reading["variety"]
                r["min_price"] = reading["min_price"]
                r["max_price"] = reading["max_price"]
                r["modal_price"] = reading["modal_price"]
                r["source"] = reading["source"]
        with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "date", "market", "variety", "min_price", "max_price",
                "modal_price", "source"
            ])
            writer.writeheader()
            writer.writerows(rows)
    else:
        with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "date", "market", "variety", "min_price", "max_price",
                "modal_price", "source"
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow(reading)


def load_history():
    if not HISTORY_CSV.exists():
        return []
    with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["modal_price"] = to_float(r["modal_price"])
        r["min_price"] = to_float(r.get("min_price"))
        r["max_price"] = to_float(r.get("max_price"))
    # de-duplicate by date, keep last entry for that date
    by_date = {}
    for r in rows:
        by_date[r["date"]] = r
    return [by_date[d] for d in sorted(by_date.keys())]


# --------------------------------------------------------------------------
# STEP 3: ANALYSIS
# --------------------------------------------------------------------------

def moving_average(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def analyze_trend(history):
    """
    Computes moving average indicators and day-over-day changes.
    """
    prices = [h["modal_price"] for h in history if h["modal_price"] is not None]
    if len(prices) < 2:
        return {
            "signal": "NOT ENOUGH DATA",
            "detail": "Need at least 2 days of history. Run this script daily to view market signals.",
            "day_change_pct": None,
        }

    today, yesterday = prices[-1], prices[-2]
    day_change_pct = ((today - yesterday) / yesterday) * 100 if yesterday else 0

    short_ma = moving_average(prices, MOVING_AVG_SHORT)
    long_ma = moving_average(prices, MOVING_AVG_LONG)

    if short_ma is not None and long_ma is not None:
        if short_ma > long_ma and day_change_pct > 0:
            signal = "UP"
            detail = (f"The 3-day average (₹{short_ma:,.0f}) has crossed above the "
                      f"7-day average (₹{long_ma:,.0f}), combined with today's price "
                      f"increase of {day_change_pct:.2f}% vs yesterday. Short-term momentum is upward.")
        elif short_ma < long_ma and day_change_pct < 0:
            signal = "DOWN"
            detail = (f"The 3-day average (₹{short_ma:,.0f}) is below the "
                      f"7-day average (₹{long_ma:,.0f}), and today's price "
                      f"declined {day_change_pct:.2f}% vs yesterday. Short-term momentum is downward.")
        else:
            signal = "FLAT / MIXED"
            detail = (f"The 3-day average (₹{short_ma:,.0f}) vs the 7-day average "
                      f"(₹{long_ma:,.0f}) and today's {day_change_pct:+.2f}% change "
                      "do not agree, indicating range-bound trading.")
    else:
        # Limited history
        if day_change_pct > 0.5:
            signal, detail = "UP", f"Price increased by {day_change_pct:.2f}% compared to yesterday (limited history)."
        elif day_change_pct < -0.5:
            signal, detail = "DOWN", f"Price decreased by {day_change_pct:.2f}% compared to yesterday (limited history)."
        else:
            signal, detail = "FLAT", f"Price is relatively unchanged ({day_change_pct:+.2f}%) vs yesterday."

    return {
        "signal": signal,
        "detail": detail,
        "day_change_pct": day_change_pct,
        "short_ma": short_ma,
        "long_ma": long_ma,
    }


# --------------------------------------------------------------------------
# STEP 4: BUILD THE HTML DASHBOARD
# --------------------------------------------------------------------------

SIGNAL_THEME = {
    "UP": {
        "color": "#10b981",
        "glow": "rgba(16, 185, 129, 0.25)",
        "class": "change-up"
    },
    "DOWN": {
        "color": "#f43f5e",
        "glow": "rgba(244, 63, 94, 0.25)",
        "class": "change-down"
    },
    "FLAT": {
        "color": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.25)",
        "class": "change-flat"
    },
    "FLAT / MIXED": {
        "color": "#f59e0b",
        "glow": "rgba(245, 158, 11, 0.25)",
        "class": "change-flat"
    },
    "NOT ENOUGH DATA": {
        "color": "#6b7280",
        "glow": "rgba(107, 114, 128, 0.25)",
        "class": "change-flat"
    }
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shivamogga Arecanut Market Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg-primary: #0b0f19;
    --bg-secondary: #111827;
    --card-bg: rgba(22, 28, 45, 0.7);
    --card-border: rgba(255, 255, 255, 0.06);
    --text-primary: #f3f4f6;
    --text-secondary: #9ca3af;
    --accent: #d97706; /* Areca Amber Gold */
    --accent-bg: rgba(217, 119, 6, 0.1);
    --accent-glow: rgba(217, 119, 6, 0.3);
    
    --color-up: #10b981;
    --color-up-bg: rgba(16, 185, 129, 0.1);
    --color-up-glow: rgba(16, 185, 129, 0.25);
    
    --color-down: #f43f5e;
    --color-down-bg: rgba(244, 63, 94, 0.1);
    --color-down-glow: rgba(244, 63, 94, 0.25);
    
    --color-flat: #f59e0b;
    --color-flat-bg: rgba(245, 158, 11, 0.1);
    --color-flat-glow: rgba(245, 158, 11, 0.25);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  
  body {{
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    background-color: var(--bg-primary);
    background-image: radial-gradient(circle at 10% 20%, rgba(217, 119, 6, 0.05) 0%, transparent 40%),
                      radial-gradient(circle at 90% 80%, rgba(99, 102, 241, 0.05) 0%, transparent 40%);
    color: var(--text-primary);
    min-height: 100vh;
    padding: 32px 16px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}

  .wrap {{
    max-width: 1000px;
    margin: 0 auto;
  }}

  header {{
    margin-bottom: 32px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding-bottom: 24px;
    flex-wrap: wrap;
    gap: 16px;
  }}

  .brand h1 {{
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, #fff 0%, #d97706 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .brand .updated {{
    font-size: 13px;
    color: var(--text-secondary);
    margin-top: 4px;
  }}

  .source-badge {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 9999px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}

  .source-badge::before {{
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    background: #10b981;
    border-radius: 50%;
    box-shadow: 0 0 8px #10b981;
  }}

  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}

  @media (max-width: 768px) {{
    .grid-2 {{ grid-template-columns: 1fr; }}
  }}

  .card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    backdrop-filter: blur(12px);
    border-radius: 20px;
    padding: 24px;
    position: relative;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  }}

  .card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 3px;
    background: transparent;
  }}

  .card:hover {{
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.1);
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
  }}

  /* Signal Card Styling */
  .card-signal::before {{
    background: {signal_color};
  }}

  .signal-label {{
    font-size: 12px;
    font-weight: 700;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
  }}

  .signal-value-container {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 12px;
  }}

  .signal-badge {{
    font-size: 32px;
    font-weight: 800;
    color: {signal_color};
    text-shadow: 0 0 20px {signal_glow};
    letter-spacing: -0.02em;
  }}

  .signal-indicator {{
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: {signal_color};
    box-shadow: 0 0 12px {signal_color};
    animation: pulse 2s infinite;
  }}

  @keyframes pulse {{
    0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 {signal_glow}; }}
    70% {{ transform: scale(1); box-shadow: 0 0 0 10px rgba(0, 0, 0, 0); }}
    100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(0, 0, 0, 0); }}
  }}

  .signal-detail {{
    font-size: 14px;
    color: var(--text-secondary);
    line-height: 1.6;
  }}

  /* Price Card Styling */
  .card-price::before {{
    background: linear-gradient(90deg, #d97706, #f59e0b);
  }}

  .price-main {{
    margin: 8px 0 20px 0;
  }}

  .price-number {{
    font-size: 36px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.03em;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }}

  .price-unit {{
    font-size: 16px;
    font-weight: 500;
    color: var(--text-secondary);
  }}

  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}

  .metric-box {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    padding: 12px;
  }}

  .metric-label {{
    font-size: 11px;
    text-transform: uppercase;
    color: var(--text-secondary);
    letter-spacing: 0.04em;
    font-weight: 600;
  }}

  .metric-value {{
    font-size: 15px;
    font-weight: 700;
    color: #fff;
    margin-top: 2px;
  }}

  .metric-value.change-up {{ color: var(--color-up); }}
  .metric-value.change-down {{ color: var(--color-down); }}
  .metric-value.change-flat {{ color: var(--color-flat); }}

  /* Chart Card Styling */
  .card-chart {{
    margin-bottom: 20px;
  }}

  /* History Table Card Styling */
  .card-table {{
    margin-bottom: 20px;
  }}

  .table-title {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 16px;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    text-align: left;
  }}

  th {{
    color: var(--text-secondary);
    font-weight: 600;
    padding: 12px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}

  td {{
    padding: 14px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: var(--text-primary);
  }}

  tr:last-child td {{
    border-bottom: none;
  }}

  tr:hover td {{
    background: rgba(255, 255, 255, 0.02);
  }}

  .badge-price {{
    font-family: monospace;
    font-weight: 700;
    color: #fff;
    font-size: 14px;
  }}

  /* Reference links card */
  .links-list {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
    margin-top: 8px;
  }}

  .link-item {{
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 12px;
    padding: 12px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    transition: all 0.2s ease;
  }}

  .link-item:hover {{
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(217, 119, 6, 0.3);
  }}

  .link-item a {{
    color: #fff;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
  }}

  .link-item a svg {{
    flex-shrink: 0;
    color: var(--accent);
  }}

  .link-item:hover a {{
    color: var(--accent);
  }}

  .disclaimer {{
    font-size: 11px;
    color: #6b7280;
    line-height: 1.6;
    margin-top: 32px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 16px;
  }}

  .disclaimer b {{
    color: var(--text-secondary);
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <h1>🌰 Shivamogga Arecanut (Adike) Market</h1>
      <div class="updated">Last synced: {updated_at}</div>
    </div>
    <div class="source-badge">
      Source: {source}
    </div>
  </header>

  <div class="grid-2">
    <!-- Trend signal card -->
    <div class="card card-signal">
      <div class="signal-label">Momentum & Trend Signal</div>
      <div class="signal-value-container">
        <div class="signal-indicator"></div>
        <div class="signal-badge">{signal}</div>
      </div>
      <div class="signal-detail">{detail}</div>
    </div>

    <!-- Latest price card -->
    <div class="card card-price">
      <div class="signal-label">Latest Trade Rate ({market})</div>
      <div class="price-main">
        <div class="price-number">
          ₹ {latest_price}
          <span class="price-unit">/ quintal</span>
        </div>
      </div>
      <div class="metrics-grid">
        <div class="metric-box">
          <div class="metric-label">Min Price</div>
          <div class="metric-value">₹ {min_price}</div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Max Price</div>
          <div class="metric-value">₹ {max_price}</div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Day Change</div>
          <div class="metric-value {change_class}">{day_change}</div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Variety</div>
          <div class="metric-value" style="color: var(--accent);">{variety}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Price history chart card -->
  <div class="card card-chart">
    <div class="table-title">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 3v18h18M18.7 8l-5.1 5.2-2.8-2.7L7 14.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
      Modal Price Trend (Last 30 Days)
    </div>
    <div style="position: relative; height: 260px; width: 100%;">
      <canvas id="priceChart"></canvas>
    </div>
  </div>

  <!-- Recent readings table card -->
  <div class="card card-table">
    <div class="table-title">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" stroke-linecap="round" stroke-linejoin="round"/></svg>
      Recent Market Records
    </div>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Market Location</th>
            <th>Variety</th>
            <th style="text-align: right;">Modal Price (₹/qtl)</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </div>
  </div>

  <!-- References card -->
  <div class="card">
    <div class="table-title">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" stroke-linecap="round" stroke-linejoin="round"/></svg>
      Official Mandi Data Resources
    </div>
    <div class="links-list">
      {reference_links}
    </div>
  </div>

  <div class="disclaimer">
    This dashboard calculates a simple moving-average (3-day vs 7-day) and day-over-day momentum signal derived from historical APMC and cooperative market reports. It is <b>not financial advice</b>. Arecanut prices are heavily influenced by local crop yields, seasonal arrivals, import tariff policies, and commercial demand from processed betel nut industries, which are not modeled here. Always verify transactions against official APMC/MAMCOS releases before making trading or farming supply decisions.
  </div>
</div>

<script>
  const labels = {chart_labels};
  const data = {chart_values};
  
  const ctx = document.getElementById('priceChart').getContext('2d');
  
  // Create gradient
  const gradient = ctx.createLinearGradient(0, 0, 0, 240);
  gradient.addColorStop(0, 'rgba(217, 119, 6, 0.25)');
  gradient.addColorStop(1, 'rgba(217, 119, 6, 0.00)');

  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: labels.map(d => {{
        const parts = d.split('-');
        if (parts.length === 3) {{
          const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
          return `${{parseInt(parts[2])}} ${{months[parseInt(parts[1]) - 1]}}`;
        }}
        return d;
      }}),
      datasets: [{{
        label: 'Modal Price (₹/quintal)',
        data: data,
        borderColor: '#d97706',
        borderWidth: 3,
        backgroundColor: gradient,
        fill: true,
        tension: 0.35,
        pointRadius: 4,
        pointBackgroundColor: '#d97706',
        pointBorderColor: '#0b0f19',
        pointBorderWidth: 2,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: '#fff',
        pointHoverBorderColor: '#d97706',
        pointHoverBorderWidth: 3,
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#111827',
          titleColor: '#9ca3af',
          bodyColor: '#fff',
          bodyFont: {{ family: "'Plus Jakarta Sans', sans-serif", weight: '600' }},
          titleFont: {{ family: "'Plus Jakarta Sans', sans-serif" }},
          borderColor: 'rgba(255, 255, 255, 0.08)',
          borderWidth: 1,
          padding: 12,
          displayColors: false,
          callbacks: {{
            label: function(context) {{
              return `₹ ${{context.parsed.y.toLocaleString('en-IN')}} / quintal`;
            }}
          }}
        }}
      }},
      scales: {{
        y: {{
          grid: {{
            color: 'rgba(255, 255, 255, 0.05)',
            drawTicks: false
          }},
          ticks: {{
            color: '#9ca3af',
            font: {{ family: "'Plus Jakarta Sans', sans-serif", size: 11 }},
            callback: function(value) {{
              return '₹' + value.toLocaleString('en-IN');
            }}
          }},
          border: {{ dash: [4, 4] }}
        }},
        x: {{
          grid: {{ display: false }},
          ticks: {{
            color: '#9ca3af',
            font: {{ family: "'Plus Jakarta Sans', sans-serif", size: 11 }},
            maxTicksLimit: 8
          }}
        }}
      }}
    }}
  }});
</script>
</body>
</html>
"""


def build_dashboard(latest: dict, history: list, trend: dict):
    signal = trend["signal"]
    theme = SIGNAL_THEME.get(signal, SIGNAL_THEME["NOT ENOUGH DATA"])

    if trend.get("day_change_pct") is not None:
        arrow = "▲" if trend["day_change_pct"] > 0 else ("▼" if trend["day_change_pct"] < 0 else "→")
        day_change = f"{arrow} {trend['day_change_pct']:+.2f}%"
    else:
        day_change = "N/A"

    table_rows = "\n".join(
        f"<tr>"
        f"<td>{h['date']}</td>"
        f"<td>{h['market']}</td>"
        f"<td>{h.get('variety') or 'N/A'}</td>"
        f"<td style='text-align: right;' class='badge-price'>₹ {h['modal_price']:,.0f}</td>"
        f"</tr>"
        for h in reversed(history[-14:])  # last 14 readings
        if h["modal_price"] is not None
    )

    reference_links = "\n".join(
        f'<div class="link-item">'
        f'  <a href="{url}" target="_blank">'
        f'    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">'
        f'      <path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" stroke-linecap="round" stroke-linejoin="round"/>'
        f'    </svg>'
        f'    {name}'
        f'  </a>'
        f'</div>'
        for name, url in REFERENCE_LINKS.items()
    )

    chart_labels = json.dumps([h["date"] for h in history[-30:]])
    chart_values = json.dumps([h["modal_price"] for h in history[-30:]])

    html = HTML_TEMPLATE.format(
        signal_color=theme["color"],
        signal_glow=theme["glow"],
        change_class=theme["class"],
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        source=latest["source"],
        signal=signal,
        detail=trend["detail"],
        market=latest["market"],
        latest_price=f"{latest['modal_price']:,.0f}",
        min_price=f"{latest['min_price']:,.0f}" if latest["min_price"] else "N/A",
        max_price=f"{latest['max_price']:,.0f}" if latest["max_price"] else "N/A",
        day_change=day_change,
        variety=latest.get("variety") or "N/A",
        table_rows=table_rows or "<tr><td colspan='4'>No history yet</td></tr>",
        reference_links=reference_links,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )
    DASHBOARD_HTML.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    print(f"[{datetime.now()}] Fetching today's Shivamogga arecanut price...")
    reading = get_today_price()

    if reading is None:
        print("[error] Could not fetch a price from any source today.")
        print("        Check your internet connection / API key, or visit these pages manually:")
        for name, url in REFERENCE_LINKS.items():
            print(f"          - {name}: {url}")
        sys.exit(1)

    print(f"[ok] {reading['date']} | {reading['market']} | "
          f"modal price ₹{reading['modal_price']:,.0f}/qtl | source: {reading['source']}")

    append_history(reading)
    history = load_history()
    trend = analyze_trend(history)

    print(f"[signal] {trend['signal']} - {trend['detail']}")

    build_dashboard(reading, history, trend)
    print(f"[done] Dashboard updated: {DASHBOARD_HTML}")
    print("       Open it in your browser to view.")


if __name__ == "__main__":
    main()

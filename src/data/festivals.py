"""
src/data/festivals.py
======================
Simple rule-based festival/demand-spike calendar for Karnataka.
Arecanut (paan/supari) demand rises around these festivals. This is
intentionally a static, editable list rather than a paid calendar API -
update `FESTIVALS` yearly or swap in the `holidays` PyPI package if you
want it fully automated.
"""

from __future__ import annotations

from datetime import date, timedelta

# Add/edit dates each year. Format: "YYYY-MM-DD": "Festival name"
FESTIVALS: dict[str, str] = {
    "2026-01-14": "Makar Sankranti",
    "2026-03-19": "Ugadi",
    "2026-08-15": "Independence Day",
    "2026-08-26": "Ganesh Chaturthi",
    "2026-10-11": "Dasara",
    "2026-10-20": "Deepavali",
    "2026-11-04": "Kartika Purnima",
}

DEMAND_WINDOW_DAYS = 10  # days before a festival where demand typically firms up


def festival_indicator(for_date: date) -> dict:
    """Returns whether `for_date` falls within a pre-festival demand window."""
    for date_str, name in FESTIVALS.items():
        festival_date = date.fromisoformat(date_str)
        window_start = festival_date - timedelta(days=DEMAND_WINDOW_DAYS)
        if window_start <= for_date <= festival_date:
            days_to = (festival_date - for_date).days
            return {"is_festival_window": True, "festival_name": name, "days_to_festival": days_to}
    return {"is_festival_window": False, "festival_name": None, "days_to_festival": None}

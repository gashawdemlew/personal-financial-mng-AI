import re
from datetime import date, timedelta
from typing import Dict, Optional


def _month_bounds(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    end = next_start - timedelta(days=1)
    return start, end


def _shift_months(anchor: date, months_back: int) -> date:
    y = anchor.year
    m = anchor.month - months_back
    while m <= 0:
        y -= 1
        m += 12
    return date(y, m, 1)


def parse_period(question: str, today: Optional[date] = None) -> Optional[Dict]:
    q = (question or "").lower()
    today = today or date.today()

    if "this week" in q:
        start = today - timedelta(days=today.weekday())
        return {"start": start, "end": today, "label": "this week", "kind": "this_week"}

    m = re.search(r"(?:last|past)\s+(\d+)\s+months?", q)
    if m:
        n = max(1, int(m.group(1)))
        this_month_start = date(today.year, today.month, 1)
        end = this_month_start - timedelta(days=1)
        start_anchor = _shift_months(this_month_start, n)
        start = date(start_anchor.year, start_anchor.month, 1)
        return {
            "start": start,
            "end": end,
            "label": f"last {n} months",
            "kind": "last_n_months",
            "months": n,
        }

    if "last month" in q:
        this_month_start = date(today.year, today.month, 1)
        end = this_month_start - timedelta(days=1)
        start = date(end.year, end.month, 1)
        return {"start": start, "end": end, "label": "last month", "kind": "last_month"}

    if "this month" in q:
        start = date(today.year, today.month, 1)
        return {"start": start, "end": today, "label": "this month", "kind": "this_month"}

    return None


def period_from_llm(payload: Dict) -> Optional[Dict]:
    if not payload:
        return None
    kind = str(payload.get("kind") or "").strip().lower()
    if kind in {"", "none"}:
        return None

    start = payload.get("start_date")
    end = payload.get("end_date")
    label = payload.get("label") or kind
    if not start or not end:
        return None
    try:
        start_d = date.fromisoformat(str(start))
        end_d = date.fromisoformat(str(end))
    except Exception:
        return None
    if end_d < start_d:
        return None
    out = {"start": start_d, "end": end_d, "label": str(label), "kind": kind}
    if payload.get("months") is not None:
        try:
            out["months"] = int(payload.get("months"))
        except Exception:
            pass
    return out

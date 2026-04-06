from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_month(month_s: str) -> date:
    return datetime.strptime(month_s, "%Y-%m").date()


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_from_txn(txn_date: str) -> str:
    return txn_date[:7]


def _pick_history_window(month_keys: List[str]) -> int:
    count = len(sorted(set(month_keys)))
    if count >= 6:
        return 6
    if count >= 3:
        return 3
    if count >= 1:
        return 1
    return 0


def _average(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _normalize_allocations(raw: Dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in (raw or {}).items():
        key = str(k or "").strip().lower()
        if not key:
            continue
        try:
            amount = float(v)
        except Exception:
            continue
        if amount < 0:
            continue
        out[key] = round(amount, 2)
    return out


def _monthly_transaction_stats(rows: List[Dict], up_to_month_exclusive: str) -> Dict[str, Dict]:
    by_month: Dict[str, Dict] = defaultdict(
        lambda: {"income": 0.0, "expense": 0.0, "category_expense": defaultdict(float)}
    )
    cutoff_month = _parse_month(up_to_month_exclusive)
    for r in rows:
        txn_d = _parse_date(str(r["txn_date"]))
        month = _month_key(date(txn_d.year, txn_d.month, 1))
        if _parse_month(month) >= cutoff_month:
            continue
        amount = float(r.get("amount", 0.0))
        txn_type = str(r.get("txn_type", "")).strip().lower()
        if txn_type == "credit":
            by_month[month]["income"] += amount
        elif txn_type == "debit":
            by_month[month]["expense"] += amount
            cat = str(r.get("narration", "other")).strip().lower() or "other"
            by_month[month]["category_expense"][cat] += amount
    return by_month


def _monthly_budget_stats(budgets: List[Dict], up_to_month_exclusive: str) -> Dict[str, Dict]:
    by_month: Dict[str, Dict] = {}
    cutoff = _parse_month(up_to_month_exclusive)
    for b in budgets:
        month = str(b.get("budget_month", "")).strip()
        if not month:
            continue
        try:
            parsed = _parse_month(month)
        except Exception:
            continue
        if parsed >= cutoff:
            continue
        by_month[month] = {
            "total_budget": float(b.get("total_budget", 0.0)),
            "allocations": _normalize_allocations(b.get("category_allocations", {})),
        }
    return by_month


def suggest_budget(
    transactions: List[Dict],
    monthly_budgets: List[Dict],
    target_month: str,
) -> Dict:
    tx_monthly = _monthly_transaction_stats(transactions, up_to_month_exclusive=target_month)
    budget_monthly = _monthly_budget_stats(monthly_budgets, up_to_month_exclusive=target_month)

    history_months = sorted(set(list(tx_monthly.keys()) + list(budget_monthly.keys())))
    window = _pick_history_window(history_months)
    if window == 0:
        return {
            "success": False,
            "mode_used": "insufficient_data",
            "window_used_months": 0,
            "message": "not enough data available",
        }

    selected_months = history_months[-window:]
    tx_selected = [m for m in selected_months if m in tx_monthly]
    budget_selected = [m for m in selected_months if m in budget_monthly]

    income_avg = _average([tx_monthly[m]["income"] for m in tx_selected]) if tx_selected else 0.0
    expense_avg = _average([tx_monthly[m]["expense"] for m in tx_selected]) if tx_selected else 0.0
    budget_avg = _average([budget_monthly[m]["total_budget"] for m in budget_selected]) if budget_selected else 0.0

    mode = "behavior_only"
    if tx_selected and budget_selected:
        mode = "budget_plus_behavior"
    elif budget_selected and not tx_selected:
        mode = "budget_only"

    if mode == "budget_plus_behavior":
        behavior_total = expense_avg + max((income_avg - expense_avg) * 0.40, 0.0)
        suggested_total = round((0.60 * budget_avg) + (0.40 * behavior_total), 2)
    elif mode == "budget_only":
        suggested_total = round(budget_avg, 2)
    else:
        if not tx_selected:
            return {
                "success": False,
                "mode_used": "insufficient_data",
                "window_used_months": 0,
                "message": "not enough data available",
            }
        suggested_total = round(expense_avg + max((income_avg - expense_avg) * 0.35, 0.0), 2)

    # Category allocation baseline
    category_totals = defaultdict(float)
    for m in tx_selected:
        for cat, amount in tx_monthly[m]["category_expense"].items():
            category_totals[cat] += float(amount)

    if category_totals:
        total_cat = sum(category_totals.values())
        shares = {k: (v / total_cat) for k, v in category_totals.items() if total_cat > 0}
    else:
        alloc_totals = defaultdict(float)
        for m in budget_selected:
            for cat, amount in budget_monthly[m]["allocations"].items():
                alloc_totals[cat] += float(amount)
        alloc_sum = sum(alloc_totals.values())
        shares = {k: (v / alloc_sum) for k, v in alloc_totals.items() if alloc_sum > 0}

    category_suggestions = []
    for cat, share in sorted(shares.items(), key=lambda x: x[1], reverse=True):
        amount = round(suggested_total * share, 2)
        category_suggestions.append(
            {
                "category": cat,
                "share_pct": round(share * 100, 2),
                "suggested_budget": amount,
            }
        )

    if mode == "budget_plus_behavior":
        confidence = "high" if window >= 3 else "medium"
    elif mode == "behavior_only":
        confidence = "medium" if window >= 3 else "low"
    else:
        confidence = "low"

    return {
        "success": True,
        "mode_used": mode,
        "window_used_months": window,
        "selected_history_months": selected_months,
        "target_month": target_month,
        "avg_income": round(income_avg, 2),
        "avg_expense": round(expense_avg, 2),
        "avg_historical_budget": round(budget_avg, 2),
        "overall_monthly_budget_suggestion": round(max(suggested_total, 0.0), 2),
        "category_budget_suggestions": category_suggestions,
        "confidence": confidence,
        "message": "Smart budget suggestion generated.",
    }

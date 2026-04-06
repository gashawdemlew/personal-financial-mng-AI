import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_bounds(anchor: date) -> Tuple[date, date]:
    start = date(anchor.year, anchor.month, 1)
    if anchor.month == 12:
        next_start = date(anchor.year + 1, 1, 1)
    else:
        next_start = date(anchor.year, anchor.month + 1, 1)
    end = next_start - timedelta(days=1)
    return start, end


def _last_month_bounds(today: date) -> Tuple[date, date]:
    this_month_start = date(today.year, today.month, 1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = date(last_month_end.year, last_month_end.month, 1)
    return last_month_start, last_month_end


def _filter_date(rows: List[Dict], start: date, end: date) -> List[Dict]:
    return [r for r in rows if start <= _parse_date(r["txn_date"]) <= end]


def _sum_amount(rows: List[Dict], txn_type: str = "") -> float:
    if txn_type:
        rows = [r for r in rows if r["txn_type"] == txn_type]
    return round(sum(float(r["amount"]) for r in rows), 2)


def _by_category(rows: List[Dict], txn_type: str = "debit") -> Dict[str, float]:
    bucket = defaultdict(float)
    for r in rows:
        if txn_type and r["txn_type"] != txn_type:
            continue
        bucket[r["narration"]] += float(r["amount"])
    return {k: round(v, 2) for k, v in sorted(bucket.items(), key=lambda x: x[1], reverse=True)}


def _resolve_period(rows: List[Dict], period: Optional[Dict], default_today: Optional[date] = None):
    if period and period.get("start") and period.get("end"):
        start = period["start"]
        end = period["end"]
        label = period.get("label", f"{start} to {end}")
        return start, end, label, _filter_date(rows, start, end)

    today = default_today or date.today()
    start, end = _last_month_bounds(today)
    return start, end, start.strftime("%B %Y"), _filter_date(rows, start, end)


def category_expense(rows: List[Dict], question_category: str, period: Optional[Dict] = None, today: Optional[date] = None) -> Dict:
    start, end, period_label, scoped = _resolve_period(rows, period, default_today=today)
    last_month = _filter_date(rows, start, end)
    category = (question_category or "").lower()

    if category:
        amount = round(
            sum(float(r["amount"]) for r in scoped if r["txn_type"] == "debit" and r["narration"] == category),
            2,
        )
        answer = f"Your {category} expenses in {period_label} were ETB {amount:.2f}."
        return {
            "period_start": str(start),
            "period_end": str(end),
            "period_label": period_label,
            "category": category,
            "amount": amount,
            "answer": answer,
        }

    totals = _by_category(scoped, txn_type="debit")
    top = next(iter(totals.items()), ("none", 0.0))
    answer = (
        f"Your top expense category in {period_label} was "
        f"{top[0]} at ETB {top[1]:.2f}."
    )
    return {
        "period_start": str(start),
        "period_end": str(end),
        "period_label": period_label,
        "by_category": totals,
        "answer": answer,
    }


def safe_spend_today(rows: List[Dict], today: Optional[date] = None) -> Dict:
    today = today or date.today()
    start, month_end = _month_bounds(today)
    current_month = _filter_date(rows, start, today)
    income = _sum_amount(current_month, "credit")
    spent = _sum_amount(current_month, "debit")
    remaining = round(income - spent, 2)
    days_left = max((month_end - today).days + 1, 1)
    safe_today = round(max(0.0, remaining / days_left), 2)

    answer = (
        f"Based on this month so far, you can safely spend about ETB {safe_today:.2f} today "
        f"(remaining ETB {remaining:.2f} over {days_left} day(s))."
    )
    return {
        "period_start": str(start),
        "period_end": str(month_end),
        "income_month_to_date": income,
        "expense_month_to_date": spent,
        "remaining_budget": remaining,
        "days_remaining": days_left,
        "safe_spend_today": safe_today,
        "answer": answer,
    }


def explain_reversal(rows: List[Dict]) -> Dict:
    ordered = sorted(rows, key=lambda r: (r["txn_date"], r["id"]))
    debits = [r for r in ordered if r["txn_type"] == "debit"]
    credits = [r for r in ordered if r["txn_type"] == "credit"]

    for d in reversed(debits):
        d_date = _parse_date(d["txn_date"])
        for c in credits:
            c_date = _parse_date(c["txn_date"])
            if abs(float(c["amount"]) - float(d["amount"])) > 0.001:
                continue
            if 0 <= (c_date - d_date).days <= 7:
                if any(k in c["narration"] for k in ["reverse", "reversal", "refund"]) or c_date >= d_date:
                    answer = (
                        "This payment likely appears reversed because a matching credit was posted "
                        f"after the debit: debit ETB {d['amount']:.2f} on {d['txn_date']}, "
                        f"credit ETB {c['amount']:.2f} on {c['txn_date']}."
                    )
                    return {"debit": d, "credit": c, "answer": answer}

    return {
        "answer": "I could not find a clear reversal pair in the available transactions. "
                  "Please provide the exact amount/date for deeper tracing."
    }


def income_vs_expense(rows: List[Dict], period: Optional[Dict] = None, today: Optional[date] = None) -> Dict:
    start, end, period_label, scoped = _resolve_period(rows, period, default_today=today)
    income = _sum_amount(scoped, "credit")
    expense = _sum_amount(scoped, "debit")
    savings = round(income - expense, 2)
    ratio = round((expense / income) * 100, 2) if income > 0 else None
    answer = (
        f"In {period_label}, income was ETB {income:.2f}, "
        f"expenses were ETB {expense:.2f}, net savings ETB {savings:.2f}."
    )
    return {
        "period_start": str(start),
        "period_end": str(end),
        "period_label": period_label,
        "income": income,
        "expense": expense,
        "savings": savings,
        "expense_to_income_pct": ratio,
        "answer": answer,
    }


def fixed_vs_variable(rows: List[Dict]) -> Dict:
    # Heuristic: categories appearing in >=3 distinct months are treated as fixed.
    month_map = defaultdict(set)
    totals = defaultdict(float)
    for r in rows:
        if r["txn_type"] != "debit":
            continue
        month_key = r["txn_date"][:7]
        cat = r["narration"]
        month_map[cat].add(month_key)
        totals[cat] += float(r["amount"])

    fixed = {}
    variable = {}
    for cat, months in month_map.items():
        amount = round(totals[cat], 2)
        if len(months) >= 3:
            fixed[cat] = amount
        else:
            variable[cat] = amount

    answer = (
        f"Detected {len(fixed)} likely fixed categories and {len(variable)} variable categories "
        "from historical debit patterns."
    )
    return {"fixed": fixed, "variable": variable, "answer": answer}


def financial_health_score(rows: List[Dict], period: Optional[Dict] = None, today: Optional[date] = None) -> Dict:
    metrics = income_vs_expense(rows, period=period, today=today)
    income = metrics["income"]
    expense = metrics["expense"]
    savings = metrics["savings"]
    savings_rate = (savings / income) if income > 0 else 0.0
    expense_ratio = (expense / income) if income > 0 else 1.0

    score = 50
    score += int(max(min(savings_rate * 100, 30), -20))
    score += int(max(min((1.0 - expense_ratio) * 40, 20), -20))
    score = max(0, min(100, score))

    level = "good" if score >= 70 else "fair" if score >= 45 else "risky"
    answer = f"Your financial health score is {score}/100 ({level})."
    return {
        "score": score,
        "level": level,
        "income": income,
        "expense": expense,
        "savings": savings,
        "answer": answer,
    }


def savings_recommendation(rows: List[Dict], period: Optional[Dict] = None, today: Optional[date] = None) -> Dict:
    metrics = income_vs_expense(rows, period=period, today=today)
    income = metrics["income"]
    expense = metrics["expense"]
    baseline_save = max(income - expense, 0)
    extra = 1000.0
    projected = baseline_save + extra
    answer = (
        f"If you save ETB {extra:.0f} more each month, your monthly savings could improve "
        f"from ETB {baseline_save:.2f} to ETB {projected:.2f}."
    )
    return {"baseline_monthly_savings": baseline_save, "recommended_extra_save": extra, "projected_savings": projected, "answer": answer}

def goal_based_savings_plan(rows: List[Dict], goal_amount: float, target_months: int, today: Optional[date] = None) -> Dict:
    if goal_amount <= 0:
        raise ValueError("goal_amount must be > 0")
    if target_months <= 0:
        raise ValueError("target_months must be > 0")

    monthly = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for r in rows:
        month = r["txn_date"][:7]
        if r["txn_type"] == "credit":
            monthly[month]["income"] += float(r["amount"])
        else:
            monthly[month]["expense"] += float(r["amount"])

    last_three = sorted(monthly.keys())[-3:]
    if last_three:
        avg_monthly_savings = round(
            sum(monthly[m]["income"] - monthly[m]["expense"] for m in last_three) / len(last_three), 2
        )
    else:
        avg_monthly_savings = 0.0

    required_monthly_savings = round(goal_amount / target_months, 2)
    additional_needed = round(max(0.0, required_monthly_savings - max(avg_monthly_savings, 0.0)), 2)
    projected_months = math.ceil(goal_amount / avg_monthly_savings) if avg_monthly_savings > 0 else None

    answer = (
        f"To reach ETB {goal_amount:.2f} in {target_months} month(s), save about "
        f"ETB {required_monthly_savings:.2f}/month. "
        f"Based on your recent average savings (ETB {avg_monthly_savings:.2f}), "
        f"you need ETB {additional_needed:.2f} more per month."
    )
    if projected_months:
        answer += f" At your current pace, the goal may take about {projected_months} month(s)."

    return {
        "goal_amount": round(goal_amount, 2),
        "target_months": target_months,
        "avg_monthly_savings_recent": avg_monthly_savings,
        "required_monthly_savings": required_monthly_savings,
        "additional_monthly_needed": additional_needed,
        "projected_months_at_current_pace": projected_months,
        "answer": answer,
    }


def budget_intelligence(rows: List[Dict]) -> Dict:
    by_cat = _by_category(rows, txn_type="debit")
    top3 = list(by_cat.items())[:3]
    tips = []
    for cat, amount in top3:
        tips.append(f"Reduce {cat} by 10% to save about ETB {amount * 0.10:.2f}.")
    answer = " ".join(tips) if tips else "Not enough debit transactions to generate budget suggestions."
    return {"top_expense_categories": by_cat, "suggestions": tips, "answer": answer}


def historical_trend(rows: List[Dict]) -> Dict:
    monthly = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for r in rows:
        month = r["txn_date"][:7]
        if r["txn_type"] == "credit":
            monthly[month]["income"] += float(r["amount"])
        else:
            monthly[month]["expense"] += float(r["amount"])

    trend = []
    for month in sorted(monthly.keys()):
        m = monthly[month]
        trend.append(
            {
                "month": month,
                "income": round(m["income"], 2),
                "expense": round(m["expense"], 2),
                "net": round(m["income"] - m["expense"], 2),
            }
        )
    answer = "Monthly trend generated for income, expense, and net balance behavior."
    return {"monthly_trend": trend, "answer": answer}


def summary(rows: List[Dict]) -> Dict:
    if not rows:
        return {"answer": "No transaction history found for this user in the selected usecase."}
    income = _sum_amount(rows, "credit")
    expense = _sum_amount(rows, "debit")
    by_cat = _by_category(rows, txn_type="debit")
    answer = (
        f"Total income ETB {income:.2f}, total expense ETB {expense:.2f}, "
        f"net ETB {income - expense:.2f}. Top expense category: "
        f"{next(iter(by_cat.keys()), 'n/a')}."
    )
    return {"income": income, "expense": expense, "by_category": by_cat, "answer": answer}

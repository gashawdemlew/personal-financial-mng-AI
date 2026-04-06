from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional, Tuple

from app.finance.engine import _month_bounds, _parse_date, goal_based_savings_plan
from app.finance.repository import insert_nudge, list_all_transactions, list_goals_for_scope


def _latest_balance(rows: List[Dict]) -> float:
    if not rows:
        return 0.0
    ordered = sorted(rows, key=lambda r: (r["txn_date"], r.get("id", 0)))
    return round(float(ordered[-1].get("balance", 0.0)), 2)


def _week_bounds(today: date) -> Tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def _previous_weeks_window(today: date, weeks: int = 4) -> Tuple[date, date]:
    current_week_start, _ = _week_bounds(today)
    end = current_week_start - timedelta(days=1)
    start = current_week_start - timedelta(days=7 * weeks)
    return start, end


def generate_predictive_liquidity_nudges(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    today: Optional[date] = None,
    lookahead_days: int = 3,
) -> List[Dict]:
    today = today or date.today()
    rows = list_all_transactions(usecase_id=usecase_id, user_id=user_id, linked_account_id=linked_account_id)
    debits = [r for r in rows if r.get("txn_type") == "debit"]
    if len(debits) < 4:
        return []

    by_category = defaultdict(list)
    for r in debits:
        d = _parse_date(r["txn_date"])
        by_category[str(r.get("narration", "other")).strip().lower()].append((d, float(r["amount"])))

    created = []
    current_balance = _latest_balance(rows)
    for category, entries in by_category.items():
        if len(entries) < 3:
            continue
        day_amounts = defaultdict(list)
        for d, amount in entries:
            day_amounts[d.day].append(amount)

        recurring_day = None
        recurring_amounts = []
        for day_key, amounts in day_amounts.items():
            if len(amounts) >= 2:
                recurring_day = day_key
                recurring_amounts = amounts
                break
        if recurring_day is None:
            continue

        try:
            expected_date = date(today.year, today.month, recurring_day)
        except ValueError:
            # Skip impossible day-of-month for this month.
            continue
        days_until = (expected_date - today).days
        if days_until < 0:
            # Try next month.
            if today.month == 12:
                expected_date = date(today.year + 1, 1, min(recurring_day, 28))
            else:
                expected_date = date(today.year, today.month + 1, min(recurring_day, 28))
            days_until = (expected_date - today).days

        if days_until > lookahead_days:
            continue

        expected_amount = round(float(median(recurring_amounts)), 2)
        shortage = round(max(0.0, expected_amount - current_balance), 2)
        priority = "high" if shortage > 0 else "medium"
        title = f"Upcoming {category} payment"
        message = (
            f"Heads up: your {category} payment is usually around day {recurring_day}. "
            f"Expected about ETB {expected_amount:.2f} in {days_until} day(s)."
        )
        if shortage > 0:
            message += f" You may need ETB {shortage:.2f} more to cover it."

        dedupe_key = f"predictive_liquidity:{today.isoformat()}:{category}:{expected_date.isoformat()}"
        created.append(
            insert_nudge(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                nudge_type="predictive_liquidity",
                priority=priority,
                title=title,
                message=message,
                payload={
                    "category": category,
                    "expected_date": expected_date.isoformat(),
                    "expected_amount": expected_amount,
                    "days_until": days_until,
                    "current_balance": current_balance,
                    "shortage": shortage,
                },
                dedupe_key=dedupe_key,
            )
        )
    return [n for n in created if n]


def generate_spending_anomaly_nudges(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    today: Optional[date] = None,
    threshold_pct: float = 0.20,
) -> List[Dict]:
    today = today or date.today()
    rows = list_all_transactions(usecase_id=usecase_id, user_id=user_id, linked_account_id=linked_account_id)
    debits = [r for r in rows if r.get("txn_type") == "debit"]
    if not debits:
        return []

    current_start, current_end = _week_bounds(today)
    prev_start, prev_end = _previous_weeks_window(today, weeks=4)

    current_by_cat = defaultdict(float)
    previous_weekly_by_cat = defaultdict(list)
    for r in debits:
        d = _parse_date(r["txn_date"])
        cat = str(r.get("narration", "other")).strip().lower()
        amount = float(r["amount"])
        if current_start <= d <= current_end:
            current_by_cat[cat] += amount
            continue
        if prev_start <= d <= prev_end:
            week_start = d - timedelta(days=d.weekday())
            previous_weekly_by_cat[cat].append((week_start.isoformat(), amount))

    created = []
    for cat, current_total in current_by_cat.items():
        per_week = defaultdict(float)
        for week_key, amount in previous_weekly_by_cat.get(cat, []):
            per_week[week_key] += amount
        if not per_week:
            continue

        baseline = sum(per_week.values()) / len(per_week)
        if baseline <= 0:
            continue
        increase = (current_total - baseline) / baseline
        if increase < threshold_pct:
            continue

        pct = round(increase * 100, 1)
        title = f"{cat.title()} spending spike"
        message = (
            f"You've spent {pct:.1f}% more on {cat} this week than your recent weekly average. "
            f"(This week ETB {current_total:.2f} vs baseline ETB {baseline:.2f})."
        )
        dedupe_key = f"spending_anomaly:{today.isoformat()}:{cat}"
        created.append(
            insert_nudge(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                nudge_type="spending_anomaly",
                priority="medium",
                title=title,
                message=message,
                payload={
                    "category": cat,
                    "week_start": current_start.isoformat(),
                    "week_end": current_end.isoformat(),
                    "current_week_total": round(current_total, 2),
                    "baseline_weekly_avg": round(baseline, 2),
                    "increase_pct": pct,
                },
                dedupe_key=dedupe_key,
            )
        )
    return [n for n in created if n]


def generate_goal_aware_nudges(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    today: Optional[date] = None,
) -> List[Dict]:
    today = today or date.today()
    goals = list_goals_for_scope(
        usecase_id=usecase_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        status="active",
    )
    if not goals:
        return []

    rows = list_all_transactions(usecase_id=usecase_id, user_id=user_id, linked_account_id=linked_account_id)
    created = []
    for goal in goals:
        plan = goal_based_savings_plan(
            rows,
            goal_amount=float(goal["goal_amount"]),
            target_months=int(goal["target_months"]),
            today=today,
        )
        additional = float(plan.get("additional_monthly_needed", 0.0))
        projected_months = plan.get("projected_months_at_current_pace")
        target_months = int(goal["target_months"])
        if additional <= 0.0 and projected_months and projected_months <= target_months:
            continue

        title = f"Goal check: {goal['goal_name']}"
        message = (
            f"To stay on track for goal '{goal['goal_name']}', target ETB "
            f"{plan['required_monthly_savings']:.2f}/month."
        )
        if additional > 0:
            message += f" You need about ETB {additional:.2f} more monthly at your current pace."
        if projected_months:
            message += f" Current pace projects about {projected_months} month(s)."

        dedupe_key = f"goal_aware:{today.isoformat()}:{goal['goal_name']}"
        created.append(
            insert_nudge(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                nudge_type="goal_aware",
                priority="high" if additional > 0 else "medium",
                title=title,
                message=message,
                payload={
                    "goal": {
                        "goal_name": goal["goal_name"],
                        "goal_amount": float(goal["goal_amount"]),
                        "target_months": target_months,
                        "start_date": goal["start_date"],
                    },
                    "plan": plan,
                },
                dedupe_key=dedupe_key,
            )
        )
    return [n for n in created if n]


def run_phase1_nudges(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict:
    run_date = today or date.today()
    predictive = generate_predictive_liquidity_nudges(
        usecase_id=usecase_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        today=run_date,
    )
    anomaly = generate_spending_anomaly_nudges(
        usecase_id=usecase_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        today=run_date,
    )
    goal_aware = generate_goal_aware_nudges(
        usecase_id=usecase_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        today=run_date,
    )
    return {
        "run_date": run_date.isoformat(),
        "account_scope": "account" if linked_account_id else "portfolio",
        "linked_account_id": linked_account_id or None,
        "predictive_liquidity_count": len(predictive),
        "spending_anomaly_count": len(anomaly),
        "goal_aware_count": len(goal_aware),
        "total_created": len(predictive) + len(anomaly) + len(goal_aware),
        "created": {
            "predictive_liquidity": predictive,
            "spending_anomaly": anomaly,
            "goal_aware": goal_aware,
        },
    }

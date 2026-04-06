import unittest
from datetime import date

from app.finance.engine import (
    category_expense,
    goal_based_savings_plan,
    income_vs_expense,
    safe_spend_today,
)


def _rows():
    return [
        {"id": 1, "txn_type": "credit", "amount": 10000, "txn_date": "2026-01-05", "narration": "salary"},
        {"id": 2, "txn_type": "debit", "amount": 1200, "txn_date": "2026-01-06", "narration": "transport"},
        {"id": 3, "txn_type": "debit", "amount": 800, "txn_date": "2026-01-07", "narration": "food"},
        {"id": 4, "txn_type": "credit", "amount": 9000, "txn_date": "2025-12-05", "narration": "salary"},
        {"id": 5, "txn_type": "debit", "amount": 2000, "txn_date": "2025-12-10", "narration": "transport"},
        {"id": 6, "txn_type": "credit", "amount": 9000, "txn_date": "2025-11-05", "narration": "salary"},
        {"id": 7, "txn_type": "debit", "amount": 3000, "txn_date": "2025-11-15", "narration": "rent"},
        {"id": 8, "txn_type": "credit", "amount": 10000, "txn_date": "2026-02-01", "narration": "salary"},
        {"id": 9, "txn_type": "debit", "amount": 1000, "txn_date": "2026-02-20", "narration": "food"},
    ]


class TestFinanceEngine(unittest.TestCase):
    def test_income_vs_expense_last_three_months(self):
        period = {"start": date(2025, 11, 1), "end": date(2026, 1, 31), "label": "last 3 months"}
        result = income_vs_expense(_rows(), period=period, today=date(2026, 2, 21))
        self.assertEqual(result["income"], 28000.0)
        self.assertEqual(result["expense"], 7000.0)
        self.assertEqual(result["savings"], 21000.0)

    def test_safe_spend_today(self):
        result = safe_spend_today(_rows(), today=date(2026, 2, 21))
        self.assertEqual(result["income_month_to_date"], 10000.0)
        self.assertEqual(result["expense_month_to_date"], 1000.0)
        self.assertEqual(result["remaining_budget"], 9000.0)
        self.assertGreater(result["safe_spend_today"], 0.0)

    def test_category_expense_this_week(self):
        period = {"start": date(2026, 2, 16), "end": date(2026, 2, 21), "label": "this week"}
        result = category_expense(_rows(), "food", period=period, today=date(2026, 2, 21))
        self.assertEqual(result["amount"], 1000.0)

    def test_goal_based_savings_plan(self):
        result = goal_based_savings_plan(_rows(), goal_amount=12000, target_months=6)
        self.assertEqual(result["required_monthly_savings"], 2000.0)
        self.assertIn("additional_monthly_needed", result)


if __name__ == "__main__":
    unittest.main()

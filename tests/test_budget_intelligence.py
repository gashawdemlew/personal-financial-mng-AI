import unittest

from app.finance.budget_intelligence import suggest_budget


def _tx(month: str, day: str, txn_type: str, amount: float, narration: str):
    return {
        "txn_date": f"{month}-{day}",
        "txn_type": txn_type,
        "amount": amount,
        "narration": narration,
    }


class TestBudgetIntelligence(unittest.TestCase):
    def test_prefers_six_month_window_when_available(self):
        tx = [
            _tx("2025-12", "05", "credit", 10000, "salary"),
            _tx("2025-12", "10", "debit", 3000, "rent"),
            _tx("2026-01", "05", "credit", 10000, "salary"),
            _tx("2026-01", "10", "debit", 2500, "food"),
            _tx("2026-02", "05", "credit", 10000, "salary"),
            _tx("2026-02", "11", "debit", 2200, "transport"),
            _tx("2026-03", "05", "credit", 10000, "salary"),
            _tx("2026-03", "12", "debit", 2400, "food"),
            _tx("2026-04", "05", "credit", 10000, "salary"),
            _tx("2026-04", "15", "debit", 2600, "rent"),
            _tx("2026-05", "05", "credit", 10000, "salary"),
            _tx("2026-05", "16", "debit", 2700, "transport"),
            _tx("2026-06", "05", "credit", 10000, "salary"),
            _tx("2026-06", "18", "debit", 2800, "food"),
        ]
        budgets = [
            {"budget_month": "2026-01", "total_budget": 7000, "category_allocations": {"food": 2000, "rent": 3000}},
            {"budget_month": "2026-02", "total_budget": 7100, "category_allocations": {"food": 2100, "rent": 3000}},
            {"budget_month": "2026-03", "total_budget": 7200, "category_allocations": {"food": 2200, "rent": 3000}},
            {"budget_month": "2026-04", "total_budget": 7300, "category_allocations": {"food": 2300, "rent": 3000}},
            {"budget_month": "2026-05", "total_budget": 7400, "category_allocations": {"food": 2400, "rent": 3000}},
            {"budget_month": "2026-06", "total_budget": 7500, "category_allocations": {"food": 2500, "rent": 3000}},
        ]
        result = suggest_budget(tx, budgets, target_month="2026-07")
        self.assertTrue(result["success"])
        self.assertEqual(result["window_used_months"], 6)
        self.assertEqual(result["mode_used"], "budget_plus_behavior")
        self.assertGreater(result["overall_monthly_budget_suggestion"], 0.0)

    def test_uses_three_month_when_six_not_available(self):
        tx = [
            _tx("2026-03", "05", "credit", 8000, "salary"),
            _tx("2026-03", "10", "debit", 3000, "food"),
            _tx("2026-04", "05", "credit", 8000, "salary"),
            _tx("2026-04", "10", "debit", 3200, "food"),
            _tx("2026-05", "05", "credit", 8000, "salary"),
            _tx("2026-05", "10", "debit", 3100, "transport"),
        ]
        result = suggest_budget(tx, [], target_month="2026-06")
        self.assertTrue(result["success"])
        self.assertEqual(result["window_used_months"], 3)
        self.assertEqual(result["mode_used"], "behavior_only")

    def test_uses_one_month_when_only_one_available(self):
        tx = [
            _tx("2026-05", "05", "credit", 9000, "salary"),
            _tx("2026-05", "08", "debit", 2000, "transport"),
            _tx("2026-05", "14", "debit", 1500, "food"),
        ]
        result = suggest_budget(tx, [], target_month="2026-06")
        self.assertTrue(result["success"])
        self.assertEqual(result["window_used_months"], 1)
        self.assertEqual(result["mode_used"], "behavior_only")

    def test_returns_insufficient_data_when_no_history(self):
        result = suggest_budget([], [], target_month="2026-06")
        self.assertFalse(result["success"])
        self.assertEqual(result["mode_used"], "insufficient_data")
        self.assertEqual(result["message"], "not enough data available")


if __name__ == "__main__":
    unittest.main()

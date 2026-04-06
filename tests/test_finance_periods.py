import unittest
from datetime import date

from app.finance.periods import parse_period


class TestFinancePeriods(unittest.TestCase):
    def test_parse_last_three_months(self):
        p = parse_period("show expenses for last 3 months", today=date(2026, 2, 21))
        self.assertIsNotNone(p)
        self.assertEqual(p["kind"], "last_n_months")
        self.assertEqual(str(p["start"]), "2025-11-01")
        self.assertEqual(str(p["end"]), "2026-01-31")

    def test_parse_this_week(self):
        p = parse_period("how much did i spend this week?", today=date(2026, 2, 21))
        self.assertIsNotNone(p)
        self.assertEqual(p["kind"], "this_week")
        self.assertEqual(str(p["start"]), "2026-02-16")
        self.assertEqual(str(p["end"]), "2026-02-21")


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.finance import repository
from app.finance.repository import (
    FinanceGoal,
    FinanceMonthlyBudget,
    FinanceTransaction,
    FinanceTransactionArchive,
)
from app.finance.router import _should_include_archive


class TestFinanceRetention(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                FinanceTransaction.__table__,
                FinanceTransactionArchive.__table__,
                FinanceGoal.__table__,
                FinanceMonthlyBudget.__table__,
            ],
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    @contextmanager
    def _patched_repo(self):
        with patch("app.finance.repository._session", side_effect=lambda: self.session_factory()), patch(
            "app.finance.repository.init_finance_db",
            return_value=None,
        ):
            yield

    def test_ingest_archives_transactions_older_than_six_months(self):
        transactions = [
            {
                "Transaction type": "debit",
                "Transaction amount": 1200,
                "Balance": 5000,
                "transaction date": "2025-08-01",
                "transaction narration": "transport",
            },
            {
                "Transaction type": "credit",
                "Transaction amount": 10000,
                "Balance": 15000,
                "transaction date": "2026-03-20",
                "transaction narration": "salary",
            },
        ]

        with self._patched_repo():
            inserted, failed, retention = repository.ingest_transactions(
                "financial-guide",
                "user_1",
                transactions,
                today=date(2026, 3, 23),
            )

        self.assertEqual(inserted, 2)
        self.assertEqual(failed, [])
        self.assertEqual(retention["cutoff_date"], "2025-09-23")
        self.assertEqual(retention["archived_count"], 1)
        self.assertEqual(retention["deleted_count"], 1)

        with self.session_factory() as session:
            active_rows = session.execute(
                select(FinanceTransaction).order_by(FinanceTransaction.txn_date.asc())
            ).scalars().all()
            archive_rows = session.execute(
                select(FinanceTransactionArchive).order_by(FinanceTransactionArchive.txn_date.asc())
            ).scalars().all()

        self.assertEqual(len(active_rows), 1)
        self.assertEqual(active_rows[0].txn_date, "2026-03-20")
        self.assertEqual(len(archive_rows), 1)
        self.assertEqual(archive_rows[0].txn_date, "2025-08-01")

    def test_ingest_keeps_recent_transactions_active(self):
        transactions = [
            {
                "Transaction type": "debit",
                "Transaction amount": 900,
                "Balance": 10000,
                "transaction date": "2025-11-01",
                "transaction narration": "food",
            }
        ]

        with self._patched_repo():
            inserted, failed, retention = repository.ingest_transactions(
                "financial-guide",
                "user_1",
                transactions,
                today=date(2026, 3, 23),
            )

        self.assertEqual(inserted, 1)
        self.assertEqual(failed, [])
        self.assertEqual(retention["archived_count"], 0)
        self.assertEqual(retention["deleted_count"], 0)

        with self.session_factory() as session:
            active_count = session.execute(select(FinanceTransaction)).scalars().all()
            archive_count = session.execute(select(FinanceTransactionArchive)).scalars().all()

        self.assertEqual(len(active_count), 1)
        self.assertEqual(len(archive_count), 0)

    def test_transaction_storage_stats_reports_active_and_archived_counts(self):
        with self._patched_repo():
            repository.ingest_transactions(
                "financial-guide",
                "user_1",
                [
                    {
                        "Transaction type": "debit",
                        "Transaction amount": 1200,
                        "Balance": 5000,
                        "transaction date": "2025-08-01",
                        "transaction narration": "transport",
                    },
                    {
                        "Transaction type": "credit",
                        "Transaction amount": 10000,
                        "Balance": 15000,
                        "transaction date": "2026-03-20",
                        "transaction narration": "salary",
                    },
                ],
                today=date(2026, 3, 23),
            )
            stats = repository.transaction_storage_stats("financial-guide", user_id="user_1")

        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["user_id"], "user_1")
        self.assertEqual(stats[0]["active_count"], 1)
        self.assertEqual(stats[0]["archived_count"], 1)

    def test_ingest_preserves_linked_account_id_and_filters_by_account(self):
        transactions = [
            {
                "Transaction type": "debit",
                "Transaction amount": 400,
                "Balance": 4600,
                "transaction date": "2026-03-10",
                "transaction narration": "food",
                "linked_account_id": "acct_1",
            },
            {
                "Transaction type": "debit",
                "Transaction amount": 250,
                "Balance": 4350,
                "transaction date": "2026-03-12",
                "transaction narration": "transport",
                "linked_account_id": "acct_2",
            },
        ]

        with self._patched_repo():
            repository.ingest_transactions("financial-guide", "user_1", transactions, today=date(2026, 3, 23))
            acct_1_rows = repository.list_all_transactions("financial-guide", "user_1", linked_account_id="acct_1")
            acct_2_rows = repository.list_all_transactions("financial-guide", "user_1", linked_account_id="acct_2")
            all_rows = repository.list_all_transactions("financial-guide", "user_1")
            accounts = repository.list_linked_accounts("financial-guide", "user_1")

        self.assertEqual(len(acct_1_rows), 1)
        self.assertEqual(acct_1_rows[0]["linked_account_id"], "acct_1")
        self.assertEqual(len(acct_2_rows), 1)
        self.assertEqual(acct_2_rows[0]["linked_account_id"], "acct_2")
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(accounts, ["acct_1", "acct_2"])

    def test_goals_and_budgets_can_be_scoped_per_linked_account(self):
        with self._patched_repo():
            portfolio_goal = repository.upsert_goal(
                "financial-guide",
                "user_1",
                None,
                "emergency fund",
                10000,
                6,
            )
            account_goal = repository.upsert_goal(
                "financial-guide",
                "user_1",
                "acct_1",
                "emergency fund",
                5000,
                4,
            )
            portfolio_budget = repository.upsert_monthly_budget(
                "financial-guide",
                "user_1",
                None,
                "2026-03",
                6000,
                "ETB",
                {"food": 2000},
            )
            account_budget = repository.upsert_monthly_budget(
                "financial-guide",
                "user_1",
                "acct_1",
                "2026-03",
                3000,
                "ETB",
                {"food": 1000},
            )
            portfolio_goals = repository.list_goals_for_scope("financial-guide", "user_1", linked_account_id=None)
            account_goals = repository.list_goals_for_scope("financial-guide", "user_1", linked_account_id="acct_1")
            portfolio_budgets = repository.list_monthly_budgets("financial-guide", "user_1", linked_account_id=None)
            account_budgets = repository.list_monthly_budgets("financial-guide", "user_1", linked_account_id="acct_1")

        self.assertIsNone(portfolio_goal["linked_account_id"])
        self.assertEqual(account_goal["linked_account_id"], "acct_1")
        self.assertIsNone(portfolio_budget["linked_account_id"])
        self.assertEqual(account_budget["linked_account_id"], "acct_1")
        self.assertEqual(len(portfolio_goals), 1)
        self.assertEqual(len(account_goals), 1)
        self.assertEqual(len(portfolio_budgets), 1)
        self.assertEqual(len(account_budgets), 1)

    def test_yearly_questions_request_archive(self):
        period = {"start": date(2025, 1, 1), "end": date(2025, 12, 31), "months": 12}
        self.assertTrue(_should_include_archive("Show my annual spending", period))
        self.assertFalse(_should_include_archive("Show my food expense this month", {"months": 1}))


if __name__ == "__main__":
    unittest.main()

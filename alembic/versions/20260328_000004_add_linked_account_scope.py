"""add linked account scope to finance tables

Revision ID: 20260328_000004
Revises: 20260323_000003
Create Date: 2026-03-28 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260328_000004"
down_revision = "20260323_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finance_transactions", sa.Column("linked_account_id", sa.String(length=255), nullable=True))
    op.create_index("ix_finance_transactions_linked_account_id", "finance_transactions", ["linked_account_id"])

    op.add_column("finance_transactions_archive", sa.Column("linked_account_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_finance_transactions_archive_linked_account_id",
        "finance_transactions_archive",
        ["linked_account_id"],
    )

    op.add_column("finance_goals", sa.Column("linked_account_id", sa.String(length=255), nullable=True))
    op.create_index("ix_finance_goals_linked_account_id", "finance_goals", ["linked_account_id"])
    op.drop_constraint("uq_finance_goals_scope", "finance_goals", type_="unique")
    op.create_unique_constraint(
        "uq_finance_goals_scope",
        "finance_goals",
        ["usecase_id", "user_id", "linked_account_id", "goal_name"],
    )

    op.add_column("finance_nudges", sa.Column("linked_account_id", sa.String(length=255), nullable=True))
    op.create_index("ix_finance_nudges_linked_account_id", "finance_nudges", ["linked_account_id"])
    op.drop_constraint("uq_finance_nudges_scope", "finance_nudges", type_="unique")
    op.create_unique_constraint(
        "uq_finance_nudges_scope",
        "finance_nudges",
        ["usecase_id", "user_id", "linked_account_id", "dedupe_key"],
    )

    op.add_column("finance_monthly_budgets", sa.Column("linked_account_id", sa.String(length=255), nullable=True))
    op.create_index("ix_finance_monthly_budgets_linked_account_id", "finance_monthly_budgets", ["linked_account_id"])
    op.drop_constraint("uq_finance_budgets_scope", "finance_monthly_budgets", type_="unique")
    op.create_unique_constraint(
        "uq_finance_budgets_scope",
        "finance_monthly_budgets",
        ["usecase_id", "user_id", "linked_account_id", "budget_month"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_finance_budgets_scope", "finance_monthly_budgets", type_="unique")
    op.create_unique_constraint(
        "uq_finance_budgets_scope",
        "finance_monthly_budgets",
        ["usecase_id", "user_id", "budget_month"],
    )
    op.drop_index("ix_finance_monthly_budgets_linked_account_id", table_name="finance_monthly_budgets")
    op.drop_column("finance_monthly_budgets", "linked_account_id")

    op.drop_constraint("uq_finance_nudges_scope", "finance_nudges", type_="unique")
    op.create_unique_constraint(
        "uq_finance_nudges_scope",
        "finance_nudges",
        ["usecase_id", "user_id", "dedupe_key"],
    )
    op.drop_index("ix_finance_nudges_linked_account_id", table_name="finance_nudges")
    op.drop_column("finance_nudges", "linked_account_id")

    op.drop_constraint("uq_finance_goals_scope", "finance_goals", type_="unique")
    op.create_unique_constraint(
        "uq_finance_goals_scope",
        "finance_goals",
        ["usecase_id", "user_id", "goal_name"],
    )
    op.drop_index("ix_finance_goals_linked_account_id", table_name="finance_goals")
    op.drop_column("finance_goals", "linked_account_id")

    op.drop_index("ix_finance_transactions_archive_linked_account_id", table_name="finance_transactions_archive")
    op.drop_column("finance_transactions_archive", "linked_account_id")

    op.drop_index("ix_finance_transactions_linked_account_id", table_name="finance_transactions")
    op.drop_column("finance_transactions", "linked_account_id")

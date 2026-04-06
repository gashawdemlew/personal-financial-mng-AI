"""initial chat and finance schema

Revision ID: 20260322_000001
Revises:
Create Date: 2026-03-22 00:00:01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_messages_usecase_id", "chat_messages", ["usecase_id"])
    op.create_index("ix_chat_messages_chat_id", "chat_messages", ["chat_id"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("last_message_preview", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usecase_id", "chat_id", name="uq_chat_sessions_scope"),
    )
    op.create_index("ix_chat_sessions_usecase_id", "chat_sessions", ["usecase_id"])
    op.create_index("ix_chat_sessions_chat_id", "chat_sessions", ["chat_id"])

    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("txn_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("txn_date", sa.String(length=32), nullable=False),
        sa.Column("narration", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_finance_transactions_usecase_id", "finance_transactions", ["usecase_id"])
    op.create_index("ix_finance_transactions_user_id", "finance_transactions", ["user_id"])
    op.create_index("ix_finance_transactions_txn_date", "finance_transactions", ["txn_date"])

    op.create_table(
        "finance_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_finance_chat_messages_usecase_id", "finance_chat_messages", ["usecase_id"])
    op.create_index("ix_finance_chat_messages_user_id", "finance_chat_messages", ["user_id"])
    op.create_index("ix_finance_chat_messages_chat_id", "finance_chat_messages", ["chat_id"])

    op.create_table(
        "finance_goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("goal_name", sa.String(length=255), nullable=False),
        sa.Column("goal_amount", sa.Float(), nullable=False),
        sa.Column("target_months", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usecase_id", "user_id", "goal_name", name="uq_finance_goals_scope"),
    )
    op.create_index("ix_finance_goals_usecase_id", "finance_goals", ["usecase_id"])
    op.create_index("ix_finance_goals_user_id", "finance_goals", ["user_id"])
    op.create_index("ix_finance_goals_status", "finance_goals", ["status"])

    op.create_table(
        "finance_nudges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("nudge_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("acknowledged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usecase_id", "user_id", "dedupe_key", name="uq_finance_nudges_scope"),
    )
    op.create_index("ix_finance_nudges_usecase_id", "finance_nudges", ["usecase_id"])
    op.create_index("ix_finance_nudges_user_id", "finance_nudges", ["user_id"])
    op.create_index("ix_finance_nudges_acknowledged", "finance_nudges", ["acknowledged"])

    op.create_table(
        "finance_monthly_budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("budget_month", sa.String(length=16), nullable=False),
        sa.Column("total_budget", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=32), nullable=False),
        sa.Column("category_allocations_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usecase_id", "user_id", "budget_month", name="uq_finance_budgets_scope"),
    )
    op.create_index("ix_finance_monthly_budgets_usecase_id", "finance_monthly_budgets", ["usecase_id"])
    op.create_index("ix_finance_monthly_budgets_user_id", "finance_monthly_budgets", ["user_id"])
    op.create_index("ix_finance_monthly_budgets_budget_month", "finance_monthly_budgets", ["budget_month"])


def downgrade() -> None:
    op.drop_index("ix_finance_monthly_budgets_budget_month", table_name="finance_monthly_budgets")
    op.drop_index("ix_finance_monthly_budgets_user_id", table_name="finance_monthly_budgets")
    op.drop_index("ix_finance_monthly_budgets_usecase_id", table_name="finance_monthly_budgets")
    op.drop_table("finance_monthly_budgets")

    op.drop_index("ix_finance_nudges_acknowledged", table_name="finance_nudges")
    op.drop_index("ix_finance_nudges_user_id", table_name="finance_nudges")
    op.drop_index("ix_finance_nudges_usecase_id", table_name="finance_nudges")
    op.drop_table("finance_nudges")

    op.drop_index("ix_finance_goals_status", table_name="finance_goals")
    op.drop_index("ix_finance_goals_user_id", table_name="finance_goals")
    op.drop_index("ix_finance_goals_usecase_id", table_name="finance_goals")
    op.drop_table("finance_goals")

    op.drop_index("ix_finance_chat_messages_chat_id", table_name="finance_chat_messages")
    op.drop_index("ix_finance_chat_messages_user_id", table_name="finance_chat_messages")
    op.drop_index("ix_finance_chat_messages_usecase_id", table_name="finance_chat_messages")
    op.drop_table("finance_chat_messages")

    op.drop_index("ix_finance_transactions_txn_date", table_name="finance_transactions")
    op.drop_index("ix_finance_transactions_user_id", table_name="finance_transactions")
    op.drop_index("ix_finance_transactions_usecase_id", table_name="finance_transactions")
    op.drop_table("finance_transactions")

    op.drop_index("ix_chat_sessions_chat_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_usecase_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("ix_chat_messages_chat_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_usecase_id", table_name="chat_messages")
    op.drop_table("chat_messages")

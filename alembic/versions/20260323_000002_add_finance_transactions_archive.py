"""add finance transactions archive

Revision ID: 20260323_000002
Revises: 20260322_000001
Create Date: 2026-03-23 00:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000002"
down_revision = "20260322_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_transactions_archive",
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
    op.create_index(
        "ix_finance_transactions_archive_usecase_id",
        "finance_transactions_archive",
        ["usecase_id"],
    )
    op.create_index(
        "ix_finance_transactions_archive_user_id",
        "finance_transactions_archive",
        ["user_id"],
    )
    op.create_index(
        "ix_finance_transactions_archive_txn_date",
        "finance_transactions_archive",
        ["txn_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_finance_transactions_archive_txn_date", table_name="finance_transactions_archive")
    op.drop_index("ix_finance_transactions_archive_user_id", table_name="finance_transactions_archive")
    op.drop_index("ix_finance_transactions_archive_usecase_id", table_name="finance_transactions_archive")
    op.drop_table("finance_transactions_archive")

"""add chat quota config

Revision ID: 20260323_000003
Revises: 20260323_000002
Create Date: 2026-03-23 16:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000003"
down_revision = "20260323_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_quota_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usecase_id", sa.String(length=255), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("usecase_id", name="uq_chat_quota_usecase"),
    )
    op.create_index("ix_chat_quota_config_usecase_id", "chat_quota_config", ["usecase_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_quota_config_usecase_id", table_name="chat_quota_config")
    op.drop_table("chat_quota_config")

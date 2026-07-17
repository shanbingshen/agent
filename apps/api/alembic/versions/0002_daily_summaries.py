"""Add persisted AI daily summaries."""

import sqlalchemy as sa
from alembic import op

revision = "0002_daily_summaries"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("device_scope", sa.JSON(), nullable=False),
        sa.Column("statistics", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("generated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_summaries_summary_date", "daily_summaries", ["summary_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_summaries_summary_date", table_name="daily_summaries")
    op.drop_table("daily_summaries")

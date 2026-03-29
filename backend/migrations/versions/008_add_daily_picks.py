"""Add daily_picks table and is_top_pick to calibration_log

Revision ID: 008
Revises: 007
Create Date: 2026-03-29

daily_picks: persists the day's top Veredictos del día — mirrors frontend pickBestBets().
is_top_pick: marks whether a CalibrationLog entry was the day's top pick (full unit weight).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_top_pick to calibration_log
    op.add_column(
        "calibration_log",
        sa.Column("is_top_pick", sa.Boolean(), nullable=True),
    )

    # Create daily_picks table
    op.create_table(
        "daily_picks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matches.id"),
            nullable=False,
        ),
        sa.Column("pick_type", sa.String(10), nullable=False),   # "value" | "strength"
        sa.Column("signal_side", sa.String(10), nullable=True),  # "home" | "draw" | "away"
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_unique_constraint(
        "uq_daily_picks_date_type",
        "daily_picks",
        ["date", "pick_type"],
    )

    op.create_index(
        "ix_daily_picks_date",
        "daily_picks",
        ["date"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_picks_date", table_name="daily_picks")
    op.drop_constraint("uq_daily_picks_date_type", "daily_picks", type_="unique")
    op.drop_table("daily_picks")
    op.drop_column("calibration_log", "is_top_pick")

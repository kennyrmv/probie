"""Add signal_source and lineup_confirmed to calibration_log

Revision ID: 007
Revises: 006
Create Date: 2026-03-29

signal_source: "edge" (IA confirmó ineficiencia de mercado) | "fuerza" (IA detectó dominancia cualitativa)
lineup_confirmed: True if analysis was run with confirmed XI data
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calibration_log",
        sa.Column("signal_source", sa.String(10), nullable=True),
    )
    op.add_column(
        "calibration_log",
        sa.Column("lineup_confirmed", sa.Boolean(), nullable=True),
    )
    # Clear old records — they were based on model value tiers, not AI signals
    op.execute("DELETE FROM calibration_log")


def downgrade() -> None:
    op.drop_column("calibration_log", "lineup_confirmed")
    op.drop_column("calibration_log", "signal_source")

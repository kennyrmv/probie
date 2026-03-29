"""Add CLV tracking fields to calibration_log

Revision ID: 006
Revises: 005
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calibration_log", sa.Column("signal_outcome", sa.String(10), nullable=True))
    op.add_column("calibration_log", sa.Column("signal_tier", sa.String(10), nullable=True))
    op.add_column("calibration_log", sa.Column("model_prob", sa.Float(), nullable=True))
    op.add_column("calibration_log", sa.Column("entry_poly_prob", sa.Float(), nullable=True))
    op.add_column("calibration_log", sa.Column("closing_poly_prob", sa.Float(), nullable=True))
    op.add_column("calibration_log", sa.Column("clv_pp", sa.Float(), nullable=True))
    op.create_index(
        "ix_calibration_log_prediction_id",
        "calibration_log",
        ["prediction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_calibration_log_prediction_id", table_name="calibration_log")
    op.drop_column("calibration_log", "clv_pp")
    op.drop_column("calibration_log", "closing_poly_prob")
    op.drop_column("calibration_log", "entry_poly_prob")
    op.drop_column("calibration_log", "model_prob")
    op.drop_column("calibration_log", "signal_tier")
    op.drop_column("calibration_log", "signal_outcome")

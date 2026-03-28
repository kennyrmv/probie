"""Add match result fields (home_score, away_score, match_status)

Revision ID: 005
Revises: 004
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("home_score", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("away_score", sa.Integer(), nullable=True))
    op.add_column(
        "matches",
        sa.Column(
            "match_status",
            sa.String(20),
            nullable=False,
            server_default="scheduled",
        ),
    )


def downgrade() -> None:
    op.drop_column("matches", "match_status")
    op.drop_column("matches", "away_score")
    op.drop_column("matches", "home_score")

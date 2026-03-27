"""Initial schema — 5 tables for EdgeFút

Revision ID: 001_initial
Revises:
Create Date: 2026-03-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── matches
    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("home_team", sa.String(100), nullable=False),
        sa.Column("away_team", sa.String(100), nullable=False),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("competition", sa.String(100), nullable=False),
        sa.Column("polymarket_neg_risk_market_id", sa.String(200), nullable=True),
        sa.Column("polymarket_event_slug", sa.String(200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_kickoff_utc", "matches", ["kickoff_utc"])
    op.create_index(
        "ix_matches_polymarket_neg_risk_market_id",
        "matches",
        ["polymarket_neg_risk_market_id"],
    )

    # ── predictions
    op.create_table(
        "predictions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_home_prob", sa.Float, nullable=False),
        sa.Column("model_draw_prob", sa.Float, nullable=False),
        sa.Column("model_away_prob", sa.Float, nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── market_snapshots (append-only)
    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("polymarket_market_id", sa.String(200), nullable=True),
        sa.Column("polymarket_prob", sa.Float, nullable=False),
        sa.Column("delta_pp", sa.Float, nullable=False),
        sa.Column("value_tier", sa.String(10), nullable=False),
        sa.Column(
            "snapshotted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_snapshots_match_outcome_time",
        "market_snapshots",
        ["match_id", "outcome", "snapshotted_at"],
    )

    # ── historical_matches
    op.create_table(
        "historical_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("home_team_id", sa.Integer, nullable=False),
        sa.Column("away_team_id", sa.Integer, nullable=False),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("home_goals", sa.Integer, nullable=False),
        sa.Column("away_goals", sa.Integer, nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("competition", sa.String(50), nullable=False),
        sa.Column("season", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_competition_date",
        "historical_matches",
        ["competition", "date"],
    )

    # ── calibration_log
    op.create_table(
        "calibration_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prediction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actual_result", sa.String(10), nullable=False),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("calibration_log")
    op.drop_index("ix_historical_competition_date", table_name="historical_matches")
    op.drop_table("historical_matches")
    op.drop_index("ix_market_snapshots_match_outcome_time", table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_table("predictions")
    op.drop_index("ix_matches_polymarket_neg_risk_market_id", table_name="matches")
    op.drop_index("ix_matches_kickoff_utc", table_name="matches")
    op.drop_table("matches")

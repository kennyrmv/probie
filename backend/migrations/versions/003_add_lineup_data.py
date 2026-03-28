"""add lineup_data to matches

Revision ID: 003
Revises: 002
Create Date: 2026-03-28

Adds lineup_data JSONB column to matches. Populated by SofaScore resolver
when a confirmed lineup is available (typically 1h before kickoff).

Schema:
{
  "source": "sofascore",
  "fetched_at": "2026-03-28T15:00:00+00:00",
  "sofascore_event_id": 12345,
  "home_formation": "4-3-3",
  "away_formation": "4-2-3-1",
  "home_starters": [{"name": str, "position": str, "jersey": str}],
  "home_subs": [...],
  "away_starters": [...],
  "away_subs": [...],
  "home_missing": [{"name": str, "reason": str, "type": str}],
  "away_missing": [...]
}
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('matches', sa.Column('lineup_data', JSONB(), nullable=True))


def downgrade():
    op.drop_column('matches', 'lineup_data')

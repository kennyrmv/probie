"""add analysis_data to matches

Revision ID: 004
Revises: 003
Create Date: 2026-03-28

Adds analysis_data JSONB column. Populated on demand by Claude agent
when user explicitly requests match analysis.

Schema:
{
  "source": "claude+duckduckgo",
  "analyzed_at": "2026-03-28T15:00:00+00:00",
  "home_lineup": ["name", ...],
  "away_lineup": ["name", ...],
  "home_missing": [{"name": str, "reason": str}],
  "away_missing": [{"name": str, "reason": str}],
  "form_home": "V-V-E-V-D, 2.2 pts/j",
  "form_away": "...",
  "context": "narrative context string",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "lineup_confirmed": false,
  "confidence": "alta|media|baja",
  "sources": ["url1", "url2"]
}
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('matches', sa.Column('analysis_data', JSONB(), nullable=True))


def downgrade():
    op.drop_column('matches', 'analysis_data')

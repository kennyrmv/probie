"""add home_squad and away_squad to matches

Revision ID: 002
Revises: 001
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '002'
down_revision = '001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('matches', sa.Column('home_squad', JSONB(), nullable=True))
    op.add_column('matches', sa.Column('away_squad', JSONB(), nullable=True))

def downgrade():
    op.drop_column('matches', 'away_squad')
    op.drop_column('matches', 'home_squad')

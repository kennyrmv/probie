"""
SQLAlchemy ORM models for EdgeFút.
All schema changes go through Alembic migrations — never ALTER manually.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, String, Text, Integer
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_kickoff_utc", "kickoff_utc"),
        Index("ix_matches_polymarket_neg_risk_market_id", "polymarket_neg_risk_market_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    kickoff_utc = Column(DateTime(timezone=True), nullable=False)
    competition = Column(String(100), nullable=False)
    polymarket_neg_risk_market_id = Column(String(200), nullable=True)
    polymarket_event_slug = Column(String(200), nullable=True)
    home_squad = Column(JSONB, nullable=True)   # [{name, position, nationality}]
    away_squad = Column(JSONB, nullable=True)
    lineup_data = Column(JSONB, nullable=True)   # confirmed lineups from API-Football
    analysis_data = Column(JSONB, nullable=True) # on-demand AI analysis (Claude+web)
    home_score = Column(Integer, nullable=True)  # final result (populated post-match)
    away_score = Column(Integer, nullable=True)
    match_status = Column(String(20), nullable=False, default="scheduled")  # scheduled|live|finished

    predictions = relationship("Prediction", back_populates="match", cascade="all, delete-orphan")
    market_snapshots = relationship("MarketSnapshot", back_populates="match", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Match {self.home_team} vs {self.away_team} ({self.kickoff_utc})>"


class Prediction(Base):
    """
    Model outputs — immutable once created per match run.
    One row per match per model execution (typically once per day).
    """
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False)
    model_home_prob = Column(Float, nullable=False)
    model_draw_prob = Column(Float, nullable=False)
    model_away_prob = Column(Float, nullable=False)
    reasons = Column(JSONB, nullable=True)  # [{type, value, direction, text}]
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    match = relationship("Match", back_populates="predictions")

    def __repr__(self) -> str:
        return (
            f"<Prediction match={self.match_id} "
            f"H={self.model_home_prob:.2f} D={self.model_draw_prob:.2f} A={self.model_away_prob:.2f}>"
        )


class MarketSnapshot(Base):
    """
    Polymarket odds snapshots — append-only, one row per outcome per 15-min refresh.
    Enables tracking how odds evolved relative to our prediction.
    NEVER UPDATE existing rows. Only INSERT.
    """
    __tablename__ = "market_snapshots"
    __table_args__ = (
        Index("ix_market_snapshots_match_outcome_time", "match_id", "outcome", "snapshotted_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False)
    outcome = Column(String(10), nullable=False)  # "home" | "draw" | "away"
    polymarket_market_id = Column(String(200), nullable=True)
    polymarket_prob = Column(Float, nullable=False)  # json.loads(outcomePrices)[0]
    delta_pp = Column(Float, nullable=False)          # model_prob - polymarket_prob
    value_tier = Column(String(10), nullable=False)   # "high" | "mid" | "none"
    snapshotted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    match = relationship("Match", back_populates="market_snapshots")

    def __repr__(self) -> str:
        return (
            f"<MarketSnapshot match={self.match_id} outcome={self.outcome} "
            f"poly={self.polymarket_prob:.2f} delta={self.delta_pp:+.1f}pp {self.value_tier}>"
        )


class HistoricalMatch(Base):
    """
    Seeded from football-data.org. Used by Dixon-Coles for parameter estimation.
    """
    __tablename__ = "historical_matches"
    __table_args__ = (
        Index("ix_historical_competition_date", "competition", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    home_team_id = Column(Integer, nullable=False)
    away_team_id = Column(Integer, nullable=False)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)
    home_goals = Column(Integer, nullable=False)
    away_goals = Column(Integer, nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)
    competition = Column(String(50), nullable=False)
    season = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<HistoricalMatch {self.home_team_name} {self.home_goals}-{self.away_goals} "
            f"{self.away_team_name} ({self.date.date()})>"
        )


class CalibrationLog(Base):
    """
    Tracks prediction accuracy over time.
    Each row: one prediction + actual result after the match finishes.
    """
    __tablename__ = "calibration_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id = Column(UUID(as_uuid=True), ForeignKey("predictions.id"), nullable=False)
    actual_result = Column(String(10), nullable=False)  # "home" | "draw" | "away"
    resolved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    prediction = relationship("Prediction")

    def __repr__(self) -> str:
        return f"<CalibrationLog prediction={self.prediction_id} actual={self.actual_result}>"

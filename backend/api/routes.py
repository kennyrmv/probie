"""
FastAPI routes for EdgeFút.

Routes:
  GET /api/matches/today  — today's matches with model probs + delta
  GET /health             — Railway health check
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import check_db_connection, get_db
from models import Match, MarketSnapshot, Prediction

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
def health_check():
    """
    Railway health check endpoint.
    Returns 200 {"status": "ok", "db": "connected"} when healthy.
    Returns 503 when DB is unreachable.
    """
    db_ok = check_db_connection()
    if not db_ok:
        raise HTTPException(status_code=503, detail={"status": "degraded", "db": "unavailable"})
    return {"status": "ok", "db": "connected"}


# ─────────────────────────────────────────────────────────────────────────────
# Matches today
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/matches/today")
def get_matches_today(db: Session = Depends(get_db)):
    """
    Return today's matches with model probabilities and market deltas.

    Response sorted by best_delta_pp descending.
    Each match shows all 3 outcomes (home/draw/away).
    Empty list if no matches today.

    Raises 500 if DB unavailable.
    """
    try:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_end = today_start.replace(hour=23, minute=59, second=59)

        today_matches = (
            db.query(Match)
            .filter(
                Match.kickoff_utc >= today_start,
                Match.kickoff_utc <= today_end,
            )
            .all()
        )

        if not today_matches:
            return []

        result = []
        for match in today_matches:
            match_data = _build_match_response(db, match)
            if match_data:
                result.append(match_data)

        # Sort by best_delta_pp descending
        result.sort(key=lambda x: x["best_delta_pp"] or 0, reverse=True)
        return result

    except Exception as exc:
        logger.error("GET /api/matches/today failed: %s", exc)
        raise HTTPException(status_code=500, detail="DB unavailable")


def _build_match_response(db: Session, match: Match) -> dict | None:
    """Build the full response dict for a single match."""
    # Get the latest prediction
    prediction = (
        db.query(Prediction)
        .filter(Prediction.match_id == match.id)
        .order_by(desc(Prediction.created_at))
        .first()
    )

    if not prediction:
        return None

    # Get the latest market snapshot per outcome (subquery: max snapshotted_at per outcome)
    outcomes_data = []
    best_delta = None
    best_tier = "none"

    for outcome in ("home", "draw", "away"):
        snapshot = (
            db.query(MarketSnapshot)
            .filter(
                MarketSnapshot.match_id == match.id,
                MarketSnapshot.outcome == outcome,
            )
            .order_by(desc(MarketSnapshot.snapshotted_at))
            .first()
        )

        model_prob = {
            "home": prediction.model_home_prob,
            "draw": prediction.model_draw_prob,
            "away": prediction.model_away_prob,
        }[outcome]

        if snapshot:
            delta_pp = snapshot.delta_pp
            value_tier = snapshot.value_tier
            polymarket_prob = snapshot.polymarket_prob
            polymarket_url = _build_polymarket_url(match, outcome)
        else:
            # Polymarket resolver failed for this outcome
            delta_pp = None
            value_tier = None
            polymarket_prob = None
            polymarket_url = None

        outcome_obj = {
            "outcome": outcome,
            "label": _outcome_label(outcome, match.home_team, match.away_team),
            "polymarket_url": polymarket_url,
            "polymarket_prob": polymarket_prob,
            "model_prob": round(model_prob, 4),
            "delta_pp": round(delta_pp, 1) if delta_pp is not None else None,
            "value_tier": value_tier,
        }
        outcomes_data.append(outcome_obj)

        if delta_pp is not None and (best_delta is None or delta_pp > best_delta):
            best_delta = delta_pp
            best_tier = value_tier or "none"

    return {
        "id": str(match.id),
        "home_team": match.home_team,
        "away_team": match.away_team,
        "kickoff": match.kickoff_utc.isoformat(),
        "competition": match.competition,
        "outcomes": outcomes_data,
        "best_value_tier": best_tier,
        "best_delta_pp": round(best_delta, 1) if best_delta is not None else None,
        "reasons": prediction.reasons or [],
    }


def _outcome_label(outcome: str, home_team: str, away_team: str) -> str:
    if outcome == "home":
        return f"{home_team} gana"
    elif outcome == "draw":
        return "Empate"
    else:
        return f"{away_team} gana"


def _build_polymarket_url(match: Match, outcome: str) -> str | None:
    """Build a Polymarket URL from event slug."""
    slug = match.polymarket_event_slug
    if not slug:
        return None
    return f"https://polymarket.com/event/{slug}"

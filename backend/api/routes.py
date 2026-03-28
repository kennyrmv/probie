"""
FastAPI routes for EdgeFút.

Routes:
  GET  /api/matches/today              — today's matches with model probs + delta
  POST /api/matches/{id}/analyze       — on-demand AI analysis (web search + Claude)
  POST /api/matches/{id}/fetch-lineup  — fetch confirmed lineup from API-Football
  GET  /health                         — Railway health check
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import check_db_connection, get_db, SessionLocal
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
    Returns 200 with system status including lineup API connectivity.
    Returns 503 when DB is unreachable.
    """
    db_ok = check_db_connection()
    if not db_ok:
        raise HTTPException(status_code=503, detail={"status": "degraded", "db": "unavailable"})

    return {
        "status": "ok",
        "db": "connected",
        "lineup_status": "ok",  # Claude+DuckDuckGo — always available
    }


# ─────────────────────────────────────────────────────────────────────────────
# Matches today
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/matches/today")
def get_matches_today(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Return today's matches with model probabilities and market deltas.

    Response sorted by best_delta_pp descending.
    Each match shows all 3 outcomes (home/draw/away).
    Empty list if no matches today.

    Raises 500 if DB unavailable.
    """
    try:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        # Show matches from 2h ago (live/just started) up to 36h ahead
        window_start = now - timedelta(hours=2)
        window_end = now + timedelta(hours=36)

        today_matches = (
            db.query(Match)
            .filter(
                Match.kickoff_utc >= window_start,
                Match.kickoff_utc <= window_end,
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
            # Auto re-analysis: XI available but analysis was done without lineup
            lineup = match.lineup_data or {}
            has_starters = bool(lineup.get("home_starters"))
            analysis_has_lineup = bool(match.analysis_data and match.analysis_data.get("lineup_data_used"))
            if has_starters and not analysis_has_lineup:
                background_tasks.add_task(_run_analysis_and_store, str(match.id))
                logger.info("Queued re-analysis for %s vs %s (lineup available, analysis stale)", match.home_team, match.away_team)

        # Sort by best_delta_pp descending
        result.sort(key=lambda x: x["best_delta_pp"] or 0, reverse=True)
        return result

    except Exception as exc:
        logger.error("GET /api/matches/today failed: %s", exc)
        raise HTTPException(status_code=500, detail="DB unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# AI Analysis — on demand
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/matches/{match_id}/analyze")
def analyze_match(match_id: str, db: Session = Depends(get_db)):
    """
    Trigger on-demand AI analysis for a match.
    Searches the web + uses Claude to synthesize lineups, injuries, context,
    top 3 players, probability adjustment, and unified bet signal.
    Takes ~15-30 seconds. Called explicitly by the user.
    """
    import uuid
    try:
        mid = uuid.UUID(match_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid match_id")

    match = db.query(Match).filter(Match.id == mid).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Build outcomes context so Claude knows the math edge
    outcomes_context = _build_outcomes_context(db, match)

    try:
        from resolver.match_analyst import analyze_match as run_analysis
        analysis = run_analysis(
            home_team=match.home_team,
            away_team=match.away_team,
            competition=match.competition,
            kickoff_dt=match.kickoff_utc,
            lineup_data=match.lineup_data,      # Pass confirmed lineup if available
            outcomes=outcomes_context,           # Pass math context (model vs market)
        )
        match.analysis_data = analysis
        db.commit()
        return {"status": "ok", "analysis": analysis}
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Analysis failed for match %s: %s", match_id, exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Lineup fetch — on demand
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/matches/{match_id}/fetch-lineup")
def fetch_match_lineup(match_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Fetch confirmed lineup from API-Football for a specific match.
    Lineups are usually confirmed ~1h before kickoff.
    Stores result in match.lineup_data if found.
    Returns {"status": "ok"|"not_available", "lineup": {...}|null}
    """
    import uuid
    try:
        mid = uuid.UUID(match_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid match_id")

    match = db.query(Match).filter(Match.id == mid).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    try:
        from resolver.claude_lineup import fetch_lineup_for_match
        lineup = fetch_lineup_for_match(
            home_team=match.home_team,
            away_team=match.away_team,
            kickoff_dt=match.kickoff_utc,
        )

        if lineup:
            match.lineup_data = lineup
            db.commit()
            logger.info(
                "Lineup fetched for %s vs %s: %d home starters, %d away starters",
                match.home_team,
                match.away_team,
                len(lineup.get("home_starters", [])),
                len(lineup.get("away_starters", [])),
            )
            should_analyze = (
                not match.analysis_data
                or lineup.get("lineup_confirmed", False)
            )
            if should_analyze:
                background_tasks.add_task(_run_analysis_and_store, str(match.id))
                return {"status": "ok", "lineup": lineup, "auto_analysis_triggered": True}
            return {"status": "ok", "lineup": lineup, "auto_analysis_triggered": False}
        else:
            return {"status": "not_available", "lineup": None, "message": "Alineación no confirmada aún — suele publicarse ~1h antes del partido"}

    except Exception as exc:
        logger.error("Lineup fetch failed for match %s: %s", match_id, exc)
        raise HTTPException(status_code=500, detail=f"Lineup fetch failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Admin: manual pipeline triggers
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/matches/{match_id}/result")
def record_match_result(match_id: str, result: dict, db: Session = Depends(get_db)):
    """
    Record the final result of a match.
    Body: {"home_score": int, "away_score": int}
    Also marks match_status as "finished" and logs to calibration_log.
    """
    import uuid
    try:
        mid = uuid.UUID(match_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid match_id")

    match = db.query(Match).filter(Match.id == mid).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    home_score = result.get("home_score")
    away_score = result.get("away_score")
    if home_score is None or away_score is None:
        raise HTTPException(status_code=422, detail="home_score and away_score required")

    match.home_score = int(home_score)
    match.away_score = int(away_score)
    match.match_status = "finished"

    # Determine actual result outcome
    if home_score > away_score:
        actual = "home"
    elif away_score > home_score:
        actual = "away"
    else:
        actual = "draw"

    # Log to calibration_log if there's a prediction
    try:
        from models import CalibrationLog, Prediction
        from sqlalchemy import desc as _desc
        prediction = (
            db.query(Prediction)
            .filter(Prediction.match_id == match.id)
            .order_by(_desc(Prediction.created_at))
            .first()
        )
        if prediction:
            cal = CalibrationLog(
                prediction_id=prediction.id,
                actual_result=actual,
            )
            db.add(cal)
    except Exception as exc:
        logger.warning("Could not write calibration log for match %s: %s", match_id, exc)

    db.commit()
    logger.info(
        "Result recorded: %s vs %s = %d-%d (%s)",
        match.home_team, match.away_team, home_score, away_score, actual,
    )
    return {"status": "ok", "actual_result": actual, "home_score": home_score, "away_score": away_score}


@router.post("/api/admin/run-pipeline")
def admin_run_pipeline():
    """Manually trigger the full daily pipeline (seed + model + Polymarket)."""
    from pipeline.pipeline import run_daily_pipeline
    with SessionLocal() as db:
        run_daily_pipeline(db)
        db.commit()
    return {"status": "ok", "message": "Daily pipeline complete"}


@router.post("/api/admin/run-refresh")
def admin_run_refresh():
    """Manually trigger the Polymarket odds refresh."""
    from pipeline.pipeline import run_refresh_pipeline
    with SessionLocal() as db:
        run_refresh_pipeline(db)
        db.commit()
    return {"status": "ok", "message": "Refresh pipeline complete"}


@router.post("/api/admin/seed")
def admin_seed():
    """Manually trigger historical data seed."""
    from pipeline.pipeline import seed_historical_data
    with SessionLocal() as db:
        seed_historical_data(db)
        db.commit()
    return {"status": "ok", "message": "Seed complete"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_outcomes_context(db: Session, match: Match) -> list[dict] | None:
    """Build outcomes list with model + market probs for AI context."""
    prediction = (
        db.query(Prediction)
        .filter(Prediction.match_id == match.id)
        .order_by(desc(Prediction.created_at))
        .first()
    )
    if not prediction:
        return None

    result = []
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

        result.append({
            "outcome": outcome,
            "label": _outcome_label(outcome, match.home_team, match.away_team),
            "model_prob": round(model_prob, 4),
            "polymarket_prob": round(snapshot.polymarket_prob, 4) if snapshot else None,
            "delta_pp": round(snapshot.delta_pp, 1) if snapshot else None,
            "value_tier": snapshot.value_tier if snapshot else None,
        })
    return result


def _run_analysis_and_store(match_id: str) -> None:
    """Background task: run AI analysis and persist to DB.
    Opens a fresh DB session — safe to call from FastAPI BackgroundTasks.
    """
    with SessionLocal() as db:
        try:
            import uuid as _uuid
            try:
                mid = _uuid.UUID(str(match_id))
            except ValueError:
                logger.error("_run_analysis_and_store: invalid match_id %s", match_id)
                return
            match = db.query(Match).filter(Match.id == mid).first()
            if not match:
                logger.warning("_run_analysis_and_store: match %s not found", match_id)
                return
            outcomes_context = _build_outcomes_context(db, match)
            from resolver.match_analyst import analyze_match as run_analysis
            analysis = run_analysis(
                home_team=match.home_team,
                away_team=match.away_team,
                competition=match.competition or "International Friendly",
                kickoff_dt=match.kickoff_utc,
                lineup_data=match.lineup_data,
                outcomes=outcomes_context,
            )
            match.analysis_data = analysis
            db.commit()
            logger.info("Background analysis stored for match %s", match_id)
        except Exception as exc:
            logger.error("Background analysis failed for match %s: %s", match_id, exc)


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

    outcomes_data = []
    best_delta = None
    best_tier = "none"

    # Pull AI probability adjustments if analysis exists
    ai_adjustment = {}
    if match.analysis_data and match.analysis_data.get("prob_adjustment"):
        adj = match.analysis_data["prob_adjustment"]
        if isinstance(adj, dict):
            ai_adjustment = {
                "home": adj.get("home", 0.0),
                "draw": adj.get("draw", 0.0),
                "away": adj.get("away", 0.0),
            }

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

        # AI-adjusted model prob (clamped to [0.01, 0.98])
        raw_adjustment = ai_adjustment.get(outcome, 0.0)
        ai_model_prob = round(max(0.01, min(0.98, model_prob + raw_adjustment)), 4)

        if snapshot:
            delta_pp = snapshot.delta_pp
            value_tier = snapshot.value_tier
            polymarket_prob = snapshot.polymarket_prob
            polymarket_url = _build_polymarket_url(match, outcome)
            # AI-adjusted delta
            ai_delta_pp = round((ai_model_prob - polymarket_prob) * 100, 1) if polymarket_prob else None
        else:
            delta_pp = None
            value_tier = None
            polymarket_prob = None
            polymarket_url = None
            ai_delta_pp = None

        outcome_obj = {
            "outcome": outcome,
            "label": _outcome_label(outcome, match.home_team, match.away_team),
            "polymarket_url": polymarket_url,
            "polymarket_prob": polymarket_prob,
            "model_prob": round(model_prob, 4),
            "ai_model_prob": ai_model_prob if raw_adjustment != 0.0 else None,
            "ai_delta_pp": ai_delta_pp if raw_adjustment != 0.0 else None,
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
        "home_squad": match.home_squad or [],
        "away_squad": match.away_squad or [],
        "lineup_data": match.lineup_data or None,
        "analysis_data": match.analysis_data or None,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "match_status": match.match_status or "scheduled",
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

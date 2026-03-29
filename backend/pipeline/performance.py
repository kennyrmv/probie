"""
performance.py — Match result resolution and CLV tracking for EdgeFút.

Philosophy (per user design):
  Only track matches where the IA emitted a REAL signal:
    - "edge"   → bet_signal.type == "value"    (⚡ Edge confirmado)
    - "fuerza" → bet_signal.type == "strength" (💪 Apuesta de fuerza)

  AND the analysis was run with lineup data (lineup_data_used == True).
  If no lineup yet and match hasn't started, we wait.
  After kickoff +1h we log regardless (some games never publish lineups).

  This lets us compare "edge" vs "fuerza" performance separately.

CLV (Closing Line Value):
  entry_poly_prob  = Polymarket price for signal_outcome at first snapshot
  closing_poly_prob = Polymarket price at last snapshot before kickoff
  clv_pp = (closing - entry) * 100
  Positive CLV = market moved toward our prediction → model was early and right.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import CalibrationLog, MarketSnapshot, Match, Prediction
from resolver.resolver import (
    FootballDataAPIError,
    fetch_results_for_date,
    normalize_team_name,
)

logger = logging.getLogger(__name__)

RESOLUTION_THRESHOLD = 0.95  # Polymarket prob to consider a market settled


# ─────────────────────────────────────────────────────────────────────────────
# Result resolution helpers
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_from_polymarket(db: Session, match: Match) -> str | None:
    """
    Check latest MarketSnapshot per outcome.
    If one outcome has prob > 0.95 the market is settled → that's the result.
    Returns "home", "draw", "away", or None.

    Queries per-outcome explicitly to avoid the limit(9) bug where all rows
    could belong to a single outcome and the others remain unchecked.
    """
    for outcome in ("home", "draw", "away"):
        snap = (
            db.query(MarketSnapshot)
            .filter(
                MarketSnapshot.match_id == match.id,
                MarketSnapshot.outcome == outcome,
            )
            .order_by(desc(MarketSnapshot.snapshotted_at))
            .first()
        )
        if snap and snap.polymarket_prob >= RESOLUTION_THRESHOLD:
            return outcome
    return None


def _resolve_from_football_data(
    match: Match, api_key: str
) -> tuple[str, int, int] | None:
    """
    Try football-data.org for the final score.
    Returns (outcome, home_goals, away_goals) or None.
    """
    date_str = match.kickoff_utc.date().isoformat()
    try:
        results = fetch_results_for_date(date_str, api_key=api_key)
    except FootballDataAPIError as exc:
        logger.debug("FD result fetch failed for %s vs %s: %s", match.home_team, match.away_team, exc)
        return None

    home_norm = normalize_team_name(match.home_team)
    away_norm = normalize_team_name(match.away_team)

    for m in results:
        fd_home = normalize_team_name(m.get("homeTeam", {}).get("name", ""))
        fd_away = normalize_team_name(m.get("awayTeam", {}).get("name", ""))
        if fd_home != home_norm or fd_away != away_norm:
            continue
        score = m.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")
        if hg is None or ag is None:
            return None
        if int(hg) > int(ag):
            return "home", int(hg), int(ag)
        elif int(hg) == int(ag):
            return "draw", int(hg), int(ag)
        else:
            return "away", int(hg), int(ag)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLV helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_entry_snapshot(
    db: Session, match_id, outcome: str
) -> MarketSnapshot | None:
    """
    Earliest snapshot for this outcome — the entry price.
    (Not filtered by value_tier since signal comes from IA, not math tier.)
    """
    return (
        db.query(MarketSnapshot)
        .filter(
            MarketSnapshot.match_id == match_id,
            MarketSnapshot.outcome == outcome,
        )
        .order_by(MarketSnapshot.snapshotted_at)
        .first()
    )


def _get_closing_snapshot(
    db: Session, match_id, outcome: str, kickoff_utc: datetime
) -> MarketSnapshot | None:
    """Last snapshot before kickoff — the closing price."""
    return (
        db.query(MarketSnapshot)
        .filter(
            MarketSnapshot.match_id == match_id,
            MarketSnapshot.outcome == outcome,
            MarketSnapshot.snapshotted_at <= kickoff_utc,
        )
        .order_by(desc(MarketSnapshot.snapshotted_at))
        .first()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main job
# ─────────────────────────────────────────────────────────────────────────────


def resolve_match_results(db: Session) -> int:
    """
    Hourly job: resolve results for AI-signaled matches that kicked off >2.5h ago.

    Tracking rules:
      1. match.analysis_data.bet_signal.type must be "value" or "strength"
      2. analysis must have been run with lineup data (lineup_data_used == True)
         OR match kicked off >1h ago (lineup data may never come for some games)
      3. Result must be resolvable (Polymarket settled OR football-data.org)

    Populates CalibrationLog with signal_source, actual_result, and CLV data.
    Returns number of matches newly resolved.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=2, minutes=30)

    # IDs already in calibration_log (avoid duplicates)
    already_logged: set = {
        row[0]
        for row in db.query(CalibrationLog.prediction_id).all()
    }

    # Matches that should be finished: kicked off >2.5h ago, not yet marked finished
    candidates = (
        db.query(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)
        .filter(
            Match.kickoff_utc <= cutoff,
            Match.match_status != "finished",
        )
        .all()
    )

    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    resolved_count = 0
    already_resolved_matches: set = set()  # avoid double-logging if match has multiple predictions

    for match, prediction in candidates:
        if prediction.id in already_logged:
            continue
        if match.id in already_resolved_matches:
            continue

        # ── Gate 1: AI must have emitted a signal ──────────────────────────
        analysis = match.analysis_data
        if not analysis:
            logger.debug(
                "Skip %s vs %s — no analysis data", match.home_team, match.away_team
            )
            continue

        signal = analysis.get("bet_signal") or {}
        signal_type = signal.get("type")
        signal_side = signal.get("side")

        VALID_SIDES = ("home", "draw", "away")
        if signal_type not in ("value", "strength") or not signal_side:
            logger.debug(
                "Skip %s vs %s — IA signal is '%s' (not value/strength)",
                match.home_team, match.away_team, signal_type,
            )
            continue
        if signal_side not in VALID_SIDES:
            logger.warning(
                "Skip %s vs %s — invalid signal_side '%s' from LLM (expected home/draw/away)",
                match.home_team, match.away_team, signal_side,
            )
            continue

        # ── Gate 2: must have lineup data (verify from actual DB data, not LLM self-report) ──
        # Check match.lineup_data directly — the LLM's analysis_data.lineup_data_used is a
        # self-report that the LLM could hallucinate True even if no lineup was provided.
        actual_lineup_available = bool(
            match.lineup_data and match.lineup_data.get("home_starters")
        )
        # Also accept analysis self-report as a secondary signal, but not alone
        lineup_data_used = actual_lineup_available or bool(analysis.get("lineup_data_used", False))
        hours_since_kickoff = (now - match.kickoff_utc).total_seconds() / 3600

        if not lineup_data_used and hours_since_kickoff < 1.0:
            logger.debug(
                "Skip %s vs %s — no lineup in analysis yet and only %.1fh since kickoff. Waiting.",
                match.home_team, match.away_team, hours_since_kickoff,
            )
            continue

        # ── Resolve actual result ──────────────────────────────────────────
        actual_result = _resolve_from_polymarket(db, match)

        if not actual_result and api_key:
            fd = _resolve_from_football_data(match, api_key)
            if fd:
                actual_result, home_score, away_score = fd
                match.home_score = home_score
                match.away_score = away_score

        if not actual_result:
            logger.debug(
                "Cannot resolve result yet for %s vs %s", match.home_team, match.away_team
            )
            continue

        match.match_status = "finished"

        # ── Signal metadata ────────────────────────────────────────────────
        signal_source = "edge" if signal_type == "value" else "fuerza"
        signal_outcome = signal_side
        lineup_confirmed = lineup_data_used  # reuse already-computed value (key: "lineup_data_used")

        # Model probability for the signaled outcome
        model_prob = {
            "home": prediction.model_home_prob,
            "draw": prediction.model_draw_prob,
            "away": prediction.model_away_prob,
        }.get(signal_outcome)

        # Math tier at signal time (from latest snapshot before kickoff)
        entry_snap = _get_entry_snapshot(db, match.id, signal_outcome)
        closing_snap = _get_closing_snapshot(db, match.id, signal_outcome, match.kickoff_utc)

        entry_poly_prob = entry_snap.polymarket_prob if entry_snap else None
        closing_poly_prob = closing_snap.polymarket_prob if closing_snap else None
        clv_pp = (
            (closing_poly_prob - entry_poly_prob) * 100.0
            if entry_poly_prob is not None and closing_poly_prob is not None
            else None
        )
        signal_tier = entry_snap.value_tier if entry_snap else None

        # ── Persist ────────────────────────────────────────────────────────
        log = CalibrationLog(
            prediction_id=prediction.id,
            actual_result=actual_result,
            signal_outcome=signal_outcome,
            signal_source=signal_source,
            signal_tier=signal_tier,
            model_prob=model_prob,
            lineup_confirmed=lineup_confirmed,
            entry_poly_prob=entry_poly_prob,
            closing_poly_prob=closing_poly_prob,
            clv_pp=clv_pp,
        )
        db.add(log)
        already_logged.add(prediction.id)
        already_resolved_matches.add(match.id)
        resolved_count += 1

        logger.info(
            "Resolved %s vs %s → %s | %s(%s) signal=%s tier=%s CLV=%s lineup=%s",
            match.home_team,
            match.away_team,
            actual_result,
            signal_source,
            signal_outcome,
            "✓" if signal_outcome == actual_result else "✗",
            signal_tier or "?",
            f"{clv_pp:+.1f}pp" if clv_pp is not None else "N/A",
            "confirmed" if lineup_confirmed else "probable",
        )

    db.flush()
    logger.info("resolve_match_results: %d newly resolved (AI-signal + lineup gate)", resolved_count)
    return resolved_count

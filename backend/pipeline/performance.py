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
from datetime import date as date_cls, datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import CalibrationLog, DailyPick, MarketSnapshot, Match, Prediction
from resolver.resolver import (
    FootballDataAPIError,
    fetch_results_for_date,
    fetch_results_from_espn,
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
    Try ESPN first (covers all competitions, no key), then football-data.org as fallback.
    Returns (outcome, home_goals, away_goals) or None.
    """
    date_str = match.kickoff_utc.date().isoformat()
    home_norm = normalize_team_name(match.home_team)
    away_norm = normalize_team_name(match.away_team)

    # ── ESPN (primary — covers friendlies, all leagues, no key needed) ───────
    try:
        espn_results = fetch_results_from_espn(date_str)
        result = _match_score_in_results(espn_results, home_norm, away_norm)
        if result:
            logger.debug("Score via ESPN: %s vs %s → %s", match.home_team, match.away_team, result)
            return result
    except FootballDataAPIError as exc:
        logger.debug("ESPN fetch failed for %s vs %s: %s", match.home_team, match.away_team, exc)

    # ── football-data.org (fallback — needs key, limited competitions) ───────
    if api_key:
        try:
            fd_results = fetch_results_for_date(date_str, api_key=api_key)
            result = _match_score_in_results(fd_results, home_norm, away_norm)
            if result:
                logger.debug("Score via FD: %s vs %s → %s", match.home_team, match.away_team, result)
                return result
        except FootballDataAPIError as exc:
            logger.debug("FD fetch failed for %s vs %s: %s", match.home_team, match.away_team, exc)

    return None


def _match_score_in_results(
    results: list[dict], home_norm: str, away_norm: str
) -> tuple[str, int, int] | None:
    """Find a match by normalized team name in a list of result dicts."""
    from rapidfuzz import fuzz
    for m in results:
        fd_home = normalize_team_name(m.get("homeTeam", {}).get("name", ""))
        fd_away = normalize_team_name(m.get("awayTeam", {}).get("name", ""))
        # Exact match first, then fuzzy (ESPN uses full names like "FC Barcelona")
        home_ok = fd_home == home_norm or fuzz.token_set_ratio(fd_home, home_norm) >= 85
        away_ok = fd_away == away_norm or fuzz.token_set_ratio(fd_away, away_norm) >= 85
        if not (home_ok and away_ok):
            continue
        score = m.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")
        if hg is None or ag is None:
            return None
        hg, ag = int(hg), int(ag)
        outcome = "home" if hg > ag else "away" if ag > hg else "draw"
        return outcome, hg, ag
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

    # Matches that should be finished: kicked off >2.5h ago, within last 7 days.
    # NOTE: we do NOT filter by match_status != "finished" here because update_match_scores()
    # may have already marked a match as "finished" before resolve_match_results() could log it.
    # Deduplication is handled entirely by already_logged (prediction_id in CalibrationLog).
    window_open = now - timedelta(days=7)
    candidates = (
        db.query(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)
        .filter(
            Match.kickoff_utc <= cutoff,
            Match.kickoff_utc >= window_open,
        )
        .all()
    )

    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    resolved_count = 0
    # Avoid double-logging: pre-load match IDs that already have a CalibrationLog entry
    already_resolved_matches: set = {
        row[0]
        for row in db.query(Prediction.match_id)
        .join(CalibrationLog, CalibrationLog.prediction_id == Prediction.id)
        .all()
    }

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

        # ── Gate 2: must have OFFICIALLY CONFIRMED lineup (not just probable/press-conference) ──
        # Requires lineup_confirmed: True in lineup_data — only API-Football and Claude "official"
        # sources set this. Probable lineups (press conferences, journalists) are excluded.
        # Rationale: Georgia/Lithuania and Armenia/Belarus showed wrong lineups because Claude
        # classified press-conference lineups as "confirmed". This gate prevents those from
        # inflating our tracking quality.
        actual_lineup_available = bool(
            match.lineup_data
            and match.lineup_data.get("home_starters")
            and match.lineup_data.get("lineup_confirmed", False)  # must be officially confirmed
        )
        # No LLM self-report fallback — analysis_data.lineup_data_used can be hallucinated
        lineup_data_used = actual_lineup_available
        hours_since_kickoff = (now - match.kickoff_utc).total_seconds() / 3600

        if not lineup_data_used and hours_since_kickoff < 1.0:
            logger.debug(
                "Skip %s vs %s — no confirmed lineup yet and only %.1fh since kickoff. Waiting.",
                match.home_team, match.away_team, hours_since_kickoff,
            )
            continue

        # ── Resolve actual result ──────────────────────────────────────────
        actual_result = _resolve_from_polymarket(db, match)

        if api_key:
            fd = _resolve_from_football_data(match, api_key)
            if fd:
                fd_result, home_score, away_score = fd
                # Always write the score for display — regardless of how result was resolved
                if match.home_score is None:
                    match.home_score = home_score
                    match.away_score = away_score
                # Use football-data result if Polymarket didn't settle
                if not actual_result:
                    actual_result = fd_result

        if not actual_result:
            logger.debug(
                "Cannot resolve result yet for %s vs %s", match.home_team, match.away_team
            )
            continue

        match.match_status = "finished"

        # ── Signal metadata ────────────────────────────────────────────────
        signal_source = "edge" if signal_type == "value" else "fuerza"
        signal_outcome = signal_side
        lineup_confirmed = actual_lineup_available  # True only if officially confirmed XI

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

        # ── Was this the day's top pick? ───────────────────────────────────
        match_date = match.kickoff_utc.date()
        pick_type_key = "value" if signal_source == "edge" else "strength"
        daily_pick = (
            db.query(DailyPick)
            .filter(
                DailyPick.date == match_date,
                DailyPick.match_id == match.id,
                DailyPick.pick_type == pick_type_key,
            )
            .first()
        )
        is_top_pick = daily_pick is not None

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
            is_top_pick=is_top_pick,
        )
        db.add(log)
        already_logged.add(prediction.id)
        already_resolved_matches.add(match.id)
        resolved_count += 1

        logger.info(
            "Resolved %s vs %s → %s | %s(%s) signal=%s tier=%s CLV=%s lineup=%s pick=%s",
            match.home_team,
            match.away_team,
            actual_result,
            signal_source,
            signal_outcome,
            "✓" if signal_outcome == actual_result else "✗",
            signal_tier or "?",
            f"{clv_pp:+.1f}pp" if clv_pp is not None else "N/A",
            "confirmed" if lineup_confirmed else "probable",
            "🏆top" if is_top_pick else "secondary",
        )

    db.flush()
    logger.info("resolve_match_results: %d newly resolved (AI-signal + lineup gate)", resolved_count)
    return resolved_count


# ─────────────────────────────────────────────────────────────────────────────
# Score display — no gates, no CalibrationLog
# ─────────────────────────────────────────────────────────────────────────────


def update_match_scores(db: Session) -> int:
    """
    Fetch final scores for ALL matches that kicked off >2h ago and still have no score.
    No AI signal gate — purely for score display on the frontend.

    Does NOT touch CalibrationLog — that's resolve_match_results()'s job.
    Runs alongside the hourly resolve job.
    """
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not api_key:
        return 0

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=2)

    unresolved = (
        db.query(Match)
        .filter(
            Match.kickoff_utc <= cutoff,
            Match.home_score.is_(None),
        )
        .all()
    )

    updated = 0
    for match in unresolved:
        fd = _resolve_from_football_data(match, api_key)
        if not fd:
            continue
        actual_result, home_goals, away_goals = fd
        match.home_score = home_goals
        match.away_score = away_goals
        match.match_status = "finished"
        updated += 1
        logger.info(
            "Score fetched: %s vs %s → %d-%d (%s)",
            match.home_team, match.away_team, home_goals, away_goals, actual_result,
        )

    if updated:
        db.flush()
    logger.info("update_match_scores: %d scores updated", updated)
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Daily picks — Veredictos del día
# ─────────────────────────────────────────────────────────────────────────────


def save_daily_picks(db: Session, target_date: date_cls | None = None) -> dict:
    """
    Select and persist today's top Veredictos del día.
    Mirrors frontend pickBestBets() logic:
      - Best VALUE: scheduled match with highest ai_delta_pp among "value" signals (≥5pp)
      - Best STRENGTH: scheduled match with "strength" signal, ranked by confidence

    Upserts into daily_picks table — one entry per pick_type per day.
    Run at 09:30 and 14:30 UTC (after daily pipeline) so new analyses are captured.

    Returns {"date": str, "value": match_id_str|None, "strength": match_id_str|None}
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    day_start = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=timezone.utc,
    )
    day_end = day_start + timedelta(hours=36)  # same window as /api/matches/today

    candidates = (
        db.query(Match)
        .filter(
            Match.kickoff_utc >= day_start,
            Match.kickoff_utc <= day_end,
            Match.match_status == "scheduled",
        )
        .all()
    )

    conf_map = {"alta": 3, "media": 2, "baja": 1}
    best_value: tuple | None = None   # (match, signal_side, ai_delta_pp)
    best_value_edge = -999.0
    best_strength: tuple | None = None  # (match, signal_side)
    best_strength_conf = 0

    for match in candidates:
        analysis = match.analysis_data
        if not analysis:
            continue

        signal = analysis.get("bet_signal") or {}
        signal_type = signal.get("type")
        signal_side = signal.get("side")

        if not signal_side or signal_type not in ("value", "strength"):
            continue

        if signal_side not in ("home", "draw", "away"):
            continue

        if signal_type == "value":
            # Compute ai_delta_pp — same as routes._build_match_response()
            prediction = (
                db.query(Prediction)
                .filter(Prediction.match_id == match.id)
                .order_by(desc(Prediction.created_at))
                .first()
            )
            snap = (
                db.query(MarketSnapshot)
                .filter(
                    MarketSnapshot.match_id == match.id,
                    MarketSnapshot.outcome == signal_side,
                )
                .order_by(desc(MarketSnapshot.snapshotted_at))
                .first()
            )
            if not prediction or not snap:
                continue

            model_prob = {
                "home": prediction.model_home_prob,
                "draw": prediction.model_draw_prob,
                "away": prediction.model_away_prob,
            }.get(signal_side, 0.0)

            adj = analysis.get("prob_adjustment") or {}
            ai_adj = adj.get(signal_side, 0.0) if isinstance(adj, dict) else 0.0
            ai_model_prob = max(0.01, min(0.98, model_prob + ai_adj))
            ai_delta_pp = (ai_model_prob - snap.polymarket_prob) * 100.0

            if ai_delta_pp < 5.0:  # minimum 5pp edge required
                continue

            if ai_delta_pp > best_value_edge:
                best_value_edge = ai_delta_pp
                best_value = (match, signal_side)

        elif signal_type == "strength":
            conf = signal.get("confidence", "baja")
            conf_score = conf_map.get(conf, 1)
            if conf_score > best_strength_conf:
                best_strength_conf = conf_score
                best_strength = (match, signal_side)

    result: dict = {"date": target_date.isoformat(), "value": None, "strength": None}

    for pick_type, pick_data in [("value", best_value), ("strength", best_strength)]:
        if not pick_data:
            continue
        match, signal_side = pick_data

        existing = (
            db.query(DailyPick)
            .filter(
                DailyPick.date == target_date,
                DailyPick.pick_type == pick_type,
            )
            .first()
        )

        if existing:
            existing.match_id = match.id
            existing.signal_side = signal_side
            logger.info(
                "Daily pick updated: %s → %s vs %s (%s)",
                pick_type, match.home_team, match.away_team, signal_side,
            )
        else:
            db.add(DailyPick(
                date=target_date,
                match_id=match.id,
                pick_type=pick_type,
                signal_side=signal_side,
            ))
            logger.info(
                "Daily pick saved: %s → %s vs %s (%s)",
                pick_type, match.home_team, match.away_team, signal_side,
            )

        result[pick_type] = str(match.id)

    db.flush()
    return result

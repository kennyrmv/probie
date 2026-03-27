"""
pipeline.py — Dixon-Coles model + reasons generation for EdgeFút.

Flow:
  1. seed_historical_data() — populate historical_matches from football-data.org
  2. fit_dixon_coles()      — fit model on historical data
  3. predict_match()        — compute home/draw/away probs for a fixture
  4. select_reasons()       — pick top 3 signals by deviation magnitude
  5. run_pipeline()         — orchestrates the daily + pre-match refresh
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import penaltyblog as pb
from sqlalchemy.orm import Session

from models import HistoricalMatch, Match, MarketSnapshot, Prediction
from resolver.resolver import (
    fetch_historical_matches,
    fetch_polymarket_events,
    fetch_today_fixtures,
    get_all_outcome_probs,
    normalize_team_name,
    resolve_match,
    FootballDataAPIError,
    PolymarketAPIError,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

COLD_START_THRESHOLD = 50  # warn if fewer matches in DB
VALUE_TIER_HIGH_PP = 10.0  # delta > 10pp → "high"
VALUE_TIER_MID_PP = 5.0    # delta 5-10pp → "mid"

# Competitions to track (football-data.org codes)
TARGET_COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "UCL", "CL"]

# Seed: last 2 PL seasons
SEED_COMPETITION = "PL"
SEED_SEASONS = [2023, 2024]

# ─────────────────────────────────────────────────────────────────────────────
# Historical data seeding
# ─────────────────────────────────────────────────────────────────────────────


def seed_historical_data(
    db: Session,
    competition_code: str = SEED_COMPETITION,
    seasons: list[int] | None = None,
    api_key: str | None = None,
) -> int:
    """
    Populate historical_matches from football-data.org.
    Idempotent: checks for existing rows before inserting (no duplicates).

    Returns number of rows inserted.
    """
    if seasons is None:
        seasons = SEED_SEASONS

    total_inserted = 0
    key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")

    for season in seasons:
        raw_matches = fetch_historical_matches(competition_code, season, api_key=key)
        inserted = 0

        for m in raw_matches:
            home_team = m.get("homeTeam", {})
            away_team = m.get("awayTeam", {})
            score = m.get("score", {}).get("fullTime", {})
            date_str = m.get("utcDate", "")

            home_id = home_team.get("id")
            away_id = away_team.get("id")
            home_name = home_team.get("name", "")
            away_name = away_team.get("name", "")
            home_goals = score.get("home")
            away_goals = score.get("away")

            if None in (home_id, away_id, home_goals, away_goals) or not date_str:
                continue

            # Idempotency check: skip if this fixture already exists
            existing = (
                db.query(HistoricalMatch)
                .filter(
                    HistoricalMatch.home_team_id == home_id,
                    HistoricalMatch.away_team_id == away_id,
                    HistoricalMatch.season == season,
                    HistoricalMatch.home_goals == home_goals,
                    HistoricalMatch.away_goals == away_goals,
                )
                .first()
            )
            if existing:
                continue

            try:
                match_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            row = HistoricalMatch(
                home_team_id=home_id,
                away_team_id=away_id,
                home_team_name=home_name,
                away_team_name=away_name,
                home_goals=home_goals,
                away_goals=away_goals,
                date=match_date,
                competition=competition_code,
                season=season,
            )
            db.add(row)
            inserted += 1

        db.flush()
        logger.info("Seeded %d new matches (%s season %d)", inserted, competition_code, season)
        total_inserted += inserted

    total_in_db = db.query(HistoricalMatch).count()
    if total_in_db < COLD_START_THRESHOLD:
        logger.warning(
            "Cold start: only %d historical matches in DB. "
            "Model may be unreliable (need >%d). Seed more data.",
            total_in_db, COLD_START_THRESHOLD,
        )

    return total_inserted


# ─────────────────────────────────────────────────────────────────────────────
# Dixon-Coles model
# ─────────────────────────────────────────────────────────────────────────────


def _load_training_data(db: Session) -> pd.DataFrame:
    """Load historical matches from DB into a DataFrame for penaltyblog."""
    rows = db.query(HistoricalMatch).all()
    return pd.DataFrame(
        [
            {
                "home_team": normalize_team_name(r.home_team_name),
                "away_team": normalize_team_name(r.away_team_name),
                "home_goals": r.home_goals,
                "away_goals": r.away_goals,
                "date": r.date,
            }
            for r in rows
        ]
    )


def fit_dixon_coles(db: Session) -> pb.models.DixonColes:
    """
    Fit a Dixon-Coles model on the historical_matches table.

    Teams with no historical data get league-average parameters (handled by penaltyblog).
    Returns the fitted model object.
    """
    df = _load_training_data(db)
    if df.empty:
        raise ValueError("No historical data available to fit Dixon-Coles model")

    model = pb.models.DixonColes()
    model.fit(
        goals_home=df["home_goals"],
        goals_away=df["away_goals"],
        teams_home=df["home_team"],
        teams_away=df["away_team"],
    )
    logger.info(
        "Dixon-Coles fitted on %d matches (%d unique teams)",
        len(df),
        len(set(df["home_team"]) | set(df["away_team"])),
    )
    return model


def predict_match(
    model: pb.models.DixonColes,
    home_team: str,
    away_team: str,
) -> dict[str, float]:
    """
    Compute home/draw/away probabilities using the fitted Dixon-Coles model.

    Returns dict with keys "home", "draw", "away" that sum to 1.0 (within 1e-6).
    Teams not in training data get league-average parameters (not a crash).
    """
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    probs = model.predict(home_norm, away_norm)

    # penaltyblog returns a probability matrix; sum over result bins
    p_home = float(probs.home_win)
    p_draw = float(probs.draw)
    p_away = float(probs.away_win)

    # Sanity check: probs should sum to ~1.0
    total = p_home + p_draw + p_away
    if abs(total - 1.0) > 1e-4:
        logger.warning(
            "Dixon-Coles probabilities don't sum to 1.0 for %s vs %s: %.6f",
            home_team, away_team, total,
        )

    return {"home": p_home, "draw": p_draw, "away": p_away}


# ─────────────────────────────────────────────────────────────────────────────
# Signal computation (reasons)
# ─────────────────────────────────────────────────────────────────────────────


def _compute_signals(
    fixture: dict,
    model: pb.models.DixonColes,
    home_team: str,
    away_team: str,
    weather_data: dict | None = None,
    lineups_data: dict | None = None,
) -> list[dict]:
    """
    Compute all available signals for a fixture.
    Returns list of signal dicts with keys: type, value, deviation, direction, text.
    Signals that fail (API timeout, missing data) are silently skipped.
    """
    signals: list[dict] = []
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    # ── Signal 1: Home advantage index (Dixon-Coles parameters)
    try:
        home_attack = model.parameters.get(f"attack_{home_norm}", model.parameters.get("mu", 1.0))
        away_defense = model.parameters.get(f"defence_{away_norm}", model.parameters.get("mu", 1.0))
        home_adv_index = float(home_attack) - float(away_defense)
        signals.append({
            "type": "home_advantage",
            "value": round(home_adv_index, 3),
            "deviation": abs(home_adv_index),
            "direction": "positive" if home_adv_index > 0 else "negative",
            "text": f"Índice ataque local vs defensa visitante: {home_adv_index:+.2f}",
        })
    except Exception as exc:
        logger.debug("home_advantage signal failed: %s", exc)

    # ── Signal 2: H2H win rate (from fixture data if available)
    try:
        h2h = fixture.get("head2head", {})
        home_wins = h2h.get("homeTeam", {}).get("wins", 0)
        total_h2h = h2h.get("numberOfMatches", 0)
        if total_h2h > 0:
            h2h_rate = home_wins / total_h2h
            baseline = 0.4  # rough league average home win rate
            deviation = abs(h2h_rate - baseline)
            signals.append({
                "type": "h2h",
                "value": round(h2h_rate, 3),
                "deviation": deviation,
                "direction": "positive" if h2h_rate > baseline else "negative",
                "text": f"{home_team} gana {home_wins}/{total_h2h} H2H recientes",
            })
    except Exception as exc:
        logger.debug("h2h signal failed: %s", exc)

    # ── Signal 3: Form delta (points/game last 5)
    try:
        home_form = fixture.get("homeTeam", {}).get("form", "")
        away_form = fixture.get("awayTeam", {}).get("form", "")
        if home_form and away_form:
            home_pts = sum(3 if r == "W" else (1 if r == "D" else 0) for r in home_form[:5])
            away_pts = sum(3 if r == "W" else (1 if r == "D" else 0) for r in away_form[:5])
            form_delta = (home_pts - away_pts) / 15.0  # normalize to [-1, 1]
            signals.append({
                "type": "form",
                "value": round(form_delta, 3),
                "deviation": abs(form_delta),
                "direction": "positive" if form_delta > 0 else "negative",
                "text": f"Forma últimas 5: {home_team} {home_pts}pts vs {away_team} {away_pts}pts",
            })
    except Exception as exc:
        logger.debug("form signal failed: %s", exc)

    # ── Signal 4: Key absences (lineups)
    if lineups_data is not None:
        try:
            absent_home = lineups_data.get("home_absences", [])
            absent_away = lineups_data.get("away_absences", [])
            n_absent = len(absent_home) + len(absent_away)
            if n_absent > 0:
                deviation = min(n_absent / 5.0, 1.0)  # cap at 1.0
                direction = "negative" if absent_home else "positive"  # home absences hurt
                names = ", ".join((absent_home + absent_away)[:3])
                signals.append({
                    "type": "absence",
                    "value": n_absent,
                    "deviation": deviation,
                    "direction": direction,
                    "text": f"Bajas: {names}" + (" (+más)" if n_absent > 3 else ""),
                })
        except Exception as exc:
            logger.debug("absence signal failed: %s", exc)

    # ── Signal 5: Weather (adverse conditions flag)
    if weather_data is not None:
        try:
            precip = weather_data.get("precipitation_mm", 0)
            wind = weather_data.get("wind_speed_kph", 0)
            if precip > 5 or wind > 40:
                adverse_score = (precip / 50.0) + (wind / 100.0)
                signals.append({
                    "type": "weather",
                    "value": {"precipitation_mm": precip, "wind_speed_kph": wind},
                    "deviation": min(adverse_score, 1.0),
                    "direction": "negative",
                    "text": f"Condiciones adversas: {precip}mm lluvia, viento {wind}km/h",
                })
        except Exception as exc:
            logger.debug("weather signal failed: %s", exc)

    return signals


def select_reasons(
    fixture: dict,
    model: pb.models.DixonColes,
    home_team: str,
    away_team: str,
    weather_data: dict | None = None,
    lineups_data: dict | None = None,
    n: int = 3,
) -> list[dict]:
    """
    Select the top N signals by deviation magnitude.

    If fewer than N signals are available, returns what's available.
    If all signals have zero deviation, still returns N (degenerate case).
    Weather/lineup signals that are unavailable are silently skipped.

    Returns list of reason dicts: [{type, value, direction, text}]
    """
    all_signals = _compute_signals(
        fixture, model, home_team, away_team,
        weather_data=weather_data,
        lineups_data=lineups_data,
    )

    if not all_signals:
        logger.warning(
            "select_reasons: no signals available for %s vs %s",
            home_team, away_team,
        )
        return []

    # Sort by deviation descending; pick top N
    sorted_signals = sorted(all_signals, key=lambda s: s["deviation"], reverse=True)
    top = sorted_signals[:n]

    # Return clean reason dicts (drop internal "deviation" key)
    return [
        {"type": s["type"], "value": s["value"], "direction": s["direction"], "text": s["text"]}
        for s in top
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Value tier calculation
# ─────────────────────────────────────────────────────────────────────────────


def compute_value_tier(delta_pp: float) -> str:
    """
    Classify delta (model_prob - market_prob in percentage points) into value tier.
    high: >10pp | mid: 5-10pp | none: <5pp
    """
    if delta_pp > VALUE_TIER_HIGH_PP:
        return "high"
    elif delta_pp > VALUE_TIER_MID_PP:
        return "mid"
    else:
        return "none"


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline orchestration
# ─────────────────────────────────────────────────────────────────────────────


def run_daily_pipeline(db: Session) -> int:
    """
    Daily fixture poller (06:00 UTC):
    1. Fetch today's fixtures from football-data.org
    2. Resolve each to a Polymarket event
    3. Fit Dixon-Coles model
    4. Store matches + predictions in DB

    Returns number of matches processed.
    """
    logger.info("=== EdgeFút daily pipeline starting ===")

    # 1. Fetch fixtures
    try:
        fixtures = fetch_today_fixtures(competition_codes=TARGET_COMPETITIONS)
    except FootballDataAPIError as exc:
        logger.error("Daily pipeline: failed to fetch fixtures: %s", exc)
        return 0

    if not fixtures:
        logger.info("Daily pipeline: no fixtures today")
        return 0

    # 2. Fetch Polymarket events (once, reused for all fixtures)
    try:
        pm_events = fetch_polymarket_events()
    except PolymarketAPIError as exc:
        logger.error("Daily pipeline: failed to fetch Polymarket events: %s", exc)
        return 0

    # 3. Fit model
    try:
        model = fit_dixon_coles(db)
    except ValueError as exc:
        logger.error("Daily pipeline: model fit failed: %s", exc)
        return 0

    processed = 0
    for fixture in fixtures:
        try:
            _process_fixture(db, fixture, pm_events, model)
            processed += 1
        except Exception as exc:
            logger.error(
                "Daily pipeline: error processing fixture %s: %s",
                fixture.get("id"), exc,
            )
            continue

    logger.info("=== Daily pipeline complete: %d/%d fixtures processed ===", processed, len(fixtures))
    return processed


def run_refresh_pipeline(db: Session) -> int:
    """
    Pre-match refresher (every 15 min, 08:00-22:00 UTC on match days):
    Updates Polymarket odds snapshots for all today's matches.
    """
    logger.info("=== EdgeFút 15-min refresh starting ===")

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start.replace(hour=23, minute=59)

    today_matches = (
        db.query(Match)
        .filter(Match.kickoff_utc >= today_start, Match.kickoff_utc <= today_end)
        .all()
    )

    if not today_matches:
        return 0

    try:
        pm_events = fetch_polymarket_events()
    except PolymarketAPIError as exc:
        logger.error("Refresh pipeline: failed to fetch Polymarket events: %s", exc)
        return 0

    try:
        model = fit_dixon_coles(db)
    except ValueError as exc:
        logger.error("Refresh pipeline: model fit failed: %s", exc)
        return 0

    refreshed = 0
    for match in today_matches:
        try:
            _refresh_match_snapshot(db, match, pm_events, model)
            refreshed += 1
        except Exception as exc:
            logger.error("Refresh pipeline: error refreshing match %s: %s", match.id, exc)

    logger.info("=== Refresh complete: %d/%d matches updated ===", refreshed, len(today_matches))
    return refreshed


def _process_fixture(
    db: Session,
    fixture: dict,
    pm_events: list[dict],
    model,
) -> None:
    """Process a single fixture: resolve, predict, store."""
    home_team = fixture.get("homeTeam", {}).get("name", "")
    away_team = fixture.get("awayTeam", {}).get("name", "")
    kickoff_str = fixture.get("utcDate", "")
    competition = fixture.get("competition", {}).get("name", "Unknown")

    if not home_team or not away_team or not kickoff_str:
        return

    kickoff_dt = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))

    # Upsert match record
    match = (
        db.query(Match)
        .filter(
            Match.home_team == home_team,
            Match.away_team == away_team,
            Match.kickoff_utc == kickoff_dt,
        )
        .first()
    )

    if not match:
        match = Match(
            home_team=home_team,
            away_team=away_team,
            kickoff_utc=kickoff_dt,
            competition=competition,
        )
        db.add(match)

    # Resolve to Polymarket
    pm_event = resolve_match(fixture, pm_events)
    if pm_event:
        match.polymarket_neg_risk_market_id = pm_event.get("negRiskMarketID")
        match.polymarket_event_slug = pm_event.get("slug")

    db.flush()  # get match.id

    # Compute model probabilities
    probs = predict_match(model, home_team, away_team)

    # Generate reasons
    reasons = select_reasons(fixture, model, home_team, away_team)

    # Store prediction (immutable)
    prediction = Prediction(
        match_id=match.id,
        model_home_prob=probs["home"],
        model_draw_prob=probs["draw"],
        model_away_prob=probs["away"],
        reasons=reasons,
    )
    db.add(prediction)

    # Store market snapshots if Polymarket resolved
    if pm_event:
        _store_market_snapshots(db, match, pm_event, probs)


def _refresh_match_snapshot(
    db: Session,
    match: Match,
    pm_events: list[dict],
    model,
) -> None:
    """Refresh Polymarket odds snapshot for an existing match."""
    fixture = {
        "homeTeam": {"name": match.home_team},
        "awayTeam": {"name": match.away_team},
        "utcDate": match.kickoff_utc.isoformat(),
    }
    pm_event = resolve_match(fixture, pm_events)
    if not pm_event:
        return

    probs = predict_match(model, match.home_team, match.away_team)
    _store_market_snapshots(db, match, pm_event, probs)


def _store_market_snapshots(
    db: Session,
    match: Match,
    pm_event: dict,
    model_probs: dict[str, float],
) -> None:
    """
    Append new market_snapshots rows for home/draw/away.
    NEVER updates existing rows — append-only.
    """
    try:
        pm_probs = get_all_outcome_probs(
            pm_event, match.home_team, match.away_team
        )
    except (ValueError, Exception) as exc:
        logger.warning(
            "Could not get Polymarket probs for %s vs %s: %s",
            match.home_team, match.away_team, exc,
        )
        return

    now = datetime.now(timezone.utc)
    for outcome in ("home", "draw", "away"):
        model_prob = model_probs.get(outcome, 0.0)
        pm_prob = pm_probs.get(outcome, 0.0)
        delta_pp = (model_prob - pm_prob) * 100.0  # convert to percentage points

        snapshot = MarketSnapshot(
            match_id=match.id,
            outcome=outcome,
            polymarket_market_id=pm_event.get("markets", [{}])[0].get("id"),
            polymarket_prob=pm_prob,
            delta_pp=delta_pp,
            value_tier=compute_value_tier(delta_pp),
            snapshotted_at=now,
        )
        db.add(snapshot)

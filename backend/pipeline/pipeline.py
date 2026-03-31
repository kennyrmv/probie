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
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import penaltyblog as pb
from sqlalchemy.orm import Session

from models import HistoricalMatch, Match, MarketSnapshot, Prediction
from resolver.resolver import (
    fetch_historical_matches,
    fetch_polymarket_events,
    fetch_squad_for_team,
    fetch_today_fixtures,
    fetch_today_from_polymarket,
    get_all_outcome_probs,
    normalize_team_name,
    resolve_match,
    FootballDataAPIError,
    PolymarketAPIError,
)
from resolver.api_football import fetch_lineup_for_match, LineupAPIError

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

COLD_START_THRESHOLD = 50  # warn if fewer matches in DB
VALUE_TIER_HIGH_PP = 10.0  # delta > 10pp → "high"
VALUE_TIER_MID_PP = 5.0    # delta 5-10pp → "mid"

# Competitions to track (football-data.org codes)
# All available on the free tier: domestic leagues + CL + Copa Libertadores
TARGET_COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "CL", "CLI", "DED", "PPL", "BSA", "ELC"]

# Seed: last 2 seasons of the 5 big leagues + CL
SEED_COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "CL"]
SEED_SEASONS = [2023, 2024]

# ─────────────────────────────────────────────────────────────────────────────
# Historical data seeding
# ─────────────────────────────────────────────────────────────────────────────


def seed_historical_data(
    db: Session,
    competitions: list[str] | None = None,
    seasons: list[int] | None = None,
    api_key: str | None = None,
) -> int:
    """
    Populate historical_matches from football-data.org.
    Idempotent: checks for existing rows before inserting (no duplicates).
    Seeds all 5 big leagues + CL for the last 2 seasons.

    Returns number of rows inserted.
    """
    if seasons is None:
        seasons = SEED_SEASONS
    if competitions is None:
        competitions = SEED_COMPETITIONS

    total_inserted = 0
    key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")

    for competition_code in competitions:
        for season in seasons:
            try:
                raw_matches = fetch_historical_matches(competition_code, season, api_key=key)
            except FootballDataAPIError as exc:
                logger.warning("Seed: skipping %s/%d — %s", competition_code, season, exc)
                continue
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


def fit_dixon_coles(db: Session) -> pb.models.DixonColesGoalModel:
    """
    Fit a Dixon-Coles model on the historical_matches table.

    Teams with no historical data get league-average parameters (handled by penaltyblog).
    Returns the fitted model object.
    """
    df = _load_training_data(db)
    if df.empty:
        raise ValueError("No historical data available to fit Dixon-Coles model")

    import numpy as np
    model = pb.models.DixonColesGoalModel(
        goals_home=np.array(df["home_goals"], copy=True),
        goals_away=np.array(df["away_goals"], copy=True),
        teams_home=df["home_team"].tolist(),
        teams_away=df["away_team"].tolist(),
    )
    model.fit()
    logger.info(
        "Dixon-Coles fitted on %d matches (%d unique teams)",
        len(df),
        len(set(df["home_team"]) | set(df["away_team"])),
    )
    return model


def predict_match(
    model: pb.models.DixonColesGoalModel,
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

    try:
        probs = model.predict(home_norm, away_norm, max_goals=10)
        p_home = float(probs.home_win)
        p_draw = float(probs.draw)
        p_away = float(probs.away_win)
    except (ValueError, KeyError):
        # Teams not in training data — use league-average priors
        # (home advantage ~40%, draw ~25%, away ~35%)
        logger.warning(
            "predict_match: unknown teams '%s' vs '%s' — using league-average priors",
            home_team, away_team,
        )
        p_home, p_draw, p_away = 0.40, 0.25, 0.35

    # Sanity check: probs should sum to ~1.0
    total = p_home + p_draw + p_away
    if abs(total - 1.0) > 1e-4:
        logger.warning(
            "Dixon-Coles probabilities don't sum to 1.0 for %s vs %s: %.6f",
            home_team, away_team, total,
        )

    return {"home": p_home, "draw": p_draw, "away": p_away}


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed signal helpers (H2H + Form)
# ─────────────────────────────────────────────────────────────────────────────


def _load_all_historical(db: Session) -> list:
    """
    Load all HistoricalMatch rows sorted by date desc.
    Called once per pipeline run and shared across fixtures to avoid N full scans.
    3627 rows ≈ <2MB in memory — no concern.
    """
    return db.query(HistoricalMatch).order_by(HistoricalMatch.date.desc()).all()


def _find_team_id(all_historical: list, team_name: str) -> int | None:
    """
    Look up football-data.org team ID from pre-loaded historical matches.
    Returns None for national teams or any team not in our historical dataset.
    Uses normalized name matching (same as H2H/Form signals).
    """
    team_norm = normalize_team_name(team_name)
    for r in all_historical:
        if normalize_team_name(r.home_team_name) == team_norm:
            return r.home_team_id
        if normalize_team_name(r.away_team_name) == team_norm:
            return r.away_team_id
    return None


def _query_h2h(
    all_historical: list,
    home_team: str,
    away_team: str,
    last_n: int = 10,
) -> dict:
    """
    Compute head-to-head record from pre-loaded historical matches.

    Matches both directions (H vs A and A vs H) and normalizes team names
    for comparison. Returns empty dict if fewer than 3 H2H matches found
    (too small a sample to be meaningful).

    Returns:
        {home_wins, draws, away_wins, total_matches, avg_goals}
        where wins/losses are from home_team's perspective.
    """
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    h2h_rows = [
        r for r in all_historical
        if (
            normalize_team_name(r.home_team_name) == home_norm
            and normalize_team_name(r.away_team_name) == away_norm
        ) or (
            normalize_team_name(r.home_team_name) == away_norm
            and normalize_team_name(r.away_team_name) == home_norm
        )
    ][:last_n]

    if len(h2h_rows) < 3:
        return {}  # too small a sample

    home_wins = draws = away_wins = total_goals = 0
    for r in h2h_rows:
        total_goals += r.home_goals + r.away_goals
        if normalize_team_name(r.home_team_name) == home_norm:
            # home_team was the home side
            if r.home_goals > r.away_goals:
                home_wins += 1
            elif r.home_goals == r.away_goals:
                draws += 1
            else:
                away_wins += 1
        else:
            # home_team was playing away
            if r.away_goals > r.home_goals:
                home_wins += 1
            elif r.home_goals == r.away_goals:
                draws += 1
            else:
                away_wins += 1

    n = len(h2h_rows)
    return {
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "total_matches": n,
        "avg_goals": round(total_goals / n, 2),
    }


def _query_form(
    all_historical: list,
    team_name: str,
    last_n: int = 6,
) -> dict:
    """
    Compute recent form for a team from pre-loaded historical matches.

    Returns empty dict if fewer than 3 matches found (national teams, new clubs).

    Returns:
        {pts_per_game, goals_per_game, conceded_per_game, last_results, matches}
        where last_results is a string like "WWDLW".
    """
    team_norm = normalize_team_name(team_name)

    team_rows = [
        r for r in all_historical
        if normalize_team_name(r.home_team_name) == team_norm
        or normalize_team_name(r.away_team_name) == team_norm
    ][:last_n]

    if len(team_rows) < 3:
        return {}  # national teams / new clubs have no data

    pts = goals_scored = goals_conceded = 0
    results: list[str] = []

    for r in team_rows:
        if normalize_team_name(r.home_team_name) == team_norm:
            gf, ga = r.home_goals, r.away_goals
        else:
            gf, ga = r.away_goals, r.home_goals

        goals_scored += gf
        goals_conceded += ga

        if gf > ga:
            pts += 3
            results.append("W")
        elif gf == ga:
            pts += 1
            results.append("D")
        else:
            results.append("L")

    n = len(team_rows)
    return {
        "pts_per_game": round(pts / n, 2),
        "goals_per_game": round(goals_scored / n, 2),
        "conceded_per_game": round(goals_conceded / n, 2),
        "last_results": "".join(results),
        "matches": n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Signal computation (reasons)
# ─────────────────────────────────────────────────────────────────────────────


def _compute_signals(
    fixture: dict,
    model: pb.models.DixonColesGoalModel,
    home_team: str,
    away_team: str,
    h2h_data: dict | None = None,
    form_data_home: dict | None = None,
    form_data_away: dict | None = None,
    weather_data: dict | None = None,
    lineups_data: dict | None = None,
) -> list[dict]:
    """
    Compute all available signals for a fixture.
    Returns list of signal dicts with keys: type, value, deviation, direction, text.
    Signals that fail (missing data) are silently skipped.

    h2h_data / form_data_home / form_data_away come from _query_h2h() / _query_form().
    Pass None to skip those signals (e.g. when historical data is unavailable).
    """
    signals: list[dict] = []
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    # ── Signal 1: Home advantage index (Dixon-Coles parameters)
    try:
        params = model.params  # penaltyblog 1.5.x uses .params (dict)
        home_attack = params.get(f"attack_{home_norm}", params.get("mu", 1.0))
        away_defense = params.get(f"defence_{away_norm}", params.get("mu", 1.0))
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

    # ── Signal 2: H2H win rate (from historical_matches DB)
    if h2h_data:
        try:
            total_h2h = h2h_data.get("total_matches", 0)
            home_wins = h2h_data.get("home_wins", 0)
            avg_goals = h2h_data.get("avg_goals", 0.0)
            if total_h2h >= 3:
                h2h_rate = home_wins / total_h2h
                baseline = 0.4
                deviation = abs(h2h_rate - baseline)
                signals.append({
                    "type": "h2h",
                    "value": round(h2h_rate, 3),
                    "deviation": deviation,
                    "direction": "positive" if h2h_rate > baseline else "negative",
                    "text": (
                        f"H2H: {home_team} gana {home_wins}/{total_h2h} "
                        f"({avg_goals:.1f} goles/partido)"
                    ),
                })
        except Exception as exc:
            logger.debug("h2h signal failed: %s", exc)

    # ── Signal 3: Form delta (pts/game last 6 from historical_matches DB)
    if form_data_home and form_data_away:
        try:
            home_ppg = form_data_home.get("pts_per_game", 0.0)
            away_ppg = form_data_away.get("pts_per_game", 0.0)
            home_res = form_data_home.get("last_results", "")[:5]
            away_res = form_data_away.get("last_results", "")[:5]
            form_delta = (home_ppg - away_ppg) / 3.0  # normalize to [-1, 1]
            signals.append({
                "type": "form",
                "value": round(form_delta, 3),
                "deviation": abs(form_delta),
                "direction": "positive" if form_delta > 0 else "negative",
                "text": (
                    f"Forma: {home_team} {home_ppg:.1f}pts/j ({home_res}) "
                    f"vs {away_team} {away_ppg:.1f}pts/j ({away_res})"
                ),
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
    model: pb.models.DixonColesGoalModel,
    home_team: str,
    away_team: str,
    h2h_data: dict | None = None,
    form_data_home: dict | None = None,
    form_data_away: dict | None = None,
    weather_data: dict | None = None,
    lineups_data: dict | None = None,
    n: int = 3,
) -> list[dict]:
    """
    Select the top N signals by deviation magnitude.

    If fewer than N signals are available, returns what's available.
    H2H/Form come from DB (historical_matches). Weather/lineups from external APIs.
    Any signal without data is silently skipped.

    Returns list of reason dicts: [{type, value, direction, text}]
    """
    all_signals = _compute_signals(
        fixture, model, home_team, away_team,
        h2h_data=h2h_data,
        form_data_home=form_data_home,
        form_data_away=form_data_away,
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

    # 1. Fetch Polymarket events (primary fixture source — covers FIFA friendlies,
    #    domestic leagues, CL, J-League, A-League, MLS, etc.)
    try:
        pm_events = fetch_polymarket_events()
    except PolymarketAPIError as exc:
        logger.error("Daily pipeline: failed to fetch Polymarket events: %s", exc)
        return 0

    # 2. Polymarket-first: extract today's fixtures from Polymarket
    pm_fixtures = fetch_today_from_polymarket(pm_events=pm_events, hours_ahead=48)

    # 3. Also fetch football-data.org fixtures (covers PL/CL/etc with richer metadata)
    try:
        fd_fixtures = fetch_today_fixtures(competition_codes=TARGET_COMPETITIONS)
    except FootballDataAPIError as exc:
        logger.warning("Daily pipeline: football-data.org unavailable: %s", exc)
        fd_fixtures = []

    # 4. Merge: start with Polymarket fixtures, then add any football-data.org
    #    fixtures not already covered (dedup by normalized team name pair)
    seen: set[tuple[str, str]] = set()
    fixtures: list[dict] = []
    for f in pm_fixtures:
        key = (
            normalize_team_name(f["homeTeam"]["name"]),
            normalize_team_name(f["awayTeam"]["name"]),
        )
        seen.add(key)
        fixtures.append(f)

    for f in fd_fixtures:
        key = (
            normalize_team_name(f.get("homeTeam", {}).get("name", "")),
            normalize_team_name(f.get("awayTeam", {}).get("name", "")),
        )
        if key not in seen:
            seen.add(key)
            fixtures.append(f)

    if not fixtures:
        logger.info("Daily pipeline: no fixtures today")
        return 0

    logger.info(
        "Daily pipeline: %d total fixtures (%d from Polymarket, %d from football-data.org)",
        len(fixtures), len(pm_fixtures), len(fd_fixtures),
    )

    # 3. Fit model
    try:
        model = fit_dixon_coles(db)
    except ValueError as exc:
        logger.error("Daily pipeline: model fit failed: %s", exc)
        return 0

    # 4. Pre-load historical matches once (shared across all fixtures for H2H/Form signals)
    all_historical = _load_all_historical(db)
    logger.info("Daily pipeline: %d historical matches loaded for signal computation", len(all_historical))

    processed = 0
    for fixture in fixtures:
        try:
            _process_fixture(db, fixture, pm_events, model, all_historical=all_historical)
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
    now = datetime.now(timezone.utc)
    for match in today_matches:
        try:
            _refresh_match_snapshot(db, match, pm_events, model)
            refreshed += 1
        except Exception as exc:
            logger.error("Refresh pipeline: error refreshing match %s: %s", match.id, exc)

        # Fetch SofaScore lineup for matches within 3h of kickoff (lineups released ~1h before)
        # Only fetch if not already stored, or if lineup is missing and match is upcoming
        hours_until_kickoff = (match.kickoff_utc - now).total_seconds() / 3600
        if -1.0 <= hours_until_kickoff <= 3.0:
            if match.lineup_data is None or not match.lineup_data.get("home_starters"):
                try:
                    logger.info(
                        "Fetching SofaScore lineup for %s vs %s (%.1fh to kickoff)",
                        match.home_team, match.away_team, hours_until_kickoff,
                    )
                    lineup = fetch_lineup_for_match(
                        match.home_team, match.away_team, match.kickoff_utc
                    )
                    if lineup:
                        match.lineup_data = lineup
                        logger.info(
                            "Lineup stored for %s vs %s: %s (%d starters) vs %s (%d starters)",
                            match.home_team, match.away_team,
                            lineup.get("home_formation", "?"),
                            len(lineup.get("home_starters", [])),
                            lineup.get("away_formation", "?"),
                            len(lineup.get("away_starters", [])),
                        )
                except LineupAPIError as exc:
                    logger.warning(
                        "API-Football error — lineup unavailable for %s vs %s. "
                        "Check /health lineup_status. Error: %s",
                        match.home_team, match.away_team, exc,
                    )
                except Exception as exc:
                    logger.error(
                        "Unexpected error fetching lineup for %s vs %s: %s",
                        match.home_team, match.away_team, exc,
                    )

    db.flush()
    logger.info("=== Refresh complete: %d/%d matches updated ===", refreshed, len(today_matches))
    return refreshed


def _process_fixture(
    db: Session,
    fixture: dict,
    pm_events: list[dict],
    model,
    all_historical: list | None = None,
) -> None:
    """Process a single fixture: resolve, predict, compute signals, store."""
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

    # Resolve to Polymarket — use pre-resolved event if available (Polymarket-first fixtures)
    pm_event = fixture.get("_polymarket_event") or resolve_match(fixture, pm_events)
    if pm_event:
        match.polymarket_neg_risk_market_id = pm_event.get("negRiskMarketID")
        match.polymarket_event_slug = pm_event.get("slug")

    db.flush()  # get match.id

    # Fetch squad data if not already stored (clubs only — national teams return [])
    if match.home_squad is None or match.away_squad is None:
        api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
        home_id = _find_team_id(all_historical or [], home_team)
        away_id = _find_team_id(all_historical or [], away_team)

        home_squad = fetch_squad_for_team(home_id, api_key) if home_id else []
        if home_id and away_id:
            time.sleep(6)  # respect 10 req/min rate limit
        away_squad = fetch_squad_for_team(away_id, api_key) if away_id else []

        match.home_squad = home_squad
        match.away_squad = away_squad
        logger.info(
            "Squads fetched: %s (%d players) vs %s (%d players)",
            home_team, len(home_squad), away_team, len(away_squad),
        )

    # Compute model probabilities
    probs = predict_match(model, home_team, away_team)

    # Pre-compute H2H and Form signals from DB historical data
    # Empty dicts if no data (national teams, new clubs) — signals are skipped silently
    hist = all_historical or []
    h2h_data = _query_h2h(hist, home_team, away_team) if hist else {}
    form_data_home = _query_form(hist, home_team) if hist else {}
    form_data_away = _query_form(hist, away_team) if hist else {}

    if h2h_data:
        logger.debug(
            "H2H signal for %s vs %s: %d matches, %s home wins",
            home_team, away_team,
            h2h_data["total_matches"], h2h_data["home_wins"],
        )
    if form_data_home:
        logger.debug("Form %s: %s pts/j (%s)", home_team, form_data_home["pts_per_game"], form_data_home["last_results"])
    if form_data_away:
        logger.debug("Form %s: %s pts/j (%s)", away_team, form_data_away["pts_per_game"], form_data_away["last_results"])

    # Generate reasons (top 3 signals by deviation)
    reasons = select_reasons(
        fixture, model, home_team, away_team,
        h2h_data=h2h_data,
        form_data_home=form_data_home,
        form_data_away=form_data_away,
    )

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

"""
data_collector.py — Structured data collector for match analysis.

Gathers ALL factual data from APIs and DB (never from web scraping or Claude).
Returns a structured JSON payload ready for Claude to analyze.

Data sources:
  - Lineups: API-Football (confirmed XI)
  - Injuries: API-Football
  - Form: computed from historical_matches DB
  - H2H: computed from historical_matches DB
  - Model probabilities: from predictions table
  - Market odds: from market_snapshots table (latest)

Usage:
  data = collect_match_data(match, db)
  # data is a dict ready to pass to match_analyst_v2.analyze()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import Match, MarketSnapshot, Prediction, HistoricalMatch
from resolver.resolver import normalize_team_name

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# H2H and Form queries (extracted from pipeline.py for reuse)
# ─────────────────────────────────────────────────────────────────────────────


def query_h2h(
    db: Session,
    home_team: str,
    away_team: str,
    last_n: int = 10,
) -> list[dict]:
    """
    Compute head-to-head record from historical_matches.
    Returns list of match dicts for structured output.
    """
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    rows = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.desc())
        .all()
    )

    h2h_rows = [
        r for r in rows
        if (
            normalize_team_name(r.home_team_name) == home_norm
            and normalize_team_name(r.away_team_name) == away_norm
        ) or (
            normalize_team_name(r.home_team_name) == away_norm
            and normalize_team_name(r.away_team_name) == home_norm
        )
    ][:last_n]

    if len(h2h_rows) < 2:
        return []

    result = []
    for r in h2h_rows:
        result.append({
            "date": r.date.strftime("%Y-%m-%d") if r.date else "",
            "home": r.home_team_name,
            "away": r.away_team_name,
            "score": f"{r.home_goals}-{r.away_goals}",
            "competition": r.competition or "",
        })
    return result


def query_form(
    db: Session,
    team_name: str,
    last_n: int = 6,
) -> dict:
    """
    Compute recent form for a team from historical_matches.
    Returns structured dict with results string and stats.
    """
    team_norm = normalize_team_name(team_name)

    rows = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.desc())
        .all()
    )

    team_rows = [
        r for r in rows
        if normalize_team_name(r.home_team_name) == team_norm
        or normalize_team_name(r.away_team_name) == team_norm
    ][:last_n]

    if len(team_rows) < 3:
        return {}

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
            results.append("V")
        elif gf == ga:
            pts += 1
            results.append("E")
        else:
            results.append("D")

    n = len(team_rows)
    return {
        "results": "-".join(results),
        "pts_per_game": round(pts / n, 2),
        "goals_per_game": round(goals_scored / n, 2),
        "conceded_per_game": round(goals_conceded / n, 2),
        "matches": n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main collector
# ─────────────────────────────────────────────────────────────────────────────


def collect_match_data(match: Match, db: Session) -> dict:
    """
    Collect all structured data for a match from APIs and DB.

    Returns a dict with:
      - match: identity info
      - lineups: confirmed XI (from match.lineup_data)
      - injuries: home/away missing players
      - form: recent results for both teams
      - h2h: head-to-head history
      - model_probs: Dixon-Coles probabilities
      - market_probs: latest Polymarket odds
      - edge: delta in percentage points per outcome
    """
    # ── Match identity ─────────────────────────────────────────────────────
    match_info = {
        "home": match.home_team,
        "away": match.away_team,
        "competition": match.competition or "Unknown",
        "kickoff": match.kickoff_utc.strftime("%d %B %Y, %H:%M UTC"),
    }

    # ── Lineups (already stored in match.lineup_data by API-Football) ──────
    lineup_data = match.lineup_data or {}
    lineups = {}
    if lineup_data.get("home_starters"):
        lineups = {
            "home_formation": lineup_data.get("home_formation", ""),
            "away_formation": lineup_data.get("away_formation", ""),
            "home_xi": [p["name"] for p in lineup_data.get("home_starters", [])[:11]],
            "away_xi": [p["name"] for p in lineup_data.get("away_starters", [])[:11]],
            "home_subs": [p["name"] for p in lineup_data.get("home_subs", [])[:7]],
            "away_subs": [p["name"] for p in lineup_data.get("away_subs", [])[:7]],
            "confirmed": bool(lineup_data.get("lineup_confirmed")),
        }

    # ── Injuries (from lineup_data, already fetched by API-Football) ───────
    injuries = {
        "home_missing": lineup_data.get("home_missing", []),
        "away_missing": lineup_data.get("away_missing", []),
    }

    # ── Form ───────────────────────────────────────────────────────────────
    form_home = query_form(db, match.home_team)
    form_away = query_form(db, match.away_team)
    form = {}
    if form_home:
        form["home"] = f"{form_home['results']} · {form_home['pts_per_game']} pts/j"
    if form_away:
        form["away"] = f"{form_away['results']} · {form_away['pts_per_game']} pts/j"

    # ── H2H ────────────────────────────────────────────────────────────────
    h2h = query_h2h(db, match.home_team, match.away_team)

    # ── Model probabilities ────────────────────────────────────────────────
    prediction = (
        db.query(Prediction)
        .filter(Prediction.match_id == match.id)
        .order_by(desc(Prediction.created_at))
        .first()
    )
    model_probs = {}
    if prediction:
        model_probs = {
            "home": round(prediction.model_home_prob, 4),
            "draw": round(prediction.model_draw_prob, 4),
            "away": round(prediction.model_away_prob, 4),
        }

    # ── Market probabilities (latest snapshot) ─────────────────────────────
    market_probs = {}
    edge = {}
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
        if snapshot:
            market_probs[outcome] = round(snapshot.polymarket_prob, 4)
            if outcome in model_probs:
                delta = round((model_probs[outcome] - snapshot.polymarket_prob) * 100, 1)
                edge[outcome] = f"{'+' if delta > 0 else ''}{delta}pp"

    return {
        "match": match_info,
        "lineups": lineups,
        "injuries": injuries,
        "form": form,
        "h2h": h2h,
        "model_probs": model_probs,
        "market_probs": market_probs,
        "edge": edge,
    }

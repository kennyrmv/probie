"""
api_football.py — Real-time lineup data via API-Football (api-sports.io).

Free tier: 100 req/day, no credit card required.
Sign up at: https://dashboard.api-football.com/register
Set env var: API_FOOTBALL_KEY=your_key

Endpoints used:
  GET /fixtures?date=YYYY-MM-DD&timezone=UTC   — today's fixtures (with IDs)
  GET /fixtures/lineups?fixture={id}           — confirmed starting XI
  GET /injuries?fixture={id}                   — injured/suspended players
                                                 (requires Pro plan — silently skipped on free)

Block detection (same interface as sofascore.py):
  - On key missing, rate-limit exceeded, or any API error
  - Writes {"status": "blocked" | "ok"} to .lineup_state.json
  - /health endpoint exposes lineup_status
  - Frontend shows amber warning banner when blocked
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / ".lineup_state.json"

API_BASE = "https://v3.football.api-sports.io"
FUZZY_THRESHOLD = 72
WINDOW_MINUTES = 90

# In-memory fixture cache: {date_str: (timestamp, fixtures_list)}
# Avoids burning API requests by re-fetching the same day's fixtures
_fixture_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


class LineupAPIError(Exception):
    """Raised when the lineup API is unavailable or returns an error."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────


def _update_state(status: str, detail: str = "") -> None:
    data: dict = {
        "status": status,
        "last_check": datetime.now(timezone.utc).isoformat(),
    }
    if status != "ok":
        data["detail"] = detail
    try:
        STATE_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.warning("Failed to write lineup state file: %s", exc)


def read_lineup_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"status": "unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP client
# ─────────────────────────────────────────────────────────────────────────────


def _get_api_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if not key:
        raise LineupAPIError("API_FOOTBALL_KEY not set in environment")
    return key


def _request(path: str, params: dict | None = None) -> dict:
    """
    Make a GET request to API-Football.
    Raises LineupAPIError on auth failure, rate limit, or network error.
    """
    key = _get_api_key()
    headers = {
        "x-rapidapi-key": key,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    url = f"{API_BASE}{path}"
    try:
        resp = httpx.get(url, headers=headers, params=params or {}, timeout=15.0)
    except httpx.RequestError as exc:
        raise LineupAPIError(f"Network error: {exc}") from exc

    if resp.status_code == 401:
        raise LineupAPIError("API key invalid or expired (401)")
    if resp.status_code == 429:
        raise LineupAPIError("Rate limit exceeded (429) — 100 req/day on free tier")
    if resp.status_code != 200:
        raise LineupAPIError(f"API error HTTP {resp.status_code}")

    data = resp.json()

    # API-Football returns errors in the response body even on 200
    errors = data.get("errors", {})
    if errors:
        msg = str(errors)
        raise LineupAPIError(f"API-Football error: {msg}")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Name normalization
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    nfd = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped.lower().strip())


# ─────────────────────────────────────────────────────────────────────────────
# API wrappers
# ─────────────────────────────────────────────────────────────────────────────


def fetch_fixtures_for_date(date_str: str) -> list[dict]:
    """
    Fetch all football fixtures for a date (YYYY-MM-DD).
    Returns list of fixture response dicts.
    Uses in-memory cache (5 min TTL) to avoid burning API requests.
    """
    import time as _time
    now = _time.time()
    cached = _fixture_cache.get(date_str)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        logger.debug("API-Football fixtures cache hit for %s", date_str)
        return cached[1]

    data = _request("/fixtures", {"date": date_str, "timezone": "UTC"})
    fixtures = data.get("response", [])
    _fixture_cache[date_str] = (now, fixtures)
    return fixtures


def find_fixture(
    fixtures: list[dict],
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
) -> Optional[dict]:
    """
    Fuzzy-match our match against API-Football fixtures.
    Returns the best matching fixture dict, or None.
    """
    home_norm = _normalize(home_team)
    away_norm = _normalize(away_team)
    kickoff_ts = kickoff_dt.timestamp()

    best_score = 0.0
    best_fixture: Optional[dict] = None

    for fix in fixtures:
        teams = fix.get("teams", {})
        fix_home = _normalize(teams.get("home", {}).get("name", ""))
        fix_away = _normalize(teams.get("away", {}).get("name", ""))

        # Time window check
        fix_ts = fix.get("fixture", {}).get("timestamp", 0)
        if abs(fix_ts - kickoff_ts) > WINDOW_MINUTES * 60:
            continue

        home_score = fuzz.partial_ratio(home_norm, fix_home)
        away_score = fuzz.partial_ratio(away_norm, fix_away)
        avg = (home_score + away_score) / 2.0

        if avg > best_score and avg >= FUZZY_THRESHOLD:
            best_score = avg
            best_fixture = fix

    if best_fixture:
        fix_id = best_fixture.get("fixture", {}).get("id")
        logger.debug(
            "API-Football match: %s vs %s → fixture_id=%s (score=%.0f)",
            home_team, away_team, fix_id, best_score,
        )
    else:
        logger.debug("API-Football: no fixture found for %s vs %s", home_team, away_team)

    return best_fixture


def fetch_lineup(fixture_id: int) -> dict:
    """
    Fetch confirmed lineup for a fixture.
    Returns dict with formations + starters + subs, or {} if not yet confirmed.
    """
    data = _request("/fixtures/lineups", {"fixture": fixture_id})
    teams = data.get("response", [])

    if not teams:
        logger.debug("API-Football: no lineup yet for fixture %d", fixture_id)
        return {}

    def parse_side(side: dict) -> tuple[str, list[dict], list[dict]]:
        formation = side.get("formation", "")
        starters = [
            {
                "name": p["player"]["name"],
                "position": p["player"].get("pos", ""),
                "jersey": str(p["player"].get("number", "")),
            }
            for p in side.get("startXI", [])
        ]
        subs = [
            {
                "name": p["player"]["name"],
                "position": p["player"].get("pos", ""),
                "jersey": str(p["player"].get("number", "")),
            }
            for p in side.get("substitutes", [])
        ]
        return formation, starters, subs

    home_side = teams[0] if len(teams) > 0 else {}
    away_side = teams[1] if len(teams) > 1 else {}

    home_formation, home_starters, home_subs = parse_side(home_side)
    away_formation, away_starters, away_subs = parse_side(away_side)

    if not home_starters and not away_starters:
        return {}

    return {
        "home_formation": home_formation,
        "away_formation": away_formation,
        "home_starters": home_starters,
        "home_subs": home_subs,
        "away_starters": away_starters,
        "away_subs": away_subs,
    }


def fetch_injuries(fixture_id: int, home_team_id: int | None = None) -> dict:
    """
    Fetch injured/suspended players for a fixture.
    Returns {"home_missing": [...], "away_missing": [...]}.
    Silently returns empty on free plan (403 from API).

    Args:
        fixture_id: API-Football fixture ID
        home_team_id: API-Football team ID for the home side.
            Used to separate injuries into home/away buckets.
            If None, all injuries go into home_missing (legacy behavior).
    """
    try:
        data = _request("/injuries", {"fixture": fixture_id})
    except LineupAPIError as exc:
        # Injuries endpoint requires a paid plan — not a hard error
        logger.debug("Injuries not available for fixture %d: %s", fixture_id, exc)
        return {"home_missing": [], "away_missing": []}

    home_missing: list[dict] = []
    away_missing: list[dict] = []

    for entry in data.get("response", []):
        player = entry.get("player", {})
        team = entry.get("team", {})
        reason = player.get("reason", "Baja")
        item = {
            "name": player.get("name", ""),
            "reason": reason,
            "type": "missing",
        }
        team_id = team.get("id")
        if home_team_id is not None and team_id is not None:
            if team_id == home_team_id:
                home_missing.append(item)
            else:
                away_missing.append(item)
        else:
            # Fallback: can't determine side — put all under home
            home_missing.append(item)

    return {"home_missing": home_missing, "away_missing": away_missing}


# ─────────────────────────────────────────────────────────────────────────────
# High-level entry point (same interface as sofascore.py)
# ─────────────────────────────────────────────────────────────────────────────


def fetch_lineup_for_match(
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
) -> Optional[dict]:
    """
    Full pipeline: find the API-Football fixture + fetch lineup + injuries.

    Returns dict with: source, fetched_at, api_fixture_id,
                       home_formation, away_formation,
                       home_starters, home_subs, away_starters, away_subs,
                       home_missing, away_missing
    Returns None if API key missing, rate-limited, fixture not found,
                  or lineup not yet confirmed.
    """
    date_str = kickoff_dt.strftime("%Y-%m-%d")

    try:
        fixtures = fetch_fixtures_for_date(date_str)
        _update_state("ok")
    except LineupAPIError as exc:
        logger.warning("API-Football unavailable: %s", exc)
        _update_state("error", str(exc))
        return None
    except Exception as exc:
        logger.error("Unexpected error fetching fixtures: %s", exc)
        _update_state("error", str(exc))
        return None

    fixture = find_fixture(fixtures, home_team, away_team, kickoff_dt)
    if not fixture:
        return None

    fixture_id: int = fixture["fixture"]["id"]

    try:
        lineup = fetch_lineup(fixture_id)
        _update_state("ok")
    except LineupAPIError as exc:
        logger.warning("API-Football lineup fetch failed for fixture %d: %s", fixture_id, exc)
        _update_state("error", str(exc))
        return None
    except Exception as exc:
        logger.error("Unexpected error fetching lineup %d: %s", fixture_id, exc)
        return None

    if not lineup:
        return None  # Not yet confirmed

    # Extract home team ID from the fixture for correct injury assignment
    home_team_id = fixture.get("teams", {}).get("home", {}).get("id")
    injuries = fetch_injuries(fixture_id, home_team_id=home_team_id)

    return {
        "source": "api-football",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "api_fixture_id": fixture_id,
        "lineup_confirmed": True,   # API-Football only publishes official confirmed lineups
        "source_type": "official",  # never speculative — API requires team to submit
        **lineup,
        **injuries,
    }

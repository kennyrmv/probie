"""
resolver.py — Polymarket ↔ football-data.org match resolver for EdgeFút.

Critical rules (from eng review):
  - Use gameStartTime (NOT endDate) for timestamp matching
  - outcomePrices is a JSON string → must json.loads() it
  - Always filter closed=false on Polymarket API calls
  - Fuzzy match threshold: >85% similarity (rapidfuzz)
  - Aliases table loaded from aliases.json (handles "Man Utd" → "manchester united")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

POLYMARKET_BASE = "https://gamma-api.polymarket.com"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
FUZZY_THRESHOLD = 85  # minimum similarity score (0–100) to accept a match
TIMESTAMP_WINDOW_MINUTES = 90  # ±90 min around Polymarket gameStartTime

ALIASES_PATH = Path(__file__).parent / "aliases.json"


def _normalize_value(v: str) -> str:
    """Pre-normalize alias values (same pipeline minus alias lookup)."""
    nfd = unicodedata.normalize("NFD", v)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    cleaned = re.sub(r"\s+", " ", stripped.lower().strip())
    return re.sub(r"[^\w\s]", "", cleaned)


_ALIASES_RAW: dict[str, str] = json.loads(ALIASES_PATH.read_text()) if ALIASES_PATH.exists() else {}
# Pre-normalize alias values so comparisons are consistent
_ALIASES: dict[str, str] = {k: _normalize_value(v) for k, v in _ALIASES_RAW.items()}

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class PolymarketAPIError(Exception):
    """Raised when the Polymarket Gamma API returns an error or times out."""


class FootballDataAPIError(Exception):
    """Raised when the football-data.org API returns an error or times out."""


# ─────────────────────────────────────────────────────────────────────────────
# Team name normalization
# ─────────────────────────────────────────────────────────────────────────────


def normalize_team_name(name: str) -> str:
    """
    Canonical team name normalization pipeline:
      1. Validate input (None → ValueError, empty → "")
      2. Unicode normalize → strip accents
      3. Lowercase + strip whitespace
      4. Remove punctuation (except spaces)
      5. Apply aliases table (e.g. "man utd" → "manchester united")

    Examples:
      "Atlético Madrid"  → "atletico madrid"
      "Manchester City"  → "manchester city"
      "Man Utd"          → "manchester united"
      ""                 → ""
      None               → raises ValueError
    """
    if name is None:
        raise ValueError("normalize_team_name: name must not be None")

    if not name:
        return ""

    # Strip accents
    normalized = unicodedata.normalize("NFD", name)
    without_accents = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Lowercase, strip, collapse whitespace
    cleaned = re.sub(r"\s+", " ", without_accents.lower().strip())

    # Remove punctuation except spaces
    cleaned = re.sub(r"[^\w\s]", "", cleaned)

    # Apply alias lookup
    return _ALIASES.get(cleaned, cleaned)


# ─────────────────────────────────────────────────────────────────────────────
# Polymarket API
# ─────────────────────────────────────────────────────────────────────────────


def fetch_polymarket_events(
    tag_slug: str = "soccer",
    limit: int = 100,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[dict]:
    """
    Fetch active, non-closed Polymarket events for the given tag slug.

    Key filter: closed=false — active=true alone returns resolved/closed markets.
    outcomePrices is a JSON string on each market; consumers must json.loads() it.

    Raises:
        PolymarketAPIError: on network timeout or non-200 after retries.
    """
    url = f"{POLYMARKET_BASE}/events"
    params = {
        "tag_slug": tag_slug,
        "active": "true",
        "closed": "false",  # CRITICAL: active=true alone returns closed markets too
        "limit": limit,
    }

    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params=params)

            if resp.status_code == 429:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Polymarket API rate limited (429). Retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
                continue

            if resp.status_code != 200:
                raise PolymarketAPIError(
                    f"Polymarket API returned {resp.status_code}: {resp.text[:200]}"
                )

            events = resp.json()
            logger.info("Fetched %d Polymarket events (tag=%s)", len(events), tag_slug)
            return events

        except httpx.TimeoutException as exc:
            if attempt == max_retries - 1:
                raise PolymarketAPIError(
                    f"Polymarket API timed out after {max_retries} attempts"
                ) from exc
            delay = base_delay * (2 ** attempt)
            logger.warning("Polymarket API timeout. Retrying in %.1fs", delay)
            time.sleep(delay)

        except httpx.RequestError as exc:
            raise PolymarketAPIError(f"Polymarket network error: {exc}") from exc

    raise PolymarketAPIError("Polymarket API: max retries exceeded")


def get_implied_prob(event: dict, outcome: str) -> float:
    """
    Extract implied probability for a specific outcome from a Polymarket event.

    outcome: "home" | "draw" | "away"
    Uses groupItemTitle to find the correct sub-market.
    outcomePrices is a JSON string — uses json.loads(), not direct indexing.

    Raises:
        ValueError: if the outcome market is not found in the event.
    """
    markets = event.get("markets", [])
    outcome_lower = outcome.lower()

    # Map outcome labels to what Polymarket uses in groupItemTitle
    # groupItemTitle format varies: "Arsenal", "Draw", "Chelsea", etc.
    # For "home"/"away" we match against team names stored elsewhere in the event;
    # for "draw" we match the literal word "draw".
    if outcome_lower == "draw":
        target_keywords = ["draw"]
    elif outcome_lower == "home":
        # The home team name is in the event question, e.g. "Will Arsenal win?"
        # Pull it from event.question or fall back to checking market position
        target_keywords = ["home", "1"]  # common Polymarket conventions
    elif outcome_lower == "away":
        target_keywords = ["away", "2"]
    else:
        raise ValueError(f"Unknown outcome '{outcome}'. Must be 'home', 'draw', or 'away'.")

    for market in markets:
        group_title = (market.get("groupItemTitle") or "").lower()

        if outcome_lower == "draw" and any(kw in group_title for kw in target_keywords):
            prices_raw = market.get("outcomePrices")
            if prices_raw is None:
                raise ValueError(f"Market has no outcomePrices: {market.get('id')}")
            prices = json.loads(prices_raw)
            return float(prices[0])  # index 0 = "Yes" probability

    # If keyword match fails, raise with context
    raise ValueError(
        f"Outcome '{outcome}' not found in event '{event.get('slug')}'. "
        f"Available groupItemTitles: {[m.get('groupItemTitle') for m in markets]}"
    )


def get_all_outcome_probs(event: dict, home_team: str, away_team: str) -> dict[str, float]:
    """
    Extract home/draw/away implied probabilities from a Polymarket event.

    Matches sub-markets by team name (fuzzy) for home/away,
    and by "draw" keyword for the draw market.

    Returns dict with keys "home", "draw", "away" → float probability.
    Raises ValueError if any outcome can't be found.
    """
    markets = event.get("markets", [])
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    result: dict[str, float] = {}

    for market in markets:
        group_title = normalize_team_name(market.get("groupItemTitle") or "")
        prices_raw = market.get("outcomePrices")
        if not prices_raw:
            continue
        prices = json.loads(prices_raw)
        prob = float(prices[0])

        if "draw" in group_title:
            result["draw"] = prob
        elif max(fuzz.partial_ratio(group_title, home_norm),
                 fuzz.token_set_ratio(group_title, home_norm)) >= FUZZY_THRESHOLD:
            result["home"] = prob
        elif max(fuzz.partial_ratio(group_title, away_norm),
                 fuzz.token_set_ratio(group_title, away_norm)) >= FUZZY_THRESHOLD:
            result["away"] = prob

    missing = [k for k in ("home", "draw", "away") if k not in result]
    if missing:
        raise ValueError(
            f"Could not find outcomes {missing} for {home_team} vs {away_team} "
            f"in event '{event.get('slug')}'. "
            f"groupItemTitles: {[m.get('groupItemTitle') for m in markets]}"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# football-data.org API
# ─────────────────────────────────────────────────────────────────────────────


def fetch_today_fixtures(
    competition_codes: list[str] | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """
    Fetch today's fixtures from football-data.org.
    competition_codes: e.g. ["PL", "PD", "SA", "BL1", "FL1", "UCL"]
    api_key: reads from FOOTBALL_DATA_API_KEY env var if not provided.

    Returns list of fixture dicts with standardized fields.
    Raises FootballDataAPIError on failure.
    """
    key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key} if key else {}

    today = datetime.now(timezone.utc).date().isoformat()
    url = f"{FOOTBALL_DATA_BASE}/matches"
    params: dict = {"dateFrom": today, "dateTo": today, "status": "SCHEDULED,TIMED"}
    if competition_codes:
        params["competitions"] = ",".join(competition_codes)

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            raise FootballDataAPIError(
                f"football-data.org returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        matches = data.get("matches", [])
        logger.info("Fetched %d fixtures for today (%s)", len(matches), today)
        return matches
    except httpx.TimeoutException as exc:
        raise FootballDataAPIError("football-data.org timed out") from exc
    except httpx.RequestError as exc:
        raise FootballDataAPIError(f"football-data.org network error: {exc}") from exc


def fetch_historical_matches(
    competition_code: str,
    season: int,
    api_key: str | None = None,
) -> list[dict]:
    """
    Fetch all finished matches for a competition/season from football-data.org.
    Used by pipeline.py seed_historical_data().

    competition_code: e.g. "PL" (Premier League)
    season: e.g. 2023 (for 2023-24 season)
    """
    key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key} if key else {}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{competition_code}/matches"
    params = {"season": season, "status": "FINISHED"}

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            raise FootballDataAPIError(
                f"football-data.org returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        matches = data.get("matches", [])
        logger.info(
            "Fetched %d historical matches (competition=%s, season=%d)",
            len(matches), competition_code, season,
        )
        return matches
    except httpx.TimeoutException as exc:
        raise FootballDataAPIError(
            f"football-data.org timed out fetching {competition_code}/{season}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Match resolver: football-data.org fixture ↔ Polymarket event
# ─────────────────────────────────────────────────────────────────────────────


def _parse_polymarket_title(title: str) -> tuple[str, str] | None:
    """
    Extract team names from Polymarket event title.
    Handles: "Arsenal vs Chelsea", "Will Arsenal beat Chelsea?", etc.
    Returns (home, away) or None if unparseable.
    """
    # Primary pattern: "TeamA vs TeamB"
    match = re.search(r"([A-Z][^v]+?)\s+vs\.?\s+([A-Z][^\?]+)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Secondary: "Will [TeamA] beat/win against [TeamB]"
    match = re.search(
        r"[Ww]ill\s+(.+?)\s+(?:beat|win against|defeat)\s+(.+?)[\?\.]",
        title,
    )
    if match:
        return match.group(1).strip(), match.group(2).strip()

    return None


def resolve_match(
    fixture: dict,
    polymarket_events: list[dict],
) -> dict | None:
    """
    Match a football-data.org fixture to a Polymarket event.

    Algorithm:
      1. Extract home/away team names from fixture
      2. For each Polymarket event, extract team names from title
      3. Fuzzy match both team names (threshold >85%)
      4. Timestamp gate: Polymarket gameStartTime within ±90 min of fixture kickoff
      5. If multiple candidates, pick closest by timestamp
      6. Returns the matched Polymarket event dict, or None with a warning

    CRITICAL: Uses gameStartTime (NOT endDate) for timestamp matching.
    endDate is market close time (typically 2h before kickoff).
    """
    # Extract fixture team names
    home_raw = (
        fixture.get("homeTeam", {}).get("name")
        or fixture.get("home_team")
        or ""
    )
    away_raw = (
        fixture.get("awayTeam", {}).get("name")
        or fixture.get("away_team")
        or ""
    )
    if not home_raw or not away_raw:
        logger.warning("resolve_match: fixture missing team names: %s", fixture.get("id"))
        return None

    home_norm = normalize_team_name(home_raw)
    away_norm = normalize_team_name(away_raw)

    # Parse fixture kickoff time
    kickoff_str = (
        fixture.get("utcDate")
        or fixture.get("kickoff_utc")
        or fixture.get("kickoff")
        or ""
    )
    if not kickoff_str:
        logger.warning("resolve_match: fixture missing kickoff time: %s", fixture.get("id"))
        return None

    try:
        kickoff_dt = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("resolve_match: unparseable kickoff '%s'", kickoff_str)
        return None

    window_start = kickoff_dt - timedelta(minutes=TIMESTAMP_WINDOW_MINUTES)
    window_end = kickoff_dt + timedelta(minutes=TIMESTAMP_WINDOW_MINUTES)

    candidates: list[tuple[dict, float]] = []  # (event, time_delta_seconds)

    for event in polymarket_events:
        title = event.get("title") or event.get("question") or ""
        teams = _parse_polymarket_title(title)
        if teams is None:
            continue

        pm_home_norm = normalize_team_name(teams[0])
        pm_away_norm = normalize_team_name(teams[1])

        # Both team names must fuzzy-match above threshold.
        # Use partial_ratio so "Arsenal FC" matches "Arsenal" (100%)
        # and token_set_ratio as fallback for rearranged tokens.
        home_score = max(fuzz.partial_ratio(home_norm, pm_home_norm),
                         fuzz.token_set_ratio(home_norm, pm_home_norm))
        away_score = max(fuzz.partial_ratio(away_norm, pm_away_norm),
                         fuzz.token_set_ratio(away_norm, pm_away_norm))

        if home_score < FUZZY_THRESHOLD or away_score < FUZZY_THRESHOLD:
            continue

        # Timestamp gate: use gameStartTime (NOT endDate)
        game_start_str = event.get("gameStartTime") or event.get("game_start_time") or ""
        if not game_start_str:
            logger.debug(
                "resolve_match: event '%s' has no gameStartTime — skipping timestamp check",
                event.get("slug"),
            )
            continue

        try:
            game_start_dt = datetime.fromisoformat(
                game_start_str.replace("Z", "+00:00")
            )
        except ValueError:
            logger.debug(
                "resolve_match: unparseable gameStartTime '%s' for event '%s'",
                game_start_str, event.get("slug"),
            )
            continue

        if not (window_start <= game_start_dt <= window_end):
            continue

        delta_seconds = abs((game_start_dt - kickoff_dt).total_seconds())
        candidates.append((event, delta_seconds))

    if not candidates:
        logger.warning(
            "resolve_match: no Polymarket event found for %s vs %s (kickoff %s)",
            home_raw, away_raw, kickoff_str,
        )
        return None

    # Pick the closest match by timestamp
    candidates.sort(key=lambda x: x[1])
    best_event, best_delta = candidates[0]

    logger.info(
        "resolve_match: matched '%s vs %s' → Polymarket '%s' (Δt=%.0fs)",
        home_raw, away_raw, best_event.get("slug"), best_delta,
    )
    return best_event

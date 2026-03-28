"""
sofascore.py — Real-time lineup + missing player data from SofaScore.

SofaScore uses Cloudflare challenge mode which blocks standard HTTP requests.
We bypass it with Playwright (headless Chromium with stealth patches).

Block detection:
  - If Cloudflare challenge is detected (403 / {"error": {"code": 403}})
  - Write {"status": "blocked", "blocked_at": "..."} to .sofascore_state.json
  - The /health endpoint reads this file and exposes sofascore_status
  - The frontend polls /health and shows a warning banner when blocked

Install:
  pip install playwright playwright-stealth
  playwright install chromium

Usage:
  from resolver.sofascore import fetch_lineup_for_match
  lineup = fetch_lineup_for_match(home_team, away_team, kickoff_dt)
  # Returns None if blocked or lineup not yet confirmed
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# State file — read by /health endpoint to expose sofascore_status
STATE_FILE = Path(__file__).parent.parent / ".sofascore_state.json"

# Primary API base (direct API subdomain)
SOFASCORE_BASE = "https://api.sofascore.com/api/v1"
# Fallback base — same API served through the main domain (what the website JS uses)
SOFASCORE_WWW_BASE = "https://www.sofascore.com/api/v1"
FUZZY_THRESHOLD = 72     # lower than Polymarket resolver — SS names diverge more
WINDOW_MINUTES = 90      # ±90 min around our kickoff time


class SofaScoreBlockedError(Exception):
    """Raised when SofaScore blocks our request (Cloudflare challenge)."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# State management
# ─────────────────────────────────────────────────────────────────────────────


def _update_state(status: str) -> None:
    """Persist SofaScore connectivity status. Called after every request."""
    data: dict = {
        "status": status,  # "ok" | "blocked"
        "last_check": datetime.now(timezone.utc).isoformat(),
    }
    if status == "blocked":
        data["blocked_at"] = data["last_check"]
    try:
        STATE_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.warning("Failed to write SofaScore state file: %s", exc)


def read_sofascore_state() -> dict:
    """
    Read SofaScore connectivity state.
    Returns {"status": "unknown"} if state file doesn't exist yet.
    """
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"status": "unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# Playwright fetch (Cloudflare bypass)
# ─────────────────────────────────────────────────────────────────────────────


def _playwright_fetch(url: str) -> dict:
    """
    Fetch a SofaScore JSON URL via Playwright headless Chromium.
    Uses playwright-stealth to evade bot detection and solve Cloudflare JS challenge.

    Raises:
        SofaScoreBlockedError — still blocked after JS challenge execution
        ImportError           — playwright / playwright-stealth not installed
    """
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError:
        raise ImportError(
            "playwright and playwright-stealth are required. "
            "Run: pip install playwright playwright-stealth && playwright install chromium"
        )

    stealth = Stealth()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()
        stealth.apply_stealth_sync(page)

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if response is None:
                raise SofaScoreBlockedError("No response received from SofaScore")

            status_code = response.status
            content = page.content()

            # Detect Cloudflare JS challenge
            cloudflare_signals = (
                status_code == 403
                or "cf-browser-verification" in content
                or "Just a moment" in content
                or "Checking if the site connection is secure" in content
            )
            if cloudflare_signals:
                raise SofaScoreBlockedError(
                    f"Cloudflare challenge not solved (HTTP {status_code})"
                )

            # Extract JSON — SofaScore API endpoints return raw JSON
            body = page.evaluate("document.body.innerText")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                # Occasionally wrapped in <pre> tags
                pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", content, re.DOTALL)
                if pre_match:
                    data = json.loads(pre_match.group(1))
                else:
                    raise SofaScoreBlockedError("Could not parse JSON from SofaScore response")

            # Check for SofaScore-level 403 error
            if isinstance(data, dict) and isinstance(data.get("error"), dict):
                err = data["error"]
                if err.get("code") == 403:
                    raise SofaScoreBlockedError(
                        f"SofaScore API error: {err.get('reason', 'blocked')}"
                    )

            return data

        finally:
            browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Name normalization
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    """Normalize team name for fuzzy matching (accent-strip, lowercase)."""
    nfd = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped.lower().strip())


# ─────────────────────────────────────────────────────────────────────────────
# SofaScore API wrappers
# ─────────────────────────────────────────────────────────────────────────────


def fetch_sofascore_events(date: str) -> list[dict]:
    """
    Fetch all football events scheduled for a date (YYYY-MM-DD).
    Returns list of event dicts. Raises SofaScoreBlockedError if blocked.

    NOTE: SofaScore aggressively guards its API against non-residential IPs.
    In production, a residential proxy may be required. The block is detected
    and written to .sofascore_state.json so the frontend can show a warning.
    """
    # Try primary API subdomain, fall back to www subdomain (same data, different host)
    for base in (SOFASCORE_BASE, SOFASCORE_WWW_BASE):
        url = f"{base}/sport/football/scheduled-events/{date}"
        try:
            data = _playwright_fetch(url)
            _update_state("ok")
            return data.get("events", [])
        except SofaScoreBlockedError:
            continue

    _update_state("blocked")
    raise SofaScoreBlockedError("SofaScore blocked on both api.sofascore.com and www.sofascore.com")


def find_sofascore_event(
    events: list[dict],
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
) -> Optional[dict]:
    """
    Fuzzy-match our fixture against SofaScore events by team names + kickoff time.
    Returns the best matching event dict, or None if no match above threshold.
    """
    home_norm = _normalize(home_team)
    away_norm = _normalize(away_team)
    kickoff_ts = kickoff_dt.timestamp()

    best_score = 0.0
    best_event: Optional[dict] = None

    for event in events:
        # Time window filter
        event_ts = event.get("startTimestamp", 0)
        if abs(event_ts - kickoff_ts) > WINDOW_MINUTES * 60:
            continue

        ev_home = _normalize(event.get("homeTeam", {}).get("name", ""))
        ev_away = _normalize(event.get("awayTeam", {}).get("name", ""))

        home_score = fuzz.partial_ratio(home_norm, ev_home)
        away_score = fuzz.partial_ratio(away_norm, ev_away)
        avg_score = (home_score + away_score) / 2.0

        if avg_score > best_score and avg_score >= FUZZY_THRESHOLD:
            best_score = avg_score
            best_event = event

    if best_event:
        logger.debug(
            "SofaScore match found: %s vs %s → event_id=%s (score=%.0f)",
            home_team, away_team, best_event.get("id"), best_score,
        )
    else:
        logger.debug("SofaScore: no event for %s vs %s", home_team, away_team)

    return best_event


def fetch_sofascore_lineup(event_id: int) -> dict:
    """
    Fetch confirmed starting lineup for a SofaScore event.

    Returns:
        dict with home_formation, away_formation, home_starters, home_subs,
             away_starters, away_subs — if lineup is confirmed
        {}   if lineup not yet released (pre-match)
    Raises SofaScoreBlockedError if request is blocked.
    """
    url = f"{SOFASCORE_BASE}/event/{event_id}/lineups"
    try:
        data = _playwright_fetch(url)
        _update_state("ok")
    except SofaScoreBlockedError:
        _update_state("blocked")
        raise

    # "confirmed" field is True when the official lineup is released
    if not data.get("confirmed", False):
        logger.debug("SofaScore lineup not yet confirmed for event %d", event_id)
        return {}

    def parse_side(side: dict) -> tuple[list[dict], list[dict]]:
        starters: list[dict] = []
        subs: list[dict] = []
        for p in side.get("players", []):
            player = p.get("player", {})
            entry = {
                "name": player.get("name", ""),
                "position": p.get("position", ""),
                "jersey": str(p.get("jerseyNumber", "")),
            }
            if p.get("substitute", False):
                subs.append(entry)
            else:
                starters.append(entry)
        return starters, subs

    home_data = data.get("home", {})
    away_data = data.get("away", {})
    home_starters, home_subs = parse_side(home_data)
    away_starters, away_subs = parse_side(away_data)

    return {
        "home_formation": home_data.get("formation", ""),
        "away_formation": away_data.get("formation", ""),
        "home_starters": home_starters,
        "home_subs": home_subs,
        "away_starters": away_starters,
        "away_subs": away_subs,
    }


def fetch_sofascore_missing_players(event_id: int) -> dict:
    """
    Fetch missing players (injuries, suspensions) for a SofaScore event.
    Returns {"home_missing": [...], "away_missing": [...]}.
    Each entry: {"name": str, "reason": str, "type": str}
    Raises SofaScoreBlockedError if blocked.
    """
    url = f"{SOFASCORE_BASE}/event/{event_id}/missing-players"
    try:
        data = _playwright_fetch(url)
        _update_state("ok")
    except SofaScoreBlockedError:
        _update_state("blocked")
        raise

    def parse_side(side: dict) -> list[dict]:
        result = []
        for entry in side.get("missingPlayers", []):
            player = entry.get("player", {})
            reason_obj = entry.get("reason", {})
            result.append({
                "name": player.get("name", ""),
                "reason": reason_obj.get("name", "Baja"),
                "type": entry.get("type", "missing"),
            })
        return result

    return {
        "home_missing": parse_side(data.get("home", {})),
        "away_missing": parse_side(data.get("away", {})),
    }


# ─────────────────────────────────────────────────────────────────────────────
# High-level entry point
# ─────────────────────────────────────────────────────────────────────────────


def fetch_lineup_for_match(
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
) -> Optional[dict]:
    """
    Full pipeline: find the SofaScore event + fetch lineup + missing players.

    Returns:
        dict with keys: source, fetched_at, sofascore_event_id,
                        home_formation, away_formation,
                        home_starters, home_subs, away_starters, away_subs,
                        home_missing, away_missing
        None  — if SofaScore is blocked, event not found, or lineup not yet confirmed
    """
    date_str = kickoff_dt.strftime("%Y-%m-%d")

    try:
        events = fetch_sofascore_events(date_str)
    except SofaScoreBlockedError as exc:
        logger.warning("SofaScore blocked fetching events for %s: %s", date_str, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error fetching SofaScore events: %s", exc)
        return None

    event = find_sofascore_event(events, home_team, away_team, kickoff_dt)
    if not event:
        return None

    event_id: int = event["id"]

    try:
        lineup = fetch_sofascore_lineup(event_id)
    except SofaScoreBlockedError as exc:
        logger.warning("SofaScore blocked fetching lineup for event %d: %s", event_id, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error fetching lineup for event %d: %s", event_id, exc)
        return None

    if not lineup:
        return None  # Lineup not yet confirmed

    try:
        missing = fetch_sofascore_missing_players(event_id)
    except SofaScoreBlockedError:
        # Missing players is nice-to-have — don't block on it
        missing = {"home_missing": [], "away_missing": []}
    except Exception as exc:
        logger.warning("Failed to fetch missing players for event %d: %s", event_id, exc)
        missing = {"home_missing": [], "away_missing": []}

    return {
        "source": "sofascore",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sofascore_event_id": event_id,
        **lineup,
        **missing,
    }

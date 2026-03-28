"""
claude_lineup.py — Lineup fetcher using DuckDuckGo + Claude.

Fallback when API_FOOTBALL_KEY is not available.
Same interface as api_football.fetch_lineup_for_match().

Flow:
  1. Run 3 targeted DuckDuckGo searches for confirmed lineup
  2. Pass results to Claude for structured extraction
  3. Return dict with home/away starters, subs, formations

Returns None if lineup is not yet confirmed or can't be found.
Requires: ANTHROPIC_API_KEY in environment
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"


def _search(query: str, max_results: int = 5) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for '%s': %s", query, exc)
        return []


def _gather_lineup_results(home_team: str, away_team: str, kickoff_dt: datetime) -> str:
    date_str = kickoff_dt.strftime("%Y-%m-%d")
    queries = [
        f"{home_team} vs {away_team} confirmed starting lineup XI {date_str}",
        f"{home_team} starting eleven formation {date_str}",
        f"{away_team} starting eleven formation {date_str}",
    ]

    all_results: list[str] = []
    for query in queries:
        results = _search(query, max_results=5)
        if not results:
            continue
        all_results.append(f"\n--- {query} ---")
        for r in results:
            all_results.append(f"[{r['title']}] ({r['url']})")
            if r["snippet"]:
                all_results.append(r["snippet"][:400])

    return "\n".join(all_results) if all_results else ""


SYSTEM_PROMPT = """You are a football lineup extraction specialist.
Extract starting XI and formation from web search results.
Respond ONLY with the requested JSON. No extra text.
Player names should be in their most common English/international form."""


def _extract_with_claude(
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
    raw_results: str,
) -> Optional[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    kickoff_str = kickoff_dt.strftime("%d %B %Y %H:%M UTC")

    prompt = f"""Match: {home_team} vs {away_team}
Kickoff: {kickoff_str}

WEB SEARCH RESULTS:
{raw_results}

Extract the starting lineup for this match. Return ONLY this JSON:
{{
  "confirmed": false,
  "home_formation": "4-3-3",
  "away_formation": "4-2-3-1",
  "home_starters": [
    {{"name": "Player Name", "position": "GK|DEF|MID|FWD", "jersey": ""}}
  ],
  "home_subs": [],
  "away_starters": [
    {{"name": "Player Name", "position": "GK|DEF|MID|FWD", "jersey": ""}}
  ],
  "away_subs": [],
  "home_missing": [{{"name": "Player Name", "reason": "injury/suspension"}}],
  "away_missing": [{{"name": "Player Name", "reason": "injury/suspension"}}]
}}

Rules:
- Set "confirmed": true only if the source explicitly says these are the official/confirmed lineup
- Set "confirmed": false if these are predicted/expected/probable lineups — still include them
- If there is truly no lineup info at all (no names mentioned), return {{"confirmed": false, "home_starters": [], "away_starters": []}}
- jersey field can be empty string
- home_subs and away_subs can be []"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    json_match = re.search(r"\{[\s\S]*\}", text)
    if not json_match:
        logger.warning("Claude returned no JSON for lineup extraction")
        return None

    data = json.loads(json_match.group())

    # Only return None if there are truly no player names
    if not data.get("home_starters") or not data.get("away_starters"):
        return None

    return data


def fetch_lineup_for_match(
    home_team: str,
    away_team: str,
    kickoff_dt: datetime,
) -> Optional[dict]:
    """
    Fetch confirmed lineup using DuckDuckGo + Claude.
    Returns None if lineup not yet confirmed or can't be found.
    Same return structure as api_football.fetch_lineup_for_match().
    """
    logger.info("Claude lineup fetch: %s vs %s", home_team, away_team)

    raw = _gather_lineup_results(home_team, away_team, kickoff_dt)
    if not raw:
        logger.debug("No search results for lineup: %s vs %s", home_team, away_team)
        return None

    try:
        data = _extract_with_claude(home_team, away_team, kickoff_dt, raw)
    except Exception as exc:
        logger.error("Claude lineup extraction failed: %s", exc)
        return None

    if not data:
        return None

    logger.info(
        "Claude lineup confirmed: %s vs %s — %d vs %d starters",
        home_team, away_team,
        len(data.get("home_starters", [])),
        len(data.get("away_starters", [])),
    )

    confirmed = data.get("confirmed", False)
    return {
        "source": "claude+duckduckgo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "lineup_confirmed": confirmed,
        "home_formation": data.get("home_formation", ""),
        "away_formation": data.get("away_formation", ""),
        "home_starters": data.get("home_starters", []),
        "home_subs": data.get("home_subs", []),
        "away_starters": data.get("away_starters", []),
        "away_subs": data.get("away_subs", []),
        "home_missing": data.get("home_missing", []),
        "away_missing": data.get("away_missing", []),
    }

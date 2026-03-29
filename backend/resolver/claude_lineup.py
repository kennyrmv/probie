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


def _fetch_page(url: str, max_chars: int = 3000) -> str:
    """Fetch plain text from a URL. Returns empty string on failure."""
    try:
        import httpx
        resp = httpx.get(url, timeout=8.0, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; LineupBot/1.0)"
        })
        if resp.status_code != 200:
            return ""
        # Strip HTML tags crudely but effectively
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", resp.text, flags=re.IGNORECASE)
        text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s{3,}", "\n", text)
        return text[:max_chars]
    except Exception as exc:
        logger.debug("Page fetch failed for %s: %s", url, exc)
        return ""


def _gather_lineup_results(home_team: str, away_team: str, kickoff_dt: datetime) -> str:
    date_str = kickoff_dt.strftime("%Y-%m-%d")
    # Prioritize queries that find official/confirmed lineups published today
    queries = [
        f"{home_team} {away_team} alineacion confirmada once inicial {date_str} site:infobae.com OR site:espn.com.ar OR site:espndeportes.espn.com",
        f"{home_team} {away_team} alineacion titular confirmada hoy",
        f"{home_team} vs {away_team} confirmed lineup starting XI {date_str} site:sofascore.com OR site:flashscore.com OR site:bbc.com OR site:espn.com",
        f"{home_team} vs {away_team} official starting XI {date_str}",
    ]

    all_results: list[str] = []
    fetched_urls: set[str] = set()

    for query in queries:
        results = _search(query, max_results=5)
        if not results:
            continue
        all_results.append(f"\n--- {query} ---")
        for r in results:
            all_results.append(f"[{r['title']}] ({r['url']})")
            if r["snippet"]:
                all_results.append(r["snippet"][:300])
            # Fetch full page for lineup-specific URLs
            url = r.get("url", "")
            if url and url not in fetched_urls and any(k in url for k in [
                "lineup", "alineacion", "starting-xi", "starting_xi", "lineups",
                "sofascore", "flashscore", "infobae", "espn"
            ]):
                page_text = _fetch_page(url)
                if page_text:
                    all_results.append(f"[PAGE CONTENT from {url}]:\n{page_text}")
                fetched_urls.add(url)

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
  "source_type": "unknown",
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

CRITICAL — source_type field determines whether we trust this lineup for betting:

"official" — the lineup was formally submitted to the referee and published by the TEAM
or a LIVE MATCH TRACKING source TODAY:
  - Club's official Twitter/X/Instagram posting "Our #StartingXI for today!" with player names
  - Sofascore or Flashscore showing a "Confirmed Lineup" section (green checkmark / live match)
  - Official team sheet posted by the club or competition body
  - TV broadcast showing the announced starting XI for today's match
  KEY TEST: was this XI submitted to the referee for THIS specific match today?
  Set "official" ONLY for unambiguous match-day official sources.

"probable" — the lineup is a prediction, press conference statement, or pre-match article:
  - Press conferences ("el técnico anunció que jugará X mañana", "el entrenador confirmó")
  - Journalist articles: "probable XI", "expected lineup", "alineación probable", "team news"
  - Sources using words like: probable, expected, likely, posible, podría, prevista, previsto
  - Training observations or sources published BEFORE today
  - ANY media/news site (infobae, espn, marca, as, etc.) even if they say "confirmada" —
    journalists use that word loosely for press-conference selections, NOT the official XI
  - Sources published more than 3 hours before kickoff from non-official club accounts
  Still include all player names — useful context for analysis even if not confirmed.

"unknown" — no lineup information at all in the search results

Set "confirmed": true ONLY when source_type is "official".
If source_type is "probable", set "confirmed": false but still include player names.
If source_type is "unknown", return empty home_starters and away_starters.
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

    # Override Claude's self-reported "confirmed" flag with the stricter source_type check.
    # Claude can be convinced by journalistic "confirmada" language — source_type is more reliable.
    source_type = data.get("source_type", "unknown")
    confirmed = (source_type == "official")  # Only official club/live-match sources count

    logger.info(
        "Claude lineup source_type=%s confirmed=%s for %s vs %s",
        source_type, confirmed, home_team, away_team,
    )

    return {
        "source": "claude+duckduckgo",
        "source_type": source_type,
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

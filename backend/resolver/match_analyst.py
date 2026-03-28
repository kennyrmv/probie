"""
match_analyst.py — Web-searching AI agent for football match analysis.

Flow:
  1. Run 4-5 targeted DuckDuckGo searches (free, no API key)
  2. Pass raw results + lineup/odds context to Claude for structured synthesis
  3. Return structured analysis stored in match.analysis_data

Triggered ONLY on explicit user request via POST /api/matches/{id}/analyze.
Never runs automatically — too slow and costly for bulk use.

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


# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────


def _search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search with DuckDuckGo. Returns list of {title, url, snippet}.
    Falls back to [] on rate limit or import error.
    """
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


def _gather_search_results(
    home_team: str,
    away_team: str,
    competition: str,
    kickoff_dt: datetime,
) -> str:
    """
    Run targeted searches and return raw results as formatted text.
    Covers: lineups, injuries, form, and match context.
    """
    month_year = kickoff_dt.strftime("%B %Y")
    date_str = kickoff_dt.strftime("%Y-%m-%d")

    queries = [
        f"{home_team} vs {away_team} lineup predicted starting XI {date_str}",
        f"{home_team} injuries suspensions missing players {month_year}",
        f"{away_team} injuries suspensions missing players {month_year}",
        f"{home_team} vs {away_team} {competition} preview analysis",
        f"{home_team} {away_team} form recent results {month_year}",
        f"{home_team} vs {away_team} head to head h2h history",
        f"{home_team} coach tactics formation {month_year}",
        f"{away_team} coach tactics formation {month_year}",
        f"{home_team} vs {away_team} motivation stakes {month_year}",
    ]

    all_results: list[str] = []
    for query in queries:
        results = _search(query, max_results=4)
        if not results:
            continue
        all_results.append(f"\n--- Búsqueda: {query} ---")
        for r in results:
            all_results.append(f"[{r['title']}] ({r['url']})")
            if r["snippet"]:
                all_results.append(r["snippet"][:300])

    return "\n".join(all_results) if all_results else "No se encontraron resultados."


# ─────────────────────────────────────────────────────────────────────────────
# Claude synthesis
# ─────────────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """Eres un analista profesional de apuestas deportivas de fútbol con 15 años de experiencia.
Tu trabajo es sintetizar información web en análisis accionables que ayuden a tomar decisiones de apuesta.

Reglas:
- Sé honesto sobre incertidumbre: si no hay info de alineación, di que no está confirmada
- Prioriza información reciente y de fuentes oficiales (clubes, prensa deportiva)
- Distingue entre bajas confirmadas y rumores
- Para los top 3 jugadores: identifica quiénes son más impactantes en el partido (no solo los más famosos)
- El ajuste de probabilidades debe ser conservador (máximo ±10pp por resultado) y basado en evidencia concreta
- La señal de apuesta combina el edge matemático CON el contexto real
- Responde ÚNICAMENTE con el JSON solicitado, sin texto adicional"""


def _synthesize(
    home_team: str,
    away_team: str,
    competition: str,
    kickoff_dt: datetime,
    raw_results: str,
    lineup_data: Optional[dict] = None,
    outcomes: Optional[list] = None,
) -> dict:
    """Call Claude to synthesize raw search results into structured analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    kickoff_str = kickoff_dt.strftime("%d %B %Y, %H:%M UTC")

    # Build lineup context if confirmed lineup available
    lineup_context = ""
    if lineup_data and lineup_data.get("home_starters"):
        home_names = [p["name"] for p in lineup_data.get("home_starters", [])[:11]]
        away_names = [p["name"] for p in lineup_data.get("away_starters", [])[:11]]
        lineup_context = f"""
ALINEACIÓN CONFIRMADA (API-Football):
{home_team}: {', '.join(home_names)}
{away_team}: {', '.join(away_names)}
Formaciones: {lineup_data.get('home_formation', '?')} vs {lineup_data.get('away_formation', '?')}
"""

    # Build odds context if available
    odds_context = ""
    if outcomes:
        odds_lines = []
        for o in outcomes:
            delta = o.get("delta_pp")
            delta_str = f"+{delta:.1f}pp" if delta and delta > 0 else (f"{delta:.1f}pp" if delta else "sin datos")
            odds_lines.append(
                f"  {o['label']}: modelo={o['model_prob']*100:.1f}% | mercado={o['polymarket_prob']*100:.1f}% | edge={delta_str} [{o.get('value_tier','?')}]"
            )
        odds_context = f"""
DATOS DEL MODELO MATEMÁTICO (Dixon-Coles vs Polymarket):
{''.join(chr(10) + line for line in odds_lines)}
El edge matemático refleja cuánto se aleja el mercado de las probabilidades históricas del modelo.
"""

    prompt = f"""Partido: {home_team} vs {away_team}
Competición: {competition}
Fecha/hora: {kickoff_str}
{lineup_context}
{odds_context}
RESULTADOS DE BÚSQUEDA WEB:
{raw_results}

Analiza este partido como un apostador profesional. Devuelve ÚNICAMENTE este JSON:
{{
  "home_lineup": ["nombre", ...],
  "away_lineup": ["nombre", ...],
  "home_missing": [{{"name": "nombre", "reason": "lesión/suspensión/otro"}}],
  "away_missing": [{{"name": "nombre", "reason": "lesión/suspensión/otro"}}],
  "top_players_home": [
    {{"name": "nombre completo", "position": "DEL|MED|DEF|POR", "impact": "por qué es clave en ESTE partido", "form": "estado de forma actual en 1 frase"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "top_players_away": [
    {{"name": "nombre completo", "position": "DEL|MED|DEF|POR", "impact": "por qué es clave en ESTE partido", "form": "estado de forma actual en 1 frase"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "form_home": "ej: V-V-E-V-D · 2.2 pts/j",
  "form_away": "ej: D-E-V-D-V · 1.4 pts/j",
  "context": "1-2 frases sobre qué se juegan ambos equipos y contexto clave",
  "key_factors": [
    "factor 1 concreto y relevante para la apuesta",
    "factor 2",
    "factor 3"
  ],
  "prob_adjustment": {{
    "home": 0.00,
    "draw": 0.00,
    "away": 0.00,
    "reasoning": "Por qué ajustas (o no) las probabilidades del modelo. Si no hay evidencia clara, deja todo en 0.00"
  }},
  "bet_signal": {{
    "type": "value|favorite|none",
    "side": "home|draw|away|null",
    "confidence": "alta|media|baja",
    "reasoning": "Explicación en 2-3 frases: combina el edge matemático CON el contexto real para dar una recomendación accionable. Si type=value, confirma/refuta el edge. Si type=favorite, explica por qué el favorito está justificado. Si type=none, explica por qué no apostar."
  }},
  "lineup_confirmed": false,
  "confidence": "alta|media|baja",
  "sources": ["url1", "url2"]
}}

Reglas para prob_adjustment: valores entre -0.10 y +0.10. La suma home+draw+away debe ser ~0.
Reglas para bet_signal.type: "value"=hay edge matemático confirmado por contexto real, "favorite"=apostar al favorito claro tiene buen ROI, "none"=no apostar.
Si no hay datos confiables para un campo, usa [] o null. No inventes datos."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON — handle cases where Claude wraps it in ```json
    json_match = re.search(r"\{[\s\S]*\}", text)
    if not json_match:
        raise ValueError(f"Claude returned no JSON: {text[:200]}")

    return json.loads(json_match.group())


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def analyze_match(
    home_team: str,
    away_team: str,
    competition: str,
    kickoff_dt: datetime,
    lineup_data: Optional[dict] = None,
    outcomes: Optional[list] = None,
) -> dict:
    """
    Full pipeline: search + synthesize.

    Args:
        home_team, away_team, competition, kickoff_dt: match identity
        lineup_data: confirmed lineup from API-Football (optional)
        outcomes: list of {label, model_prob, polymarket_prob, delta_pp, value_tier}
                  from the DB — gives Claude the math context (optional)

    Returns analysis dict ready to store in match.analysis_data.
    Raises ValueError if ANTHROPIC_API_KEY is missing.
    Raises on unrecoverable errors.
    """
    logger.info("Analyzing: %s vs %s (%s)", home_team, away_team, competition)

    raw = _gather_search_results(home_team, away_team, competition, kickoff_dt)
    logger.debug("Search results length: %d chars", len(raw))

    analysis = _synthesize(
        home_team=home_team,
        away_team=away_team,
        competition=competition,
        kickoff_dt=kickoff_dt,
        raw_results=raw,
        lineup_data=lineup_data,
        outcomes=outcomes,
    )

    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["source"] = "claude+duckduckgo"

    logger.info(
        "Analysis complete: confidence=%s, bet_signal=%s/%s, lineup_confirmed=%s, "
        "missing_home=%d, missing_away=%d, key_factors=%d",
        analysis.get("confidence"),
        analysis.get("bet_signal", {}).get("type"),
        analysis.get("bet_signal", {}).get("side"),
        analysis.get("lineup_confirmed"),
        len(analysis.get("home_missing") or []),
        len(analysis.get("away_missing") or []),
        len(analysis.get("key_factors") or []),
    )
    return analysis

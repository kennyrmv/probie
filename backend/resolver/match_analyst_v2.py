"""
match_analyst_v2.py — Structured Claude analyst for football match analysis.

Key difference from match_analyst.py:
  - Receives ONLY structured JSON data from data_collector.py
  - NO DuckDuckGo web searches — all data comes from APIs
  - ~50-60% smaller prompts → cheaper, faster, more reliable
  - Claude focuses purely on tactical analysis and bet signal generation

Triggered automatically when confirmed lineups arrive (~60 min before kickoff).
Also available on-demand via POST /api/matches/{id}/analyze.

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
# System prompt — focused on tactical analysis, not data extraction
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un analista profesional de apuestas deportivas de futbol con 15 anos de experiencia.
Recibes datos ESTRUCTURADOS de APIs oficiales (alineaciones confirmadas, lesiones, forma, H2H, odds).
Tu trabajo es ANALIZAR estos datos y producir un juicio tactico accionable.

NO necesitas buscar informacion — TODO te lo proporcionan. Enfocate en el ANALISIS.

Reglas de analisis:
- Evalua la diferencia real de calidad entre los dos XIs titular a titular.
- Para los top 3 jugadores: los mas impactantes en ESTE partido especifico, no los mas famosos.
- El ajuste de probabilidades debe ser conservador (maximo +-10pp) y justificado con evidencia concreta.
- Responde UNICAMENTE con el JSON solicitado, sin texto adicional.

TIPOS DE SENAL — elige UNA, son mutuamente excluyentes:

"value" — EDGE DE MERCADO (ineficiencia):
  El mercado esta equivocado. Requisitos: (1) el modelo da prob significativamente distinta al mercado,
  Y (2) el contexto real lo confirma — baja clave no priced, XI superior no reflejado, mercado poco activo.
  Razonamiento: explica POR QUE el mercado se equivoca, no solo que los numeros difieren.

"strength" — APUESTA DE FUERZA (conviccion cualitativa):
  Superioridad cualitativa clara e independiente de si el mercado lo refleja.
  Usar cuando: XI claramente superior, rival con bajas masivas, diferencia de nivel objetiva.
  OBLIGATORIO incluir "strength_reasons": 3-5 razones concretas y verificables.

"none" — SIN SENAL:
  Ni ineficiencia de mercado ni dominancia cualitativa clara.

REGLA CRITICA: Solo incluye jugadores que aparecen en las alineaciones proporcionadas.
Si no hay alineaciones, basa tu analisis en forma, H2H y contexto general."""


def analyze(match_data: dict) -> dict:
    """
    Analyze a match using structured data from data_collector.

    Args:
        match_data: dict from data_collector.collect_match_data() with keys:
            match, lineups, injuries, form, h2h, model_probs, market_probs, edge

    Returns:
        Analysis dict compatible with match.analysis_data JSONB schema.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    match_info = match_data.get("match", {})
    lineups = match_data.get("lineups", {})
    injuries = match_data.get("injuries", {})
    form = match_data.get("form", {})
    h2h = match_data.get("h2h", [])
    model_probs = match_data.get("model_probs", {})
    market_probs = match_data.get("market_probs", {})
    edge = match_data.get("edge", {})

    home_team = match_info.get("home", "")
    away_team = match_info.get("away", "")

    lineup_confirmed = bool(lineups.get("confirmed"))

    # Build concise structured prompt
    sections = []

    sections.append(f"PARTIDO: {home_team} vs {away_team}")
    sections.append(f"Competicion: {match_info.get('competition', '')}")
    sections.append(f"Fecha/hora: {match_info.get('kickoff', '')}")

    if lineups:
        status = "XI OFICIAL CONFIRMADO" if lineup_confirmed else "ALINEACION PROBABLE"
        sections.append(f"\n{status}:")
        sections.append(f"{home_team} ({lineups.get('home_formation', '?')}): {', '.join(lineups.get('home_xi', []))}")
        sections.append(f"{away_team} ({lineups.get('away_formation', '?')}): {', '.join(lineups.get('away_xi', []))}")
        if lineups.get("home_subs"):
            sections.append(f"Suplentes {home_team}: {', '.join(lineups['home_subs'])}")
        if lineups.get("away_subs"):
            sections.append(f"Suplentes {away_team}: {', '.join(lineups['away_subs'])}")

    home_missing = injuries.get("home_missing", [])
    away_missing = injuries.get("away_missing", [])
    if home_missing or away_missing:
        sections.append("\nLESIONES/BAJAS:")
        if home_missing:
            sections.append(f"  {home_team}: " + ", ".join(f"{p['name']} ({p.get('reason', '?')})" for p in home_missing))
        if away_missing:
            sections.append(f"  {away_team}: " + ", ".join(f"{p['name']} ({p.get('reason', '?')})" for p in away_missing))

    if form:
        sections.append("\nFORMA RECIENTE:")
        if "home" in form:
            sections.append(f"  {home_team}: {form['home']}")
        if "away" in form:
            sections.append(f"  {away_team}: {form['away']}")

    if h2h:
        sections.append(f"\nH2H (ultimos {len(h2h)} partidos):")
        for m in h2h[:5]:
            sections.append(f"  {m['date']}: {m['home']} {m['score']} {m['away']} ({m['competition']})")

    if model_probs and market_probs:
        sections.append("\nPROBABILIDADES MODELO vs MERCADO:")
        for outcome in ("home", "draw", "away"):
            mp = model_probs.get(outcome, 0)
            mkp = market_probs.get(outcome, 0)
            e = edge.get(outcome, "0pp")
            label = {"home": f"{home_team} gana", "draw": "Empate", "away": f"{away_team} gana"}[outcome]
            sections.append(f"  {label}: modelo={mp*100:.1f}% | mercado={mkp*100:.1f}% | edge={e}")

    data_text = "\n".join(sections)

    prompt = f"""{data_text}

Analiza este partido como un apostador profesional. Devuelve UNICAMENTE este JSON:
{{
  "home_lineup": ["nombre", ...],
  "away_lineup": ["nombre", ...],
  "home_missing": [{{"name": "nombre", "reason": "lesion/suspension/otro"}}],
  "away_missing": [{{"name": "nombre", "reason": "lesion/suspension/otro"}}],
  "top_players_home": [
    {{"name": "nombre", "position": "DEL|MED|DEF|POR", "impact": "por que es clave", "form": "estado actual"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "top_players_away": [
    {{"name": "nombre", "position": "DEL|MED|DEF|POR", "impact": "por que es clave", "form": "estado actual"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "form_home": "ej: V-V-E-V-D · 2.2 pts/j",
  "form_away": "ej: D-E-V-D-V · 1.4 pts/j",
  "context": "1-2 frases sobre que se juegan ambos equipos y contexto clave",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "prob_adjustment": {{
    "home": 0.00, "draw": 0.00, "away": 0.00,
    "reasoning": "Por que ajustas o no las probabilidades"
  }},
  "bet_signal": {{
    "type": "value|strength|none",
    "side": "home|draw|away|null",
    "confidence": "alta|media|baja",
    "reasoning": "2-3 frases accionables. Menciona jugadores por nombre.",
    "strength_reasons": ["razon 1", "razon 2", "razon 3"]
  }},
  "lineup_confirmed": {str(lineup_confirmed).lower()},
  "confidence": "alta|media|baja",
  "sources": []
}}

Reglas: prob_adjustment entre -0.10 y +0.10, suma ~0.
strength_reasons OBLIGATORIO si type="strength", sino [].
home_lineup y away_lineup: usa EXACTAMENTE los nombres de las alineaciones proporcionadas."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON
    json_match = re.search(r"\{[\s\S]*\}", text)
    if not json_match:
        raise ValueError(f"Claude returned no JSON: {text[:200]}")

    analysis = json.loads(json_match.group())

    # Add metadata
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["source"] = "structured-api"
    analysis["lineup_confirmed"] = lineup_confirmed
    analysis["lineup_data_used"] = bool(lineups.get("home_xi"))

    logger.info(
        "Structured analysis complete: %s vs %s, confidence=%s, signal=%s/%s, lineup_confirmed=%s",
        home_team, away_team,
        analysis.get("confidence"),
        analysis.get("bet_signal", {}).get("type"),
        analysis.get("bet_signal", {}).get("side"),
        lineup_confirmed,
    )
    return analysis

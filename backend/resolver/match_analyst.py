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
    year = kickoff_dt.strftime("%Y")

    queries = [
        # Match preview
        f"{home_team} vs {away_team} preview {date_str}",
        f"{home_team} vs {away_team} {competition} {month_year} analisis previo",
        # *** CRITICAL: Official squad list for this exact break ***
        # (prevents listing players not called up, e.g. Griezmann if not in squad)
        f"{home_team} seleccion convocados lista oficial {month_year}",
        f"{away_team} seleccion convocados lista oficial {month_year}",
        # *** CRITICAL: Results from THIS break (teams may have already played) ***
        f"{home_team} seleccion resultado partido {month_year}",
        f"{away_team} seleccion resultado partido {month_year}",
        # Injuries/absences
        f"{home_team} bajas lesiones {month_year}",
        f"{away_team} bajas lesiones {month_year}",
        # Coach and tactical system
        f"{home_team} entrenador tactica sistema {year}",
        f"{away_team} entrenador tactica sistema {year}",
        # H2H
        f"{home_team} vs {away_team} head to head historial",
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
Tu trabajo es producir análisis accionables combinando datos web con tu conocimiento experto de fútbol internacional.

Reglas sobre fuentes:
- Los resultados de búsqueda son tu fuente primaria. Úsalos cuando estén disponibles.
- Si los resultados web son escasos o vacíos, USA TU CONOCIMIENTO PROPIO sobre estas selecciones:
  rendimiento en torneos recientes (Copa Africa, Copa América, eliminatorias), estilo del entrenador,
  jugadores clave en forma, rivalidades históricas, motivación del partido. Eres un experto — no finjas
  ignorar lo que sabes. NUNCA digas "ausencia de datos web" como excusa para no analizar.
- Distingue entre bajas confirmadas (di la fuente) y bajas inferidas por tu conocimiento.

Reglas de análisis:
- Si hay XI confirmado o probable: DEBES mencionar jugadores específicos por nombre en el razonamiento.
  Evalúa la diferencia real de calidad entre los dos XIs titular a titular.
- Para los top 3 jugadores: los más impactantes en ESTE partido específico, no los más famosos en general.
- El ajuste de probabilidades debe ser conservador (máximo ±10pp) y justificado con evidencia concreta.
- Responde ÚNICAMENTE con el JSON solicitado, sin texto adicional.

━━━ TIPOS DE SEÑAL — elige UNA, son mutuamente excluyentes ━━━

"value" — EDGE DE MERCADO (ineficiencia):
  El mercado está equivocado en la probabilidad de este resultado.
  Requisitos: (1) el modelo da una prob significativamente distinta al mercado, Y (2) el contexto
  real lo confirma — una baja clave no priced, XI superior no reflejado, mercado poco activo.
  NO usar si el modelo se equivoca (ej: modelo entrena con CONMEBOL y el rival es Francia con top XI).
  Razonamiento: explica POR QUÉ el mercado está equivocado, no solo que los números difieren.

"strength" — APUESTA DE FUERZA (convicción cualitativa):
  Un equipo tiene superioridad cualitativa clara y comprobable, independientemente de si el
  mercado ya lo refleja o no. No es sobre ineficiencia — es sobre certeza de dominancia.
  Usar cuando: XI claramente superior jugador por jugador, rival con bajas masivas, diferencia
  de nivel objetiva, motivación asimétrica. INCLUSO si el mercado ya da al favorito al 60%+,
  si los fundamentos justifican alta probabilidad de victoria, es señal "strength".
  OBLIGATORIO incluir "strength_reasons": 3-5 razones concretas y verificables.
  Ejemplo: ["Mbappé + Dembélé + Olise titulares vs línea defensiva colombiana inferior",
            "Colombia rota 6 titulares en amistoso de preparación",
            "Francia invicta en 12 partidos en casa con este XI"]

"none" — SIN SEÑAL:
  Ni hay ineficiencia real de mercado ni hay dominancia cualitativa clara.
  Partido equilibrado, contexto incierto, o señales contradictorias.

━━━ REGLA CRÍTICA — CONVOCATORIA Y FORMA RECIENTE ━━━
- Los jugadores en "top_players_home/away" DEBEN estar confirmados en la convocatoria de ESTE parón.
  Si los resultados de búsqueda de "convocados {mes}" NO confirman que un jugador estrella fue
  convocado, NO lo pongas como jugador clave. Usa solo jugadores que los resultados web confirman.
  EJEMPLO: si buscas "France convocados marzo 2026" y Griezmann no aparece → NO lo incluyas.
- Para "form_home" y "form_away": incluye resultados de ESTE parón de selecciones si ya jugaron.
  Los equipos nacionales pueden haber jugado ya una primera jornada en este parón — búscalo
  explícitamente. EJEMPLO: si Colombia perdió 0-1 contra Croacia en este parón, ese resultado
  DEBE reflejarse en la forma reciente, no ignorarse.
- Nunca uses jugadores históricos famosos si no hay evidencia web de que están convocados ahora."""


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

    # Build lineup context if lineup available
    lineup_context = ""
    lineup_is_confirmed = bool(lineup_data and lineup_data.get("lineup_confirmed"))
    if lineup_data and lineup_data.get("home_starters"):
        home_players = lineup_data.get("home_starters", [])[:11]
        away_players = lineup_data.get("away_starters", [])[:11]
        home_names = [p["name"] for p in home_players]
        away_names = [p["name"] for p in away_players]
        home_missing = lineup_data.get("home_missing", [])
        away_missing = lineup_data.get("away_missing", [])
        status_label = "XI OFICIAL CONFIRMADO" if lineup_is_confirmed else "ALINEACIÓN PROBABLE"
        missing_home_str = (
            f"\n  Bajas {home_team}: " + ", ".join(f"{p['name']} ({p.get('reason','?')})" for p in home_missing)
            if home_missing else ""
        )
        missing_away_str = (
            f"\n  Bajas {away_team}: " + ", ".join(f"{p['name']} ({p.get('reason','?')})" for p in away_missing)
            if away_missing else ""
        )
        lineup_context = f"""
{status_label}:
{home_team} ({lineup_data.get('home_formation', '?')}): {', '.join(home_names)}{missing_home_str}
{away_team} ({lineup_data.get('away_formation', '?')}): {', '.join(away_names)}{missing_away_str}
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
    {{"name": "nombre completo", "position": "DEL|MED|DEF|POR", "impact": "por qué es clave en ESTE partido", "form": "estado de forma actual en 1 frase — SOLO si fue confirmado convocado en este parón"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "top_players_away": [
    {{"name": "nombre completo", "position": "DEL|MED|DEF|POR", "impact": "por qué es clave en ESTE partido", "form": "estado de forma actual en 1 frase — SOLO si fue confirmado convocado en este parón"}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}},
    {{"name": "...", "position": "...", "impact": "...", "form": "..."}}
  ],
  "form_home": "ej: V-V-E-V-D · 2.2 pts/j — incluye resultados de ESTE parón si ya jugaron",
  "form_away": "ej: D-E-V-D-V · 1.4 pts/j — incluye resultados de ESTE parón si ya jugaron",
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
    "type": "value|strength|none",
    "side": "home|draw|away|null",
    "confidence": "alta|media|baja",
    "reasoning": "2-3 frases accionables. Si type=value: explica POR QUÉ el mercado se equivoca. Si type=strength: explica la dominancia concreta del equipo. SIEMPRE menciona jugadores por nombre si hay XI disponible.",
    "strength_reasons": ["razón concreta 1", "razón concreta 2", "razón concreta 3"]
  }},
  "lineup_confirmed": {str(lineup_is_confirmed).lower()},
  "confidence": "alta|media|baja",
  "sources": ["url1", "url2"]
}}

Reglas para prob_adjustment: valores entre -0.10 y +0.10. La suma home+draw+away debe ser ~0.
IMPORTANTE para bet_signal:
- "value": ineficiencia de mercado real confirmada por contexto. El mercado se equivoca.
- "strength": dominancia cualitativa clara aunque el mercado ya lo refleje. El equipo va a ganar con alta probabilidad por razones objetivas y verificables.
- "none": ni ineficiencia real ni dominancia clara.
- strength_reasons: OBLIGATORIO si type="strength". Lista de 3-5 hechos concretos y verificables.
  Si type!="strength", devuelve strength_reasons como lista vacía [].
Si los resultados de búsqueda están vacíos o son escasos: analiza igualmente usando tu conocimiento
experto sobre estas selecciones. Contexto que DEBES conocer y usar: torneos recientes (AFCON 2023/2024,
Copa América 2024, eliminatorias mundialistas), estilo del entrenador de cada selección, jugadores
estrella en forma, h2h histórico, nivel del campeonato doméstico de los convocados.
Si no hay datos confiables para un campo estructurado (lesiones concretas, resultado exacto), usa [] — pero
el razonamiento de bet_signal SIEMPRE debe ser sustancial y mencionar contexto real, nunca excusas."""

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
    # Authoritative: override Claude's lineup_confirmed with what we actually passed in
    if lineup_data:
        analysis["lineup_confirmed"] = bool(lineup_data.get("lineup_confirmed"))
    # Track whether lineup data was used in this analysis (independent of confirmed status)
    analysis["lineup_data_used"] = bool(lineup_data and lineup_data.get("home_starters"))

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

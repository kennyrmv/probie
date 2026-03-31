# EdgeFút

> **Detector de valor en mercados de fútbol** · Football value bet detector

[![Next.js](https://img.shields.io/badge/Next.js-15-black)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.12-009688)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Railway-336791)](https://railway.app)

---

## Español

EdgeFút compara las probabilidades del modelo matemático Dixon-Coles contra las odds de la multitud en [Polymarket](https://polymarket.com), y detecta partidos donde el mercado está mal valorado.

### ¿Qué hace?

- **Señal Edge** — El modelo matemático estima una probabilidad significativamente distinta a la del mercado. Si el mercado subestima a un equipo, es una oportunidad de valor real.
- **Señal Fuerza** — Análisis cualitativo con IA (Claude): cuando la diferencia de calidad entre plantillas es objetiva y verificable, independientemente de las odds.
- **Veredicto del Día** — Muestra la mejor apuesta de mercado y la mejor apuesta de fuerza del día, lado a lado.
- **Análisis IA bajo demanda** — Claude busca en la web, analiza alineaciones, lesiones, contexto táctico y genera un veredicto con razonamiento explícito.
- **Alineaciones en tiempo real** — Obtiene las alineaciones confirmadas desde la API de football-data.org y las integra en el análisis.

### Stack técnico

```
edgefut/
├── backend/          — FastAPI + Python 3.12 + PostgreSQL
│   ├── resolver/     — Empareja mercados de Polymarket con partidos reales
│   ├── pipeline/     — Modelo Dixon-Coles + generación de señales
│   ├── api/          — Rutas REST + tareas en background
│   └── main.py       — APScheduler: pipeline 06:00 UTC, odds cada 15 min
└── frontend/         — Next.js 15 + TypeScript + Tailwind CSS
    └── app/
        ├── components/
        │   ├── MatchCard.tsx      — Fila compacta con badge de señal
        │   ├── MatchModal.tsx     — Modal de detalle con alineaciones
        │   └── AnalysisPanel.tsx  — Panel de análisis IA
        └── page.tsx               — Página principal + Veredicto del Día
```

### Cómo ejecutar localmente

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Variables de entorno necesarias:**
```
DATABASE_URL              — PostgreSQL (Railway lo configura automáticamente)
FOOTBALL_DATA_API_KEY     — API de football-data.org (tier gratuito)
API_FOOTBALL_KEY          — API-Football para alineaciones confirmadas
ANTHROPIC_API_KEY         — Claude para análisis IA
POLYMARKET_API_BASE        — Base URL de Polymarket (opcional, tiene default)
CORS_ORIGINS              — Orígenes permitidos (ej: http://localhost:3000)
```

---

## English

EdgeFút compares Dixon-Coles model probabilities against [Polymarket](https://polymarket.com) crowd odds to find football matches where the market is mispriced.

### What it does

- **Edge signal** — The math model estimates a significantly different probability than the market. When the market undervalues a team by 5pp+, that's a real value opportunity.
- **Fuerza (strength) signal** — AI-powered qualitative analysis (Claude): when the squad quality gap is objective and verifiable, regardless of odds.
- **Veredicto del Día** — Shows the best market-edge bet and the best conviction bet of the day, side by side.
- **On-demand AI analysis** — Claude searches the web, analyzes confirmed lineups, injuries, tactical context, and generates a verdict with explicit reasoning.
- **Live lineups** — Fetches confirmed lineups from the football-data.org API and integrates them into the AI analysis.

### Tech stack

| Layer | Tech |
|---|---|
| Backend | FastAPI · Python 3.12 · PostgreSQL · Alembic |
| Model | Dixon-Coles (calibrated on CONMEBOL/UEFA qualifiers) |
| AI | Claude (Anthropic) — web search + analysis |
| Frontend | Next.js 15 · TypeScript · Tailwind CSS |
| Scheduler | APScheduler — pipeline at 06:00 UTC, odds refresh every 15 min |
| Hosting | Railway (backend + DB) + Vercel (frontend) |

### Signal types

| Signal | Logic | UI |
|---|---|---|
| ⚡ Edge de mercado | Model prob > market prob by 5pp+ AND AI confirms | Green badge |
| 💪 Apuesta de fuerza | AI qualitative dominance, model may be unreliable | Purple badge |
| IA descarta señal | AI analyzed but found no edge or conviction | Grey badge |

### Running locally

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Required environment variables:**
```
DATABASE_URL              — PostgreSQL connection string
FOOTBALL_DATA_API_KEY     — football-data.org free tier key
API_FOOTBALL_KEY          — API-Football for confirmed lineups
ANTHROPIC_API_KEY         — Claude for AI analysis
POLYMARKET_API_BASE        — Polymarket base URL (has default)
CORS_ORIGINS              — Allowed CORS origins
```

### Data model

- `matches` — one row per fixture, indexed by kickoff + Polymarket market ID
- `predictions` — immutable model output, one per match per run
- `market_snapshots` — append-only Polymarket odds, one row per outcome per 15-min refresh
- `historical_matches` — seeded from football-data.org, used to calibrate Dixon-Coles
- `calibration_log` — AI signal tracking: records ⚡ Edge confirmado and 💪 Apuesta de fuerza signals with actual result, Market Drift (closing vs entry Polymarket price), Brier scores, and ROI simulation data

### Scheduler (APScheduler, UTC)

| Time | Task |
|---|---|
| 06:00 + 14:00 daily | Fetch fixtures, run Dixon-Coles, store predictions |
| Every 15 min (08:00–22:00) | Refresh Polymarket odds snapshots |
| Every 5 min | Auto-fetch lineups when available |
| Every hour (at :10) | Resolve finished match results + compute Market Drift for AI signals |

### Performance Dashboard

`GET /api/performance` (frontend: `/performance`) — tracks model accuracy on AI-confirmed signals only:

- **Win rate** — % of signals where predicted outcome was correct
- **Market Drift** — did Polymarket odds move toward our prediction before kickoff? Positive = model was early and right
- **Brier Score** — Dixon-Coles vs Polymarket calibration comparison
- **ROI simulation** — flat-unit simulation at entry prices
- **By signal type** — ⚡ Edge confirmado vs 💪 Apuesta de fuerza breakdown

---

## Limitations

- Dixon-Coles is calibrated on domestic league and qualifier data. It is **unreliable for high-profile friendlies** where squad selection is unpredictable. The AI analysis detects this and switches to the Fuerza signal when appropriate.
- Polymarket football markets can be illiquid, especially for lower-profile matches. Thin markets mean odds may not accurately reflect crowd wisdom.

---

*Built with [Claude Code](https://claude.ai/claude-code)*

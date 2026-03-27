# EdgeFút — Claude Code Context

Football value bet detector. Compares Dixon-Coles model probabilities against
Polymarket crowd odds, surfaces matches where market is mispriced by >5pp.

## Architecture

```
edgefut/
├── backend/           — FastAPI + Python 3.12
│   ├── resolver/      — Polymarket ↔ football-data.org match resolver
│   │   ├── resolver.py    critical: gameStartTime, json.loads(), closed=false
│   │   └── aliases.json   team name alias table (e.g. "man utd" → "manchester united")
│   ├── pipeline/      — Dixon-Coles model + reasons generation
│   │   └── pipeline.py
│   ├── api/           — FastAPI routes
│   │   └── routes.py
│   ├── migrations/    — Alembic schema migrations (NEVER alter manually)
│   ├── tests/         — pytest unit tests
│   ├── models.py      — SQLAlchemy ORM (5 tables)
│   ├── database.py    — connection pool + session factory
│   └── main.py        — app entry point + APScheduler
└── frontend/          — Next.js 15 + TypeScript + Tailwind (Sprint 2)
```

## Critical Rules

1. **gameStartTime, NOT endDate** — endDate is market close time (2h before kickoff)
2. **json.loads(outcomePrices)** — outcomePrices is a JSON string, not a native array
3. **closed=false filter** — active=true alone returns resolved/closed markets
4. **market_snapshots is append-only** — never UPDATE, only INSERT
5. **Alembic for all schema changes** — never ALTER TABLE manually
6. **All 3 outcomes per match** — home/draw/away, not just home

## Running the Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Run migrations first
alembic upgrade head
# Start server
uvicorn main:app --reload --port 8000
```

## Testing

```bash
cd backend
pytest tests/ -v
```

Framework: pytest. All tests runnable with `pytest tests/`.
Mock Polymarket/API responses using `unittest.mock`.

## Testing

Run command: `pytest tests/ -v`
Test directory: `backend/tests/`

### Test expectations
- 100% test coverage is the goal
- When writing new functions, write a corresponding test
- When fixing a bug, write a regression test
- When adding error handling, write a test that triggers the error
- When adding a conditional, write tests for BOTH paths
- Never commit code that makes existing tests fail

## Environment Variables

```
DATABASE_URL        — PostgreSQL URL (Railway sets this automatically)
FOOTBALL_DATA_API_KEY — football-data.org free tier key
CORS_ORIGINS        — comma-separated allowed origins
```

## Data Model

- `matches` — one row per fixture (indexed by kickoff_utc + polymarket_neg_risk_market_id)
- `predictions` — immutable model output, one per match per run
- `market_snapshots` — append-only Polymarket odds, one row per outcome per 15-min refresh
- `historical_matches` — seeded from football-data.org, used by Dixon-Coles
- `calibration_log` — prediction vs actual result for accuracy tracking

## Scheduler (APScheduler, UTC)

- 06:00 UTC daily — fetch fixtures, run model, store predictions
- Every 15 min (08:00–22:00) — refresh Polymarket odds snapshots

"""
EdgeFút FastAPI application entry point.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

# Load .env before anything else so all env vars are available
from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from database import SessionLocal, check_db_connection
from pipeline.pipeline import run_daily_pipeline, run_refresh_pipeline, seed_historical_data
from pipeline.performance import resolve_match_results, save_daily_picks, update_match_scores
from api.routes import _run_analysis_and_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="EdgeFút API",
    description="Football value bet detector against Polymarket",
    version="0.1.0",
)

# CORS: allow Next.js frontend (Vercel) + local dev
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,https://edgefut.vercel.app",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)

# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="UTC")


def _daily_job():
    with SessionLocal() as db:
        run_daily_pipeline(db)
        db.commit()


def _refresh_job():
    with SessionLocal() as db:
        run_refresh_pipeline(db)
        db.commit()


def _auto_lineup_job():
    """
    Auto-fetch confirmed lineups for matches kicking off in the next 35 minutes.
    Runs every 5 minutes. Triggers re-analysis if a confirmed XI is found.
    API-Football publishes lineups ~60min before kickoff.
    """
    from datetime import timedelta
    from models import Match
    from resolver.claude_lineup import fetch_lineup_for_match

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=0)    # already started (live)
    window_end   = now + timedelta(minutes=35)   # up to 35 min from now

    with SessionLocal() as db:
        upcoming = (
            db.query(Match)
            .filter(
                Match.kickoff_utc >= window_start,
                Match.kickoff_utc <= window_end,
            )
            .all()
        )
        for match in upcoming:
            existing = match.lineup_data or {}
            if existing.get("lineup_confirmed"):
                continue  # already confirmed, skip

            logger.info(
                "Auto-lineup: fetching for %s vs %s (kickoff in %d min)",
                match.home_team, match.away_team,
                int((match.kickoff_utc - now).total_seconds() / 60),
            )
            try:
                lineup = fetch_lineup_for_match(
                    home_team=match.home_team,
                    away_team=match.away_team,
                    kickoff_dt=match.kickoff_utc,
                )
                if lineup:
                    match.lineup_data = lineup
                    db.commit()
                    logger.info(
                        "Auto-lineup: confirmed XI stored for %s vs %s",
                        match.home_team, match.away_team,
                    )
                    # Trigger re-analysis with confirmed lineup
                    if lineup.get("lineup_confirmed"):
                        _run_analysis_and_store(str(match.id))
            except Exception as exc:
                logger.warning(
                    "Auto-lineup: failed for %s vs %s: %s",
                    match.home_team, match.away_team, exc,
                )


# Daily pipeline runs twice: 06:00 UTC (morning) + 14:00 UTC (afternoon)
# Polymarket publishes new markets throughout the day, second run catches late additions
scheduler.add_job(_daily_job, "cron", hour=6,  minute=0, id="daily_pipeline_morning")
scheduler.add_job(_daily_job, "cron", hour=14, minute=0, id="daily_pipeline_afternoon")

# Every 15 min 08:00–22:00 UTC on all days — refresh Polymarket odds
scheduler.add_job(
    _refresh_job,
    "cron",
    hour="8-22",
    minute="*/15",
    id="refresh_pipeline",
)

def _resolve_results_job():
    with SessionLocal() as db:
        resolve_match_results(db)
        update_match_scores(db)   # fetch scores for display (no AI gate)
        db.commit()


def _save_daily_picks_job():
    """
    Persist today's top Veredictos del día server-side.
    Runs after the daily pipeline so fresh analyses are included.
    """
    with SessionLocal() as db:
        result = save_daily_picks(db)
        db.commit()
    logger.info(
        "Daily picks saved: value=%s strength=%s",
        result.get("value", "none"), result.get("strength", "none"),
    )


# Every 5 min — auto-fetch confirmed lineups for matches kicking off in ≤35 min
# API-Football publishes lineups ~60min before kickoff, this catches them automatically
scheduler.add_job(
    _auto_lineup_job,
    "cron",
    minute="*/5",
    id="auto_lineup",
)

# Every 15 min — resolve finished match results + compute CLV + update scores
# Same frequency as odds refresh so results appear within 15 min of match end
scheduler.add_job(
    _resolve_results_job,
    "cron",
    minute="5,20,35,50",  # offset from refresh (:00,:15,:30,:45) to spread load
    id="resolve_results",
)

# Save Veredictos del día at 09:30 and 14:30 UTC (after each pipeline run)
# Captures picks after morning analysis + lineup data that arrives during the day
scheduler.add_job(_save_daily_picks_job, "cron", hour=9,  minute=30, id="daily_picks_morning")
scheduler.add_job(_save_daily_picks_job, "cron", hour=14, minute=30, id="daily_picks_afternoon")


@app.on_event("startup")
async def startup_event():
    logger.info("EdgeFút starting up...")

    # Seed historical data if DB is empty
    db = SessionLocal()
    try:
        from models import HistoricalMatch
        count = db.query(HistoricalMatch).count()
        if count == 0:
            logger.info("DB empty — seeding historical data (PL 2023+2024)...")
            seed_historical_data(db)
            db.commit()
            logger.info("Historical data seeded.")
        else:
            logger.info("Historical data already present (%d matches).", count)
    finally:
        db.close()

    scheduler.start()
    logger.info("Scheduler started.")

    # Run pipeline immediately on startup so matches are always fresh
    # (covers cases where server restarts between scheduled runs)
    import threading
    threading.Thread(target=_daily_job, daemon=True).start()
    logger.info("Startup pipeline triggered in background.")


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logger.info("EdgeFút shutdown.")

"""
EdgeFút FastAPI application entry point.
"""

from __future__ import annotations

import logging
import os

# Load .env before anything else so all env vars are available
from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from database import SessionLocal, check_db_connection
from pipeline.pipeline import run_daily_pipeline, run_refresh_pipeline, seed_historical_data

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


# Daily: 06:00 UTC — fetch fixtures and run model
scheduler.add_job(_daily_job, "cron", hour=6, minute=0, id="daily_pipeline")

# Every 15 min 08:00–22:00 UTC on all days — refresh Polymarket odds
scheduler.add_job(
    _refresh_job,
    "cron",
    hour="8-22",
    minute="*/15",
    id="refresh_pipeline",
)


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


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logger.info("EdgeFút shutdown.")

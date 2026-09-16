"""Job scheduler berbasis APScheduler untuk polling berkala."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config

logger = logging.getLogger("realtime_insight.scheduler")

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    """Jalankan job pipeline tiap UPDATE_INTERVAL detik."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    from .pipeline import run_pipeline

    def _job():
        import asyncio

        logger.info("== Job terjadwal dimulai ==")
        asyncio.run(run_pipeline())

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(seconds=config.UPDATE_INTERVAL),
        id="analysis_pipeline",
        name="Poll & Analisis Data",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler aktif — job tiap %s detik.", config.UPDATE_INTERVAL
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler dihentikan.")


def run_now() -> None:
    """Jalankan satu siklus pipeline secara manual (mis. dari API)."""
    from .pipeline import run_pipeline

    import asyncio

    asyncio.run(run_pipeline())
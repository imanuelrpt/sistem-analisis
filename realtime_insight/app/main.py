"""Entry point FastAPI untuk sistem analisis data real-time.

Menjalankan:
  - REST API:   /api/data, /api/reports/*, /api/health, /api/trigger
  - WebSocket:  /api/ws/live
  - Frontend:   statis dari ./frontend (/static)
  - Scheduler:  pipeline tiap UPDATE_INTERVAL detik

Run:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, database, scheduler
from .routers import data, reports, ws

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("realtime_insight.main")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


async def _run_initial_pipeline() -> None:
    """Jalankan siklus pertama saat startup (dalam background task)."""
    from .pipeline import run_pipeline

    try:
        await run_pipeline()
    except Exception as exc:  # noqa: BLE001 - jangan mematikan server
        logger.error("Pipeline awal gagal: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    logger.info("Inisialisasi database ...")
    database.init_db()
    logger.info("Config aktif: %s", config.summary())

    scheduler.start_scheduler()
    # siklus pertama langsung dijalankan agar dashboard terisi cepat
    task = asyncio.create_task(_run_initial_pipeline())

    yield
    # ---- shutdown ----
    task.cancel()
    scheduler.stop_scheduler()
    logger.info("Aplikasi berhenti.")


app = FastAPI(
    title="Realtime Insight — Analisis Data Real-time",
    description=(
        "Sistem polling data dari public API, analisis otomatis, "
        "kesimpulan LLM, dan update dashboard via WebSocket."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)
app.include_router(reports.router)
app.include_router(ws.router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.post("/api/trigger")
def trigger_manual() -> dict:
    """Jalankan satu siklus pipeline secara manual (untuk demo/test)."""
    import threading

    def _spawn() -> None:
        from .pipeline import run_pipeline

        asyncio.run(run_pipeline())

    threading.Thread(target=_spawn, daemon=True).start()
    return {"status": "queued"}


# Mount static setelah route "/" agar tidak tertimpa
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL,
    )
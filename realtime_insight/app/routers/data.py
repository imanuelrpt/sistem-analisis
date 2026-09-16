"""Router data — endpoint untuk data terkini & statistik kayu.

- GET /api/data           → payload dashboard terbaru (sinkron dengan WS)
- GET /api/data/raw?limit → titik data mentah terbaru
- GET /health             → status layanan + sumber data
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import config, schemas
from ..database import get_db
from ..models import DataPoint
from ..websocket_manager import manager

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/data")
def get_current_data(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Data dashboard terkini (trend, insight, kesimpulan terakhir)."""
    if manager.last_payload:
        return manager.last_payload

    # fallback saat belum ada siklus berjalan: baca snapshot DB terakhir
    from ..models import Conclusion, Insight, StatsSnapshot

    trends: list = []
    snapshots = (
        db.query(StatsSnapshot)
        .order_by(StatsSnapshot.created_at.desc())
        .limit(20)
        .all()
    )
    main_metrics = set(config.main_coin_metrics())
    main_idx = {m: i for i, m in enumerate(config.main_coin_metrics())}
    newest_ts: Any = None
    for snap in reversed(snapshots):
        st = snap.stats
        if not st:
            continue
        if not st.get("series"):
            continue
        newest_ts = snap.window_end
        metric = snap.metric
        trends.append(
            {
                "metric": metric,
                "unit": "",
                "last_value": st["series"][-1]["v"],
                "delta_pct_vs_prev": st.get("delta_pct"),
                "mean": st.get("mean"),
                "median": st.get("median"),
                "stdev": st.get("stdev"),
                "min": st.get("min"),
                "max": st.get("max"),
                "count": st.get("count"),
                "series": st.get("series"),
                "moving_average": st.get("moving_average"),
                "is_main": metric in main_metrics,
            }
        )

    def _sort_key(trend: dict) -> tuple:
        m = trend["metric"]
        if m in main_idx:
            return (0, main_idx[m])
        return (1, m)

    trends.sort(key=_sort_key)

    insights_out = [
        schemas.InsightOut.model_validate(i).model_dump(mode="json")
        for i in db.query(Insight).order_by(Insight.created_at.desc()).limit(30).all()
    ]
    conclusion = db.query(Conclusion).order_by(Conclusion.created_at.desc()).first()

    return {
        "timestamp": newest_ts.isoformat() if newest_ts else None,
        "sources": [config.DATA_SOURCE],
        "trends": trends,
        "insights": insights_out,
        "conclusion": (
            schemas.ConclusionOut.model_validate(conclusion).model_dump(mode="json")
            if conclusion
            else None
        ),
        "cycle": 0,
    }


@router.get("/data/raw")
def get_raw_data(
    metric: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Titik data mentah terbaru (untuk debugging / grafik awal)."""
    q = db.query(DataPoint)
    if metric:
        q = q.filter(DataPoint.metric == metric)
    rows = q.order_by(DataPoint.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "metric": r.metric,
            "value": r.value,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in reversed(rows)
    ]


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "source": config.DATA_SOURCE,
        "config": config.summary(),
        "connected_clients": len(manager._active),
        "has_payload": manager.last_payload is not None,
    }
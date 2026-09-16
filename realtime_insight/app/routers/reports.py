"""Router reports — riwayat insight & kesimpulan (halaman laporan)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conclusion, Insight

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/insights")
def get_insights(
    limit: int = Query(default=100, ge=1, le=1000),
    metric: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Riwayat insight (pola terdeteksi)."""
    q = db.query(Insight)
    if metric:
        q = q.filter(Insight.metric == metric)
    if severity:
        q = q.filter(Insight.severity == severity)
    rows = q.order_by(Insight.created_at.desc()).limit(limit).all()
    return [
        {
            "id": i.id,
            "metric": i.metric,
            "type": i.type,
            "label": i.label,
            "severity": i.severity,
            "delta_pct": i.delta_pct,
            "created_at": i.created_at.isoformat(),
        }
        for i in rows
    ]


@router.get("/conclusions")
def get_conclusions(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Riwayat kesimpulan naratif."""
    rows = db.query(Conclusion).order_by(Conclusion.created_at.desc()).limit(limit).all()
    return [
        {
            "id": c.id,
            "content": c.content,
            "provider": c.provider,
            "trigger_count": len(c.trigger or []),
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


@router.get("/stats")
def get_stats_snapshots(
    metric: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Riwayat snapshot statistik window."""
    from ..models import StatsSnapshot

    q = db.query(StatsSnapshot)
    if metric:
        q = q.filter(StatsSnapshot.metric == metric)
    rows = q.order_by(StatsSnapshot.created_at.desc()).limit(limit).all()
    return [
        {
            "id": s.id,
            "metric": s.metric,
            "window_start": s.window_start.isoformat(),
            "window_end": s.window_end.isoformat(),
            "mean": (s.stats or {}).get("mean"),
            "median": (s.stats or {}).get("median"),
            "count": (s.stats or {}).get("count"),
            "delta_pct": (s.stats or {}).get("delta_pct"),
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]
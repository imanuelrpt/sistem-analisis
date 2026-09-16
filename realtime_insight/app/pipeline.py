"""Pipeline analisis: satu siklus lengkap polling → insight → broadcast.

Urutan per siklus (diulang tiap UPDATE_INTERVAL oleh scheduler):

  1. fetch_latest()        — tarik data dari public API
  2. ingest ke DataPoint SQL → prune > MAX_RECORDS
  3. stats_engine          — statistik window untuk tiap metrik
  4. insight_engine        — rule-based detector
  5. significance check    — bandingkan insight dgn siklus sebelumnya
  6. llm_summarizer        — narasi HANYA jika ada perubahan signifikan
  7. broadcast ke client WebSocket (data_trend + insight + conclusion)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from . import config, schemas
from . import database as Database
from .models import Conclusion, DataPoint, Insight, StatsSnapshot
from .services import insight_engine, llm_summarizer, stats_engine
from .websocket_manager import manager

logger = logging.getLogger("realtime_insight.pipeline")

_RUN_LOCK = threading.Lock()  # cegah overlap antar job


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _window_bounds() -> tuple[
    datetime, datetime, datetime | None, datetime | None
]:
    end = now_utc()
    start = end - timedelta(hours=config.WINDOW_HOURS)
    prev_end = start
    prev_start = start - timedelta(hours=config.PREV_WINDOW_HOURS)
    return start, end, prev_start, prev_end


def ingest_points(db: Session, points: list[dict]) -> int:
    """Simpan titik data mentah ke database."""
    new_count = 0
    for point in points:
        metric = point["metric"]
        value = point["value"]
        dup = (
            db.query(DataPoint)
            .filter(
                DataPoint.metric == metric,
                DataPoint.value == value,
                DataPoint.timestamp > now_utc() - timedelta(seconds=config.UPDATE_INTERVAL),
            )
            .first()
        )
        if dup:
            continue
        db.add(
            DataPoint(
                source=config.DATA_SOURCE,
                metric=metric,
                value=value,
                extra=point.get("extra", {}),
                timestamp=now_utc(),
            )
        )
        new_count += 1
    db.commit()
    return new_count


def prune(db: Session) -> int:
    """Buang data tertua melebihi MAX_RECORDS."""
    total = db.query(DataPoint).count()
    excess = total - config.MAX_RECORDS
    if excess <= 0:
        return 0
    ids = (
        db.query(DataPoint.id)
        .order_by(DataPoint.timestamp.asc())
        .limit(excess)
        .all()
    )
    db.query(DataPoint).filter(
        DataPoint.id.in_([i[0] for i in ids])
    ).delete(synchronize_session=False)
    db.commit()
    return excess


def compute_and_store_stats(
    db: Session, metrics: list[str]
) -> dict[str, stats_engine.StatsResult]:
    """Hitung statistik window utk semua metrik, simpan snapshot + hasil."""
    start, end, prev_start, prev_end = _window_bounds()
    results: dict[str, stats_engine.StatsResult] = {}

    for metric in metrics:
        rows = (
            db.query(DataPoint.timestamp, DataPoint.value)
            .filter(
                DataPoint.metric == metric,
                DataPoint.timestamp >= start,
                DataPoint.timestamp <= end,
            )
            .all()
        )
        prev_rows = []
        if prev_start is not None:
            prev_rows = (
                db.query(DataPoint.timestamp, DataPoint.value)
                .filter(
                    DataPoint.metric == metric,
                    DataPoint.timestamp >= prev_start,
                    DataPoint.timestamp < prev_end,
                )
                .all()
            )

        res = stats_engine.compute_window_stats(
            metric,
            [(t, v) for t, v in rows],
            [(t, v) for t, v in prev_rows],
        )
        results[metric] = res

        snapshot = StatsSnapshot(
            metric=metric,
            window_start=start,
            window_end=end,
            prev_window_start=prev_start,
            prev_window_end=prev_end,
            stats=res.to_dict(),
        )
        db.add(snapshot)

    db.commit()
    return results


def store_insights(
    db: Session,
    insights: list[dict],
    snapshot_by_metric: dict[str, int] | None = None,
) -> list[Insight]:
    """Simpan insight baru ke DB. snapshot_by_metric: id snapshot per metrik."""
    objs: list[Insight] = []
    for ins in insights:
        obj = Insight(
            metric=ins.get("metric", "unknown"),
            type=ins.get("type", "UNKNOWN"),
            label=ins.get("label", ""),
            metric_old=ins.get("metric_old"),
            metric_new=ins.get("metric_new"),
            delta_pct=ins.get("delta_pct"),
            severity=ins.get("severity", "info"),
            details=ins.get("details", {}),
        )
        db.add(obj)
        objs.append(obj)
    db.commit()
    return objs


def store_conclusion(db: Session, content: str, trigger: list[dict], provider: str) -> Conclusion:
    obj = Conclusion(content=content, trigger=trigger, provider=provider)
    db.add(obj)
    db.commit()
    return obj


def build_trend_payload(
    stats_by_metric: dict[str, stats_engine.StatsResult]
) -> list[dict[str, Any]]:
    """Buat daftar TrendSeries utk dashboard dari hasil stats engine.

    Coin utama (config.main_coin_metrics) diurutkan paling depan dan ditandai
    `is_main=True` supaya tetap tampil menonjol walau sumber data makin banyak.
    """
    main_metrics = config.main_coin_metrics()
    main_idx = {m: i for i, m in enumerate(main_metrics)}
    trends: list[dict[str, Any]] = []
    for metric, st in stats_by_metric.items():
        if not st.series:
            continue
        trends.append(
            {
                "metric": metric,
                "unit": "usd" if "usd" in metric else "",
                "last_value": st.series[-1]["v"],
                "delta_pct_vs_prev": st.delta_pct,
                "mean": st.mean,
                "median": st.median,
                "stdev": st.stdev,
                "min": st.min,
                "max": st.max,
                "count": st.count,
                "series": st.series,
                "moving_average": st.moving_average,
                "is_main": metric in main_idx,
            }
        )

    def _sort_key(trend: dict[str, Any]) -> tuple[int, int | str]:
        m = trend["metric"]
        if m in main_idx:
            return (0, main_idx[m])
        return (1, m)

    trends.sort(key=_sort_key)
    return trends


def _last_conclusion(db: Session) -> Conclusion | None:
    return (
        db.query(Conclusion).order_by(Conclusion.created_at.desc()).first()
    )


async def run_pipeline(db: Session | None = None) -> dict[str, Any] | None:
    """Satu siklus penuh analisis. Dipanggil scheduler & startup."""
    if not _RUN_LOCK.acquire(blocking=False):
        logger.warning("Pipeline masih berjalan — lewati siklus ini.")
        return None

    close_after = db is None
    session: Session = db or Database.SessionLocal()

    try:
        from .services import fetcher

        points = await fetcher.fetch_latest()
        if not points:
            logger.warning("Tidak ada data dari sumber — siklus dibatalkan.")
            return None

        ingested = ingest_points(session, points)
        pruned = prune(session)
        logger.info("Masuk %s titik (prune %s).", ingested, pruned)

        metrics = {p["metric"] for p in points}
        stats_by_metric = compute_and_store_stats(session, sorted(metrics))

        # ---------- insight rule-based ----------
        insights_raw = insight_engine.generate_insights(stats_by_metric)

        # ---------- significance check ----------
        last_conc = _last_conclusion(session)
        changed: list[dict] = []
        is_significant = False
        if insights_raw:
            prev_snapshot_insights = (
                session.query(Insight)
                .filter(Insight.created_at >= now_utc() - timedelta(hours=config.WINDOW_HOURS))
                .order_by(Insight.created_at.desc())
                .all()
            )
            prev_insights = [
                {
                    "type": i.type,
                    "metric": i.metric,
                    "delta_pct": i.delta_pct,
                    "metric_old": i.metric_old,
                    "metric_new": i.metric_new,
                    "severity": i.severity,
                    "label": i.label,
                    "details": i.details,
                }
                for i in prev_snapshot_insights
            ]
            is_significant, changed = insight_engine.summarize_significance(
                insights_raw, prev_insights
            )

        is_significant = is_significant or not last_conc

        insight_objs = store_insights(session, insights_raw)

        # ---------- LLM (hanya jika signifikan) ----------
        conclusion = None
        conclusion_out = None
        if is_significant:
            text, provider = await llm_summarizer.generate_conclusion(
                stats_by_metric, insights_raw
            )
            conclusion = store_conclusion(
                session, text, trigger=changed or insights_raw, provider=provider
            )
            conclusion_out = schemas.ConclusionOut.model_validate(conclusion)
            logger.info("Kesimpulan LLM (%s) disimpan & signifikan.", provider)
        else:
            logger.info("Tidak ada perubahan signifikan — LLM dilewati.")

        # ---------- broadcast ----------
        trends = build_trend_payload(stats_by_metric)
        payload = {
            "timestamp": now_utc().isoformat(),
            "sources": [config.DATA_SOURCE],
            "trends": trends,
            "insights": [
                schemas.InsightOut.model_validate(i).model_dump(mode="json")
                for i in insight_objs
            ],
            "conclusion": (
                conclusion_out.model_dump(mode="json")
                if conclusion_out
                else None
            ),
            "cycle": _cycle_counter(),
        }
        await manager.broadcast(payload)

        logger.info(
            "Siklus selesai: %s metrik, %s insight, kesimpulan=%s",
            len(metrics),
            len(insights_raw),
            "ya" if conclusion else "tidak",
        )
        return payload

    finally:
        _RUN_LOCK.release()
        if close_after:
            session.close()


def _cycle_counter() -> int:
    if not hasattr(_cycle_counter, "value"):
        _cycle_counter.value = 0
    _cycle_counter.value += 1
    return _cycle_counter.value
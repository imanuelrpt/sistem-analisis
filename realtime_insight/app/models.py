"""Model SQLAlchemy untuk penyimpanan data, statistik, insight, dan kesimpulan."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataPoint(Base):
    """Satu titik data mentah hasil polling API eksternal."""

    __tablename__ = "data_points"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False, index=True)
    metric = Column(String(100), nullable=False, index=True)
    value = Column(Float, nullable=False)
    extra = Column(JSON, default=dict)
    timestamp = Column(DateTime, nullable=False, index=True, default=_utcnow)


class StatsSnapshot(Base):
    """Ringkasan statistik satu jendela waktu untuk satu metrik."""

    __tablename__ = "stats_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    metric = Column(String(100), nullable=False, index=True)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    prev_window_start = Column(DateTime, nullable=True)
    prev_window_end = Column(DateTime, nullable=True)
    stats = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Insight(Base):
    """Hasil deteksi pola rule-based (trend, spike, outliers, korelasi)."""

    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, index=True)
    metric = Column(String(100), nullable=False, index=True)
    type = Column(String(50), nullable=False)
    label = Column(String(300), nullable=False)
    metric_old = Column(Float, nullable=True)
    metric_new = Column(Float, nullable=True)
    delta_pct = Column(Float, nullable=True)
    severity = Column(String(20), nullable=False, default="info")
    details = Column(JSON, default=dict)
    snapshot_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Conclusion(Base):
    """Kesimpulan naratif Bahasa Indonesia hasil LLM summarizer."""

    __tablename__ = "conclusions"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    trigger = Column(JSON, default=list)
    provider = Column(String(50), nullable=False, default="mock")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
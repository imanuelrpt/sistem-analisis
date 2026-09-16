"""Skema Pydantic untuk request/response API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class DataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    metric: str
    value: float
    extra: Optional[dict[str, Any]] = None
    timestamp: datetime


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metric: str
    type: str
    label: str
    metric_old: Optional[float] = None
    metric_new: Optional[float] = None
    delta_pct: Optional[float] = None
    severity: str
    created_at: datetime


class ConclusionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    provider: str
    created_at: datetime


class TrendSeries(BaseModel):
    """Data deret waktu yang dikirim ke dashboard."""

    metric: str
    unit: str
    last_value: float
    delta_pct_vs_prev: float
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    series: list[dict[str, Any]]
    points: list[dict[str, Any]]


class DashboardPayload(BaseModel):
    """Payload WebSocket & GET /api/data terbaru."""

    timestamp: datetime
    sources: list[str]
    trends: list[TrendSeries]
    insights: list[InsightOut]
    conclusion: Optional[ConclusionOut] = None
    cycle: int


class ReportOut(BaseModel):
    id: int
    metric: str
    type: str
    label: str
    severity: str
    delta_pct: Optional[float] = None
    created_at: datetime


class ConclusionReportOut(BaseModel):
    id: int
    content: str
    provider: str
    trigger_count: int
    created_at: datetime
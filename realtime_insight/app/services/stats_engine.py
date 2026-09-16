"""Stats engine: menghitung statistik jendela waktu untuk tiap metrik.

Semua fungsi murni (pure function) sehingga mudah di-unit-test dan
dipakai ulang dari pipeline.

Output `StatsResult` per metrik:
    - seri deret waktu [{"t": iso, "v": float}]
    - mean, median, stdev, min, max, count
    - perubahan % vs jendela sebelumnya
    - moving average 5-titik
    - deteksi outlier (IQR) + spike > 2 stdev
    - trend (linear regression slope)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .. import config


@dataclass
class StatsResult:
    metric: str
    series: list[dict[str, Any]] = field(default_factory=list)
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    min: float | None = None
    max: float | None = None
    count: int = 0
    prev_mean: float | None = None
    delta_pct: float | None = None  # vs plain text mean jendela sebelumnya
    change_abs: float | None = None
    moving_average: list[float] = field(default_factory=list)
    outliers: list[dict[str, Any]] = field(default_factory=list)
    trends: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "series": self.series,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "min": self.min,
            "max": self.max,
            "count": self.count,
            "prev_mean": self.prev_mean,
            "delta_pct": self.delta_pct,
            "change_abs": self.change_abs,
            "moving_average": self.moving_average,
            "outliers": self.outliers,
            "trends": self.trends,
        }


def _as_values(points: Iterable[tuple[datetime, float]]) -> list[float]:
    return [v for _, v in points]


def compute_window_stats(
    metric: str,
    data: Iterable[tuple[datetime, float]],
    prev_data: Iterable[tuple[datetime, float]],
    window_seconds: int | None = None,
    ma_period: int = 5,
    stdev_threshold: float = 2.0,
) -> StatsResult:
    """Hitung statistik untuk satu metrik.

    data      : titik (timestamp, value) di jendela saat ini
    prev_data : titik di jendela sebelumnya (untuk delta %)
    """
    rows = list(data)
    prev_rows = list(prev_data)
    rows.sort(key=lambda r: r[0])

    res = StatsResult(metric=metric)
    values = _as_values(rows)

    if values:
        res.count = len(values)
        res.mean = float(statistics.mean(values))
        res.median = float(statistics.median(values))
        res.min = float(min(values))
        res.max = float(max(values))
        res.stdev = (
            float(statistics.stdev(values)) if len(values) >= 2 else 0.0
        )

        # moving average
        res.moving_average = _moving_average(values, ma_period)

        # seri deret waktu (turunkan resolusi jika terlalu panjang)
        res.series = [
            {"t": t.isoformat(), "v": v} for t, v in rows
        ]

        # delta % vs jendela sebelumnya
        prev_values = _as_values(prev_rows)
        if prev_values:
            res.prev_mean = float(statistics.mean(prev_values))
            res.change_abs = res.mean - res.prev_mean
            res.delta_pct = _safe_delta_pct(
                res.mean, res.prev_mean, zero_based=_is_zero_based(metric)
            )

        # outlier (IQR) dan spike (di luar thresh stdev)
        res.outliers = _detect_outliers(rows, stdev_threshold)

        # tren via regresi linier slope (dinormalisasi per jam)
        res.trends = _linear_trend(rows)

    return res


def _is_zero_based(metric: str) -> bool:
    return metric in config.FLOAT_ZERO_BASED


def _safe_delta_pct(new: float, old: float, zero_based: bool = False) -> float | None:
    """Hitung perubahan persen antar dua nilai.

    Untuk metrik murni positif (harga, indeks): (new - old) / old * 100.
    Untuk metrik zero-based (suhu dapat bernilai 0/negatif): pakai delta
    yang dinormalisasi terhadap span supaya tidak menghasilkan inf.
    """
    if old == 0:
        if new == 0:
            return 0.0
        # fallback: tanpa basis numerik yang aman, pakai delta absolut
        return None
    if zero_based:
        span = max(abs(new), abs(old))
        if span == 0:
            return 0.0
        return (new - old) / span * 100.0
    return (new - old) / old * 100.0


def _moving_average(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    out: list[float] = []
    for i in range(len(values)):
        window = values[max(0, i - period + 1): i + 1]
        out.append(float(statistics.mean(window)))
    return out


def _detect_outliers(
    rows: list[tuple[datetime, float]], stdev_threshold: float
) -> list[dict[str, Any]]:
    """Deteksi outlier IQR dan spike stdev."""
    if len(rows) < 4:
        return []
    values = [v for _, v in rows]
    q1, q3 = _quartiles(values)
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) >= 2 else 0.0

    outliers: list[dict[str, Any]] = []
    for t, v in rows:
        reasons = []
        if iqr > 1e-12 and (v < lo or v > hi):
            reasons.append("iqr")
        if stdev > 1e-12 and abs(v - mean) > stdev_threshold * stdev:
            reasons.append("spike")
        if reasons:
            outliers.append(
                {
                    "t": t.isoformat(),
                    "v": v,
                    "z": (v - mean) / stdev if stdev > 1e-12 else None,
                    "reasons": reasons,
                }
            )
    return outliers


def _quartiles(values: list[float]) -> tuple[float, float]:
    s = sorted(values)
    n = len(s)
    q1 = s[int(n * 0.25)]
    q3 = s[int(n * 0.75)]
    return float(q1), float(q3)


def _linear_trend(rows: list[tuple[datetime, float]]) -> dict[str, float]:
    """Slope regresi linier atas deret waktu, dinormalisasi slope/jam.

    slope_temp = perubahan nilai per jam. slope_norm = slope / mean
    (perubahan relatif per jam). positive = naik, negative = turun.
    """
    if len(rows) < 2:
        return {}
    t0 = rows[0][0].timestamp()
    xs = [t.timestamp() - t0 for t, _ in rows]
    ys = [v for _, v in rows]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0 or mean_y == 0:
        return {}
    slope = num / den
    return {
        "slope_per_hour": slope * 3600.0,
        "slope_norm_per_hour": (slope / mean_y) * 3600.0,
    }


def delta_between(
    new: float, old: float, metric: str = ""
) -> float | None:
    """Kecil helper agar mudah dipanggil di tempat lain."""
    return _safe_delta_pct(new, old, zero_based=_is_zero_based(metric))
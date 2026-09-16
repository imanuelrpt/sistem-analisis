"""Unit test untuk stats_engine (statistik jendela waktu)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.stats_engine import (
    _safe_delta_pct,
    compute_window_stats,
    delta_between,
)

# FLOAT_ZERO_BASED memuat "temperature_2m" (bisa bernilai 0/negatif)
ZERO_BASED = "temperature_2m"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_empty_data_returns_defaults():
    res = compute_window_stats("btc/usd", [], [])
    assert res.count == 0
    assert res.mean is None
    assert res.median is None
    assert res.stdev is None
    assert res.min is None
    assert res.max is None
    assert res.series == []
    assert res.delta_pct is None


def test_basic_statistics():
    t0 = _now()
    data = [
        (t0, 10.0),
        (t0 + timedelta(minutes=1), 20.0),
        (t0 + timedelta(minutes=2), 30.0),
    ]
    prev = [(t0 - timedelta(hours=2), 10.0)]
    res = compute_window_stats("btc/usd", data, prev)

    assert res.count == 3
    assert res.mean == pytest.approx(20.0)
    assert res.median == pytest.approx(20.0)
    assert res.min == pytest.approx(10.0)
    assert res.max == pytest.approx(30.0)
    assert res.delta_pct == pytest.approx(100.0)
    assert res.change_abs == pytest.approx(10.0)
    assert len(res.series) == 3
    assert res.series[0]["t"] == t0.isoformat()
    assert res.series[0]["v"] == 10.0


def test_stdev_for_single_point_is_zero():
    res = compute_window_stats("eth/usd", [(_now(), 5.0)], [])
    assert res.count == 1
    assert res.stdev == 0.0


def test_moving_average():
    t0 = _now()
    data = [(t0 + timedelta(minutes=i), float(v)) for i, v in enumerate([1, 2, 3, 4, 5])]
    res = compute_window_stats("btc/usd", data, [])
    # period=5: window makin besar sampai penuh
    assert res.moving_average == pytest.approx([1.0, 1.5, 2.0, 2.5, 3.0])


def test_outlier_detection():
    t0 = _now()
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 50]  # 50 = outlier IQR + spike
    data = [(t0 + timedelta(minutes=i), v) for i, v in enumerate(vals)]
    res = compute_window_stats("btc/usd", data, [])
    assert res.outliers, "harus ada outlier"
    assert res.outliers[-1]["v"] == 50.0
    assert set(res.outliers[-1]["reasons"]) >= {"iqr", "spike"}


def test_linear_trend_positive():
    t0 = _now()
    data = [
        (t0 + timedelta(minutes=i), float(i + 1)) for i in range(10)
    ]
    res = compute_window_stats("btc/usd", data, [])
    assert res.trends["slope_per_hour"] > 0


def test_delta_pct_positive_metric():
    assert _safe_delta_pct(120.0, 100.0) == pytest.approx(20.0)
    assert _safe_delta_pct(80.0, 100.0) == pytest.approx(-20.0)
    assert _safe_delta_pct(100.0, 100.0) == pytest.approx(0.0)


def test_delta_pct_zero_old_returns_none():
    # metrik normal tidak boleh berbasis nol -> fallback None
    assert _safe_delta_pct(10.0, 0.0) is None
    assert _safe_delta_pct(0.0, 0.0) == 0.0


def test_delta_pct_zero_based_metric():
    # suhu bisa 0/negatif: normalisasi terhadap span (old != 0)
    assert delta_between(-5.0, 5.0, ZERO_BASED) == pytest.approx(-200.0)
    assert delta_between(0.0, 0.0, ZERO_BASED) == pytest.approx(0.0)
    # old == 0 tetap tak-terhitung (fallback delta absolut -> None)
    assert delta_between(10.0, 0.0, ZERO_BASED) is None
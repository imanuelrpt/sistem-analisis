"""Unit test untuk insight_engine (deteksi pola rule-based)."""

from app.services import insight_engine
from app.services.insight_engine import InsightFactory, generate_insights, summarize_significance
from app.services.stats_engine import StatsResult


def _st(metric, **kwargs) -> StatsResult:
    defaults = {
        "metric": metric,
        "series": [],
        "moving_average": [],
        "outliers": [],
        "delta_pct": None,
        "prev_mean": None,
        "mean": None,
    }
    defaults.update(kwargs)
    return StatsResult(**defaults)


def test_all_rules_attach_metric_key():
    factory = InsightFactory(significant_pct=5.0)

    # PRICE_JUMP + MA_TREND + SPIKE untuk satu metrik
    stats = {
        "btc/usd": _st(
            "btc/usd",
            mean=120.0,
            prev_mean=100.0,
            delta_pct=20.0,
            moving_average=[1, 2, 3, 4, 5],
            outliers=[
                {"t": "2026-01-01T00:00:00+00:00", "v": 999.0, "z": 3.5, "reasons": ["spike"]}
            ],
        )
    }
    found = set()
    for ins in factory.run(stats):
        assert "metric" in ins, f"insight {ins.get('type')} tanpa metric"
        assert ins["metric"] == "btc/usd"
        found.add(ins["type"])
    assert found >= {"PRICE_JUMP", "MA_TREND", "SPIKE"}


def test_price_jump_severity_critical():
    st = _st("btc/usd", mean=120.0, prev_mean=100.0, delta_pct=20.0)
    ins = InsightFactory(significant_pct=5.0).run({"btc/usd": st})
    price = [i for i in ins if i["type"] == "PRICE_JUMP"]
    assert len(price) == 1
    assert price[0]["severity"] == "critical"  # critical_pct = 3 * 5 = 15%
    assert price[0]["delta_pct"] == 20.0


def test_no_insight_below_threshold():
    st = _st("btc/usd", mean=102.0, prev_mean=100.0, delta_pct=2.0)
    assert InsightFactory(significant_pct=5.0).run({"btc/usd": st}) == []


def test_moving_average_rule_downward():
    st = _st("eth/usd", moving_average=[10, 9, 8, 7, 6])
    ins = InsightFactory().run({"eth/usd": st})
    ma = [i for i in ins if i["type"] == "MA_TREND"]
    assert len(ma) == 1
    assert "monoton turun" in ma[0]["label"]
    assert ma[0]["details"]["direction"] == "menurun"
    assert ma[0]["metric_new"] == 6.0


def test_moving_average_rule_upward():
    st = _st("eth/usd", moving_average=[6, 7, 8, 9, 10])
    ins = InsightFactory().run({"eth/usd": st})
    ma = [i for i in ins if i["type"] == "MA_TREND"]
    assert len(ma) == 1
    assert "monoton naik" in ma[0]["label"]
    assert ma[0]["details"]["direction"] == "meningkat"


def test_correlation_rule():
    series = [
        {"t": f"2026-01-0{i}T00:00:00+00:00", "v": float(i)} for i in range(3, 8)
    ]
    stats = {
        "a/usd": _st("a/usd", series=series),
        "b/usd": _st("b/usd", series=series),  # identik -> korelasi 1.0:1 sebanyak 5
    }
    ins = InsightFactory().run(stats)
    corr = [i for i in ins if i["type"] == "CORRELATION"]
    assert len(corr) == 1
    assert corr[0]["metric"] == "a/usd ↔ b/usd"
    assert abs(corr[0]["details"]["pearson"] - 1.0) < 1e-6


def test_summarize_significance_new_insight():
    ins = [{"type": "PRICE_JUMP", "metric": "btc/usd", "delta_pct": 10.0}]
    sig, changed = summarize_significance(ins, [])
    assert sig is True
    assert changed == ins


def test_summarize_significance_identical():
    ins = [{"type": "PRICE_JUMP", "metric": "btc/usd", "delta_pct": 10.0}]
    sig, changed = summarize_significance(ins, ins)
    assert sig is False
    assert changed == []


def test_summarize_significance_shift_past_threshold():
    prev = [{"type": "PRICE_JUMP", "metric": "btc/usd", "delta_pct": 4.0}]
    new = [{"type": "PRICE_JUMP", "metric": "btc/usd", "delta_pct": 10.0}]
    sig, changed = summarize_significance(new, prev)
    assert sig is True
    assert len(changed) == 1
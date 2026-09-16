"""Insight engine: deteksi pola & signifikansi berbasis rule.

Masukan: hasil StatsResult untuk tiap metrik (dari stats_engine).
Keluaran: list pola terstruktur berbentuk dict:

    {
      "type": "PRICE_JUMP",
      "label": "Harga btc/usd naik 6,2% dalam jendela 1 jam terakhir",
      "metric_old": 1510500.0,
      "metric_new": 1604000.0,
      "delta_pct": 6.2,
      "severity": "high",
      "details": {...},
    }

severity: "info" / "warning" / "critical" (critical untuk delta >= critical_pct)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from .. import config
from .stats_engine import StatsResult


@dataclass
class InsightFactory:
    significant_pct: float = config.SIGNIFICANT_PCT
    critical_pct: float = 3 * config.SIGNIFICANT_PCT
    ma_consecutive_periods: int = 3
    spike_stdev: float = 2.0
    correlation_threshold: float = 0.7

    def _severity(self, delta_pct: float | None) -> str:
        if delta_pct is None:
            return "info"
        if abs(delta_pct) >= self.critical_pct:
            return "critical"
        if abs(delta_pct) >= self.significant_pct:
            return "warning"
        return "info"

    def run(self, stats_by_metric: dict[str, StatsResult]) -> list[dict[str, Any]]:
        """Jalankan semua rule untuk seluruh metrik yang ada."""
        insights: list[dict[str, Any]] = []
        for metric, st in stats_by_metric.items():
            insights.extend(self._rule_delta(st))
            insights.extend(self._rule_moving_average(st))
            insights.extend(self._rule_spike(st))
        insights.extend(self._rule_correlation(stats_by_metric))
        return insights

    # ------------------------------------------------------------------
    # Rule 1: perubahan % (harga naik/turun melewati threshold)
    # ------------------------------------------------------------------
    def _rule_delta(self, st: StatsResult) -> list[dict]:
        if st.delta_pct is None or st.prev_mean is None:
            return []
        delta = st.delta_pct
        if abs(delta) < self.significant_pct:
            return []

        action = "naik" if delta > 0 else "turun"
        icon = "▲" if delta > 0 else "▼"
        return [{
            "type": "PRICE_JUMP",
            "metric": st.metric,
            "label": (
                f"{icon} {st.metric} {action} {abs(delta):.1f}% "
                f"({st.prev_mean:.4g} → {st.mean:.4g}) dalam jendela "
                f"{config.WINDOW_HOURS} jam terakhir"
            ),
            "metric_old": st.prev_mean,
            "metric_new": st.mean,
            "delta_pct": round(delta, 2),
            "severity": self._severity(delta),
            "details": {
                "reason": "delta_pct >= significant threshold",
                "window": config.WINDOW_HOURS,
            },
        }]

    # ------------------------------------------------------------------
    # Rule 2: moving average turun (atau naik) beruntun
    # ------------------------------------------------------------------
    def _rule_moving_average(self, st: StatsResult) -> list[dict]:
        n = self.ma_consecutive_periods
        if len(st.moving_average) < n + 1:
            return []

        trend_label = self._consecutive_trend_label(st.moving_average, n)
        if trend_label is None:
            return []

        direction = "menurun" if trend_label.startswith("menurun") else "meningkat"
        full = "monoton turun" if direction == "menurun" else "monoton naik"
        return [{
            "type": "MA_TREND",
            "metric": st.metric,
            "label": (
                f"Moving average {st.metric} {full} selama "
                f"{n} periode berturut-turut (jendela {config.WINDOW_HOURS} jam)"
            ),
            "metric_old": st.moving_average[-1 - n],
            "metric_new": st.moving_average[-1],
            "delta_pct": None,
            "severity": "info",
            "details": {"periods": n, "direction": direction},
        }]

    def _consecutive_trend_label(
        self, series: list[float], n: int
    ) -> str | None:
        """Deteksi n periode akhir bergerak monoton naik/turun."""
        tail = series[-n - 1:]
        if len(tail) != n + 1:
            return None
        if all(b > a for a, b in zip(tail, tail[1:])):
            return f"meningkat {n} periode"
        if all(b < a for a, b in zip(tail, tail[1:])):
            return f"menurun {n} periode"
        return None

    # ------------------------------------------------------------------
    # Rule 3: spike / outlier > 2 stdev
    # ------------------------------------------------------------------
    def _rule_spike(self, st: StatsResult) -> list[dict]:
        if not st.outliers:
            return []
        latest = st.outliers[-1]  # outlier terbaru dalam window
        # hanya spike yang benar-benar melewati threshold stdev
        z = latest.get("z")
        if z is None or abs(z) < self.spike_stdev:
            return []

        direction = "meledak" if z > 0 else "merosot"
        return [{
            "type": "SPIKE",
            "metric": st.metric,
            "label": (
                f"⚡ {st.metric} {direction} ({latest['v']:.4g}) pada "
                f"{latest['t']}, {abs(z):.1f} stdev dari rata-rata"
            ),
            "metric_old": st.mean,
            "metric_new": latest["v"],
            "delta_pct": None,
            "severity": "warning",
            "details": {"z": round(z, 2), "t": latest["t"]},
        }]

    # ------------------------------------------------------------------
    # Rule 4: korelasi antar metrik > threshold
    # ------------------------------------------------------------------
    def _rule_correlation(
        self, stats_by_metric: dict[str, StatsResult]
    ) -> list[dict]:
        metrics = list(stats_by_metric.keys())
        if len(metrics) < 2:
            return []
        insights: list[dict] = []
        for i in range(len(metrics)):
            for j in range(i + 1, len(metrics)):
                a, b = metrics[i], metrics[j]
                corr = self._pearson(stats_by_metric[a], stats_by_metric[b])
                if math.isnan(corr) or math.isinf(corr):
                    continue
                if abs(corr) >= self.correlation_threshold:
                    insights.append({
                        "type": "CORRELATION",
                        "metric": f"{a} ↔ {b}",
                        "label": (
                            f"🔗 Korelasi {a} vs {b} sebesar {corr:.2f} "
                            f"(> {self.correlation_threshold:.1f})"
                        ),
                        "metric_old": None,
                        "metric_new": None,
                        "delta_pct": None,
                        "severity": "info",
                        "details": {"pearson": round(corr, 3)},
                    })
        return insights

    def _pearson(self, a: StatsResult, b: StatsResult) -> float:
        va = {p["t"]: p["v"] for p in a.series}
        vb = {p["t"]: p["v"] for p in b.series}
        common_t = [t for t in va if t in vb]
        if len(common_t) < 3:
            return float("nan")
        xs = [va[t] for t in common_t]
        ys = [vb[t] for t in common_t]
        return _pearson_coef(xs, ys)


def _pearson_coef(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return float("nan")
    return num / (dx * dy)


def generate_insights(
    stats_by_metric: dict[str, StatsResult],
    significant_pct: float = config.SIGNIFICANT_PCT,
) -> list[dict[str, Any]]:
    """API utama — bangun insight baru dari hasil stats engine."""
    factory = InsightFactory(significant_pct=significant_pct)
    return factory.run(stats_by_metric)


def summarize_significance(
    insights: list[dict[str, Any]], previous_insights: list[dict[str, Any]]
) -> tuple[bool, list[dict[str, Any]]]:
    """Cek apakah ada perubahan signifikan vs insight terakhir.

    Mengembalikan (is_significant, insights_yang_berubah).
    Suatu insight dianggap "berubah" jika tipenya tidak ada sebelumnya,
    atau delta_pct berubah melewati ambang SIGNIFICANT_PCT.
    """
    prev_lookup: dict[str, dict] = {}
    for p in previous_insights:
        key = (p.get("type"), p.get("metric"))
        prev = prev_lookup.get(key)
        if prev is None or abs(p.get("delta_pct") or 0) > abs(prev.get("delta_pct") or 0):
            prev_lookup[key] = p

    changed: list[dict[str, Any]] = []
    for ins in insights:
        key = (ins.get("type"), ins.get("metric"))
        prev = prev_lookup.get(key)
        if prev is None:
            changed.append(ins)
            continue
        pd = prev.get("delta_pct") or 0.0
        nd = ins.get("delta_pct") or 0.0
        # jenis pola baru, atau pergerakan delta melewati ambang baru
        if abs(nd - pd) >= config.SIGNIFICANT_PCT:
            changed.append(ins)
        elif ins.get("delta_pct") is None and prev.get("delta_pct") is None:
            # pola non-numerik (MA_TREND/SPIKE) dianggap sama jika waktu sama
            if prev.get("details", {}).get("t") != ins.get("details", {}).get("t"):
                changed.append(ins)

    return (len(changed) > 0), changed
"""Unit test untuk llm_summarizer (kesimpulan naratif)."""

import asyncio

from app import config
from app.services import llm_summarizer
from app.services.stats_engine import StatsResult


def _st(metric, mean, delta_pct, last) -> StatsResult:
    return StatsResult(
        metric=metric,
        series=[{"t": "2026-01-01T00:00:00+00:00", "v": last}],
        mean=mean,
        prev_mean=100.0,
        delta_pct=delta_pct,
    )


def test_build_prompt_contains_metric_and_insight():
    stats = {"btc/usd": _st("btc/usd", mean=110.0, delta_pct=10.0, last=112.0)}
    insights = [
        {
            "type": "PRICE_JUMP",
            "metric": "btc/usd",
            "label": "btc/usd naik 10%",
            "severity": "warning",
            "delta_pct": 10.0,
        }
    ]
    prompt = llm_summarizer.build_prompt(stats, insights)
    assert "btc/usd" in prompt
    assert "PRICE_JUMP" in prompt
    assert "110" in prompt


def test_mock_conclusion_no_insights():
    stats = {"btc/usd": _st("btc/usd", mean=100.0, delta_pct=0.0, last=100.0)}
    text = llm_summarizer._mock_conclusion(stats, [])
    assert "Tidak ada perubahan signifikan" in text


def test_mock_conclusion_with_spike():
    stats = {"btc/usd": _st("btc/usd", mean=110.0, delta_pct=10.0, last=112.0)}
    insights = [
        {"type": "SPIKE", "severity": "warning", "label": "btc/usd meledak"},
        {"type": "MA_TREND", "severity": "info", "label": "MA naik"},
    ]
    text = llm_summarizer._mock_conclusion(stats, insights)
    assert "Pola paling menonjol" in text
    assert "lonjakan/penurunan tajam" in text


def test_generate_conclusion_mock_when_disabled():
    assert config.LLM_ENABLED is False  # sudah diset False di conftest
    stats = {"btc/usd": _st("btc/usd", mean=110.0, delta_pct=10.0, last=112.0)}
    insights = [{"type": "PRICE_JUMP", "severity": "warning", "label": "naik"}]

    async def _run():
        return await llm_summarizer.generate_conclusion(stats, insights)

    text, provider = asyncio.run(_run())
    assert provider == "mock"
    assert isinstance(text, str) and text
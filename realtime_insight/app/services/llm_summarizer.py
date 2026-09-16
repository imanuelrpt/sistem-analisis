"""LLM summarizer: ubah insight terstruktur menjadi kesimpulan naratif.

Provider:
  - mock   : template berbasis aturan, tanpa ketergantungan eksternal.
  - ollama : POST ke server Ollama lokal (mis. llama3.2).
  - openai : POST ke API OpenAI-compatible (chat completions).

Jika LLM_ENABLED=False atau provider gagal, otomatis jatuh ke mock
sehingga pipeline tetap berjalan.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx

from .. import config

logger = logging.getLogger("realtime_insight.llm")

_SYSTEM_PROMPT = (
    "Anda adalah analis data real-time. Ringkas dalam Bahasa Indonesia "
    "dengan gaya naratif, maksimal 3 kalimat."
)

_PROMPT_TEMPLATE = (
    "Data terakhir (waktu: {now}):\n"
    "Metrik yang dianalisis:\n{metrics}\n\n"
    "Pola/insight terdeteksi:\n{insights}\n\n"
    "Tugas: Ringkas perubahan paling penting, dugaan penyebab, dan "
    "rekomendasi tindakan. Maksimal 3 kalimat dalam Bahasa Indonesia."
)


class LLMError(RuntimeError):
    pass


def _indent_lines(blocks: list[str]) -> str:
    return "\n".join(f"- {b}" for b in blocks if b) or "(tidak ada)"


def _format_number(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.4g}"


def build_prompt(stats_by_metric: dict, insights: list[dict]) -> str:
    metric_lines = []
    for metric, st in stats_by_metric.items():
        metric_lines.append(
            f"{metric}: rata2={_format_number(getattr(st, 'mean', None))}, "
            f"terakhir={_format_number(getattr(st, 'series', [])[-1]['v'] if getattr(st, 'series', []) else None)}, "
            f"delta%={getattr(st, 'delta_pct', None)}"
        )
    insight_lines = [
        f"[{ins.get('severity', 'info').upper()}] "
        f"{ins.get('type')}: {ins.get('label')} "
        f"(delta_pct={ins.get('delta_pct')})"
        for ins in insights
    ]
    now = datetime.now().strftime("%d %b %Y %H:%M")
    return _PROMPT_TEMPLATE.format(
        now=now,
        metrics=_indent_lines(metric_lines),
        insights=_indent_lines(insight_lines),
    )


async def generate_conclusion(
    stats_by_metric: dict,
    insights: list[dict],
) -> tuple[str, str]:
    """Buat kesimpulan naratif. Mengembalikan (text, provider)."""
    if not config.LLM_ENABLED:
        return _mock_conclusion(stats_by_metric, insights), "mock"

    provider = config.LLM_PROVIDER
    try:
        if provider == "ollama":
            return await _ollama_conclusion(stats_by_metric, insights), "ollama"
        if provider == "openai":
            return await _openai_conclusion(stats_by_metric, insights), "openai"
    except Exception as exc:  # noqa: BLE001 - fallback aman
        logger.warning("LLM %s gagal (%s), fallback ke mock.", provider, exc)

    return _mock_conclusion(stats_by_metric, insights), "mock"


# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------
async def _openai_conclusion(stats_by_metric: dict, insights: list[dict]) -> str:
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY kosong")
    prompt = build_prompt(stats_by_metric, insights)
    payload = {
        "model": config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 300,
    }
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
        resp = await client.post(
            config.OPENAI_BASE_URL, json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
async def _ollama_conclusion(stats_by_metric: dict, insights: list[dict]) -> str:
    prompt = build_prompt(stats_by_metric, insights)
    full_prompt = f"{_SYSTEM_PROMPT}\n\n{prompt}"
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 300},
    }
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
        resp = await client.post(config.OLLAMA_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return (data.get("response") or "").strip()


# ---------------------------------------------------------------------------
# Mock / template-based
# ---------------------------------------------------------------------------
def _mock_conclusion(stats_by_metric: dict, insights: list[dict]) -> str:
    """Kesimpulan template Bahasa Indonesia tanpa LLM eksternal."""
    parts: list[str] = []
    for metric, st in stats_by_metric.items():
        delta = getattr(st, "delta_pct", None)
        prev = getattr(st, "prev_mean", None)
        cur = getattr(st, "mean", None)
        if delta is not None and prev is not None and cur is not None:
            act = "naik" if delta > 0 else "turun"
            parts.append(
                f"Dalam {config.WINDOW_HOURS} jam terakhir {metric} {act} "
                f"{abs(delta):.2f}% ({prev:.5g} → {cur:.5g})"
            )

    if not insights:
        parts.append("Tidak ada perubahan signifikan yang terdeteksi pada siklus ini.")
        return " ".join(parts)

    sev = sorted(insights, key=lambda i: {"info": 0, "warning": 1, "critical": 2}.get(i.get("severity"), 1), reverse=True)
    top = sev[0]
    parts.append(
        f"Pola paling menonjol: {top.get('label', top.get('type', ''))}."
    )
    if any(i.get("type") == "SPIKE" for i in insights):
        parts.append(
            "Terjadi lonjakan/penurunan tajam melewati batas normal; "
            "perlu pemantauan lebih ketat."
        )
    else:
        parts.append(
            "Disarankan memantau arah pergerakan dan waspadai koreksi "
            "jika momentum mulai menurun."
        )
    return " ".join(parts)


def raw_insights_to_json(insights: list[dict]) -> str:
    return json.dumps(insights, ensure_ascii=False, default=str)
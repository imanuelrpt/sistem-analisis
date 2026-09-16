"""Konfigurasi sentral sistem analisis data real-time.

Semua threshold, interval jadwal, sumber data, dan pengaturan LLM
berada di sini. Nilai dapat di-override lewat environment variables
(lihat .env / Docker / deployment) agar tidak perlu mengubah kode.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _str(name: str, default: str) -> str:
    return os.getenv(name, default) or default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Jadwal & threshold
# ---------------------------------------------------------------------------
UPDATE_INTERVAL = _int("UPDATE_INTERVAL", 600)        # detik (10 menit)
SIGNIFICANT_PCT = _float("SIGNIFICANT_PCT", 5.0)      # LLM regen jika delta > %
WINDOW_HOURS = _int("WINDOW_HOURS", 1)                # jendela statistik (jam)
PREV_WINDOW_HOURS = _int("PREV_WINDOW_HOURS", 1)      # jendela pembanding delta
MAX_RECORDS = _int("MAX_RECORDS", 10000)              # batas simpan titik data

# ---------------------------------------------------------------------------
# Basis data
# ---------------------------------------------------------------------------
DATABASE_URL = _str("DATABASE_URL", "sqlite:///./insight.db")

# ---------------------------------------------------------------------------
# Sumber data eksternal (public API)
# ---------------------------------------------------------------------------
# Pilihan: "coingecko" | "openmeteo"
DATA_SOURCE = _str("DATA_SOURCE", "coingecko")

# CoinGecko — harga kripto (gratis, tanpa API key)
COINGECKO_URL = _str(
    "COINGECKO_URL",
    "https://api.coingecko.com/api/v3/simple/price",
)
COINGECKO_IDS = _str(
    "COINGECKO_IDS",
    "bitcoin,ethereum,binancecoin",
)
COINGECKO_VS_CURRENCIES = _str("COINGECKO_VS_CURRENCIES", "usd")
# Coin yang dianggap "utama" — selalu ditampilkan paling depan di dashboard.
COINGECKO_MAIN_COINS = _str("COINGECKO_MAIN_COINS", "bitcoin,binancecoin,ethereum")


def main_coin_metrics() -> list[str]:
    """Daftar metrik (mis. 'bitcoin/usd') untuk coin utama, urut sesuai config."""
    vs = COINGECKO_VS_CURRENCIES.strip()
    coins = [c.strip() for c in COINGECKO_MAIN_COINS.split(",") if c.strip()]
    return [f"{coin}/{vs}" for coin in coins]

# Open-Meteo — cuaca (gratis, tanpa API key)
OPENMETEO_URL = _str("OPENMETEO_URL", "https://api.open-meteo.com/v1/forecast")
OPENMETEO_LAT = _float("OPENMETEO_LAT", -6.2088)
OPENMETEO_LON = _float("OPENMETEO_LON", 106.8456)
OPENMETEO_VARIABLES = _str(
    "OPENMETEO_VARIABLES",
    "temperature_2m,relative_humidity_2m,wind_speed_10m",
)

# CATA/PELABELAN metrik yang tidak bisa memiliki nilai <= 0 (untuk delta %)
# Metrik yang bisa bernilai 0/negatif (mis. suhu) memakai formula delta lain.
FLOAT_ZERO_BASED = {"temperature_2m"}

HTTP_TIMEOUT = _float("HTTP_TIMEOUT", 20.0)

# ---------------------------------------------------------------------------
# LLM summarizer
# ---------------------------------------------------------------------------
# Pilihan provider: "mock" | "ollama" | "openai"
LLM_PROVIDER = _str("LLM_PROVIDER", "mock")
LLM_ENABLED = _bool("LLM_ENABLED", True)

OLLAMA_URL = _str("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = _str("OLLAMA_MODEL", "llama3.2")

OPENAI_API_KEY = _str("OPENAI_API_KEY", "")
OPENAI_MODEL = _str("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = _str(
    "OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"
)

# ---------------------------------------------------------------------------
# WebSocket & server
# ---------------------------------------------------------------------------
WS_PATH = _str("WS_PATH", "/api/ws/live")
HOST = _str("HOST", "0.0.0.0")
PORT = _int("PORT", 8000)
LOG_LEVEL = _str("LOG_LEVEL", "info")


def summary() -> dict:
    """Ringkasan konfigurasi aktif (untuk log/status)."""
    return {
        "data_source": DATA_SOURCE,
        "update_interval_s": UPDATE_INTERVAL,
        "significant_pct": SIGNIFICANT_PCT,
        "window_hours": WINDOW_HOURS,
        "llm_provider": LLM_PROVIDER,
        "database": DATABASE_URL,
    }
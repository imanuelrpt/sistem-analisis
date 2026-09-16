"""Service untuk menarik data dari public API eksternal.

Sumber yang didukung (gratis, tanpa API key):
  - CoinGecko  : harga kripto (bitcoin, ethereum, dll)  -> coingecko
  - Open-Meteo : cuaca real-time (suhu, angin, dsb.)    -> openmeteo

Output fetch_latest() berupa list dict:
    [{"metric": "btc/usd", "value": 61000.5, "extra": {...}}, ...]

metrik normal bernilai-perubahan: "btc/usd" -> delta % aman.
Untuk metrik weather (bisa 0/negatif) gunakan delta absolut.
"""

import logging

import httpx

from .. import config

logger = logging.getLogger("realtime_insight.fetcher")


class FetcherError(RuntimeError):
    """Gagal mengambil atau mem-parsing data dari sumber eksternal."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _fetch_coingecko() -> list[dict]:
    ids = config.COINGECKO_IDS
    vs = config.COINGECKO_VS_CURRENCIES
    url = (
        f"{config.COINGECKO_URL}?ids={ids}&vs_currencies={vs}"
        "&include_24hr_change=true&include_last_updated_at=true"
    )

    with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, dict) or not data:
        raise FetcherError("CoinGecko mengembalikan payload kosong/aneh.")

    result: list[dict] = []
    for coin, info in data.items():
        price = (info or {}).get(vs)
        if price is None:
            continue
        # deck cegah nilai non-numerik / null
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue

        result.append(
            {
                "metric": f"{coin}/{vs}",
                "value": value,
                "extra": {
                    "change_24h_pct": info.get(f"{vs}_24h_change"),
                    "name": coin,
                },
            }
        )

    if not result:
        raise FetcherError("CoinGecko: tidak ada harga valid yang dapat diambil.")
    return result


def _fetch_openmeteo() -> list[dict]:
    variables = [v.strip() for v in config.OPENMETEO_VARIABLES.split(",") if v.strip()]
    if not variables:
        raise FetcherError("Open-Meteo: OPENMETEO_VARIABLES kosong.")

    params = {
        "latitude": config.OPENMETEO_LAT,
        "longitude": config.OPENMETEO_LON,
        "current": ",".join(variables),
        "timezone": "auto",
    }
    url = f"{config.OPENMETEO_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    current = data.get("current") or {}
    units = data.get("current_units") or {}
    if not current:
        raise FetcherError("Open-Meteo: field current tidak ditemukan.")

    result: list[dict] = []
    for var in variables:
        value = current.get(var)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        result.append(
            {
                "metric": var,
                "value": value,
                "extra": {
                    "unit": units.get(var),
                    "place": f"{config.OPENMETEO_LAT},{config.OPENMETEO_LON}",
                },
            }
        )

    if not result:
        raise FetcherError("Open-Meteo: tidak ada variabel valid yang dapat diambil.")
    return result


_FETCHERS = {
    "coingecko": _fetch_coingecko,
    "openmeteo": _fetch_openmeteo,
}


async def fetch_latest() -> list[dict]:
    """Ambil data terbaru dari sumber yang dikonfigurasi (async wrapper)."""
    fn = _FETCHERS.get(config.DATA_SOURCE)
    if fn is None:
        raise FetcherError(f"Sumber data tidak dikenal: {config.DATA_SOURCE}")
    logger.info("Mengambil data dari sumber %s ...", config.DATA_SOURCE)
    try:
        points = await _run_async(fn)
    except httpx.HTTPStatusError as exc:
        raise FetcherError(
            f"HTTP {exc.response.status_code} dari {exc.request.url}"
        ) from exc
    except httpx.RequestError as exc:
        raise FetcherError(f"Gagal koneksi ke API eksternal: {exc}") from exc
    logger.info("Berhasil mengambil %s titik data.", len(points))
    return points


async def _run_async(fn):
    # Jalan pintas: sinkron sudah ok untuk polling singkat; jalankan langsung.
    import asyncio

    return await asyncio.to_thread(fn)
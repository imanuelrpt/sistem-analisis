"""Unit test untuk fetcher (polling dari public API eksternal).

Sumber HTTP dimock dengan FakeClient supaya test tidak menyentuh jaringan.
"""

import asyncio

import httpx
import pytest

from app import config
from app.services import fetcher
from app.services.fetcher import FetcherError


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.request = httpx.Request("GET", "http://fake.test")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class FakeClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        # catat URL untuk asersi
        self.last_url = url
        return self._response


def test_coingecko_parses_valid_coins(monkeypatch):
    payload = {
        "bitcoin": {"usd": 61000.5},
        "ethereum": {"usd": 3000.0},
        "binancecoin": {"usd": 700.0},
    }
    monkeypatch.setattr(config, "DATA_SOURCE", "coingecko")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse(payload)))

    points = asyncio.run(fetcher.fetch_latest())
    assert len(points) == 3
    assert points[0]["metric"] == "bitcoin/usd"
    assert points[0]["value"] == 61000.5
    assert "source" not in points[0]


def test_coingecko_skips_invalid_numeric(monkeypatch):
    payload = {
        "bitcoin": {"usd": "not-a-number"},
        "ethereum": {"usd": 3000.0},
    }
    monkeypatch.setattr(config, "DATA_SOURCE", "coingecko")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse(payload)))

    points = asyncio.run(fetcher.fetch_latest())
    assert len(points) == 1
    assert points[0]["metric"] == "ethereum/usd"


def test_coingecko_empty_payload_raises(monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "coingecko")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse({})))

    with pytest.raises(FetcherError):
        asyncio.run(fetcher.fetch_latest())


def test_openmeteo_parses_variables(monkeypatch):
    payload = {
        "current": {"temperature_2m": 31.2, "relative_humidity_2m": 78.0},
        "current_units": {"temperature_2m": "°C", "relative_humidity_2m": "%"},
    }
    monkeypatch.setattr(config, "DATA_SOURCE", "openmeteo")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse(payload)))

    points = asyncio.run(fetcher.fetch_latest())
    metrics = {p["metric"] for p in points}
    assert metrics == {"temperature_2m", "relative_humidity_2m"}
    assert points[0]["extra"]["unit"] == "°C"


def test_openmeteo_missing_current_raises(monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "openmeteo")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse({"foo": 1})))

    with pytest.raises(FetcherError):
        asyncio.run(fetcher.fetch_latest())


def test_unknown_source_raises(monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "bogus")
    with pytest.raises(FetcherError):
        asyncio.run(fetcher.fetch_latest())


def test_http_error_raises_fetcher_error(monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "coingecko")
    monkeypatch.setattr(fetcher.httpx, "Client", lambda **kw: FakeClient(FakeResponse({}, status=500)))

    with pytest.raises(FetcherError, match="HTTP 500"):
        asyncio.run(fetcher.fetch_latest())
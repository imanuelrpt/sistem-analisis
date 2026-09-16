"""Konfigurasi pytest untuk seluruh suite.

Env vars berikut WAJIB diset SEBELUM modul `app.*` di-import supaya config
membaca database khusus test (bukan insight.db produksi) dan tidak memanggil
LLM eksternal / jaringan saat startup awal.
"""

import os
import tempfile

_TEST_DB = os.path.join(tempfile.gettempdir(), "realtime_insight_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["LLM_ENABLED"] = "false"
os.environ["DATA_SOURCE"] = "none"  # startup pipeline gagal cepat, tanpa jaringan

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """TestClient FastAPI — lifespan (init DB + scheduler) ikut berjalan."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db():
    yield
    for suffix in ("", "-shm", "-wal"):
        path = _TEST_DB + suffix
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
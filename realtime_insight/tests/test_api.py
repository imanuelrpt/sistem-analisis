"""Smoke test API — memastikan endpoint utama merespons dengan benar."""

from app.main import app


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "source" in body
    assert body["config"]["update_interval_s"] > 0


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text
    assert "Realtime Insight" in resp.text


def test_static_css_available(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert ":root" in resp.text


def test_data_endpoint_shape(client):
    resp = client.get("/api/data")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("timestamp", "sources", "trends", "insights", "conclusion", "cycle"):
        assert key in body


def test_reports_endpoints(client):
    insights = client.get("/api/reports/insights")
    assert insights.status_code == 200
    assert isinstance(insights.json(), list)

    conclusions = client.get("/api/reports/conclusions")
    assert conclusions.status_code == 200
    assert isinstance(conclusions.json(), list)

    stats = client.get("/api/reports/stats")
    assert stats.status_code == 200
    assert isinstance(stats.json(), list)


def test_raw_data_endpoint(client):
    resp = client.get("/api/data/raw")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_openapi_documentation(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/data" in resp.json()["paths"]
"""POST /api/client-perf accepts soft-nav timing payloads."""

from fastapi.testclient import TestClient

from app.main import app


def test_client_perf_endpoint_ok():
    client = TestClient(app, base_url="https://testserver")
    r = client.post(
        "/api/client-perf",
        json={
            "url": "/team",
            "fetch_ms": 320.5,
            "scripts_ms": 890.1,
            "total_ms": 1210.6,
            "from_cache": False,
        },
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_client_perf_endpoint_defaults():
    client = TestClient(app, base_url="https://testserver")
    r = client.post("/api/client-perf", json={})
    assert r.status_code == 200
    assert r.json().get("ok") is True

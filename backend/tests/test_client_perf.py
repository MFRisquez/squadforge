"""POST/GET /api/client-perf soft-nav timing buffer."""

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
            "server_perf": {
                "server_ms": 900,
                "spans": [{"name": "ctx.current_manager", "ms": 12}],
            },
        },
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_client_perf_endpoint_defaults():
    client = TestClient(app, base_url="https://testserver")
    r = client.post("/api/client-perf", json={})
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_client_perf_get_returns_ring_buffer():
    client = TestClient(app, base_url="https://testserver")
    client.post(
        "/api/client-perf",
        json={
            "url": "/rules",
            "fetch_ms": 100,
            "scripts_ms": 50,
            "total_ms": 150,
            "from_cache": True,
        },
    )
    r = client.get("/api/client-perf?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("count", 0) >= 1
    assert any(e.get("url") == "/rules" for e in data.get("events", []))

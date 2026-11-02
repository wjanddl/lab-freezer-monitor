from fastapi.testclient import TestClient

from app.db import influx
from app.main import app


def test_health_reports_influx_state(monkeypatch):
    c = TestClient(app)
    for up in (True, False):
        async def fake():
            return up
        monkeypatch.setattr(influx, "ping", fake)
        body = c.get("/health").json()
        assert body["influx"] is up
        assert body["status"] == ("ok" if up else "degraded")

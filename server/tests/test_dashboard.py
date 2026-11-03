"""대시보드 조회 API: 인증, 빈 데이터(가짜 값 없음), 경보 상태, 시계열, 이력/확인, Influx CSV 해석."""
import asyncio
import json
import time
from contextlib import closing
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import influx, sqlite
from app.main import app
from app.services import auth, devices

PW = "long-enough-pw"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("JWT_SECRET", "t" * 40)
    get_settings.cache_clear()
    auth.create_user("oled", PW, "viewer")
    devices.create_device("freezer-01")
    latest = {}

    async def fake_latest(_):
        return latest

    monkeypatch.setattr(influx, "latest", fake_latest)
    client = TestClient(app)
    tok = client.post("/api/v1/auth/login", json={"username": "oled", "password": PW}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {tok}"
    client.latest = latest
    yield client
    get_settings.cache_clear()


def test_requires_auth(c):
    assert TestClient(app).get("/api/v1/status").status_code == 401


def test_no_data_returns_nulls(c):
    r = c.get("/api/v1/status")
    assert r.status_code == 200  # viewer 허용
    (d,) = r.json()["devices"]
    assert d == {"device_id": "freezer-01", "last_seen": None, "online": False,
                 "reading": None, "alarm_level": "OK", "alarms": []}


def test_reading_and_alarm(c):
    now = int(time.time())
    c.latest["freezer-01"] = {"ts": now, "temp_c": -65.0, "door_open": False, "sensor_fault": 0}
    with closing(sqlite.connect()) as db, db:
        db.execute("INSERT INTO device_status VALUES (?,?)", ("freezer-01", now))
        db.execute("INSERT INTO alert_state VALUES (?,?,?)",
                   ("freezer-01", "temp", json.dumps({"level": 1, "started_at": now - 60})))
    d = c.get("/api/v1/status").json()["devices"][0]
    assert d["online"] and d["reading"]["temp_c"] == -65.0
    assert d["alarm_level"] == "WARNING" and d["alarms"] == [{"kind": "temp", "level": "WARNING", "since": now - 60}]


def test_influx_down_503(c, monkeypatch):
    async def boom(_):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(influx, "latest", boom)
    assert c.get("/api/v1/status").status_code == 503


def test_latest_parses_csv_and_drops_stale_temp(monkeypatch):
    # temp_c 마지막 값은 옛 시각(센서 오류로 이후 미기록) → 최신 시점엔 None 이어야 함
    csv_text = (
        ",result,table,_time,_value,_field,device_id\r\n"
        ",_result,0,2026-11-03T10:00:00Z,-79.5,temp_c,freezer-01\r\n"
        "\r\n"
        ",result,table,_time,_value,_field,device_id\r\n"
        ",_result,1,2026-11-03T10:05:00Z,true,door_open,freezer-01\r\n"
        ",_result,2,2026-11-03T10:05:00Z,3,sensor_fault,freezer-01\r\n"
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(influx.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=csv_text))))
    get_settings.cache_clear()
    out = asyncio.run(influx.latest(3600))
    ts = int(datetime(2026, 11, 3, 10, 5, tzinfo=timezone.utc).timestamp())
    assert out == {"freezer-01": {"ts": ts,"temp_c": None, "door_open": True, "sensor_fault": 3}}


def test_devices(c):
    (d,) = c.get("/api/v1/devices").json()["devices"]
    assert d["device_id"] == "freezer-01" and d["created_at"] > 0 and d["online"] is False


def test_readings_downsamples_and_validates(c, monkeypatch):
    calls = []

    async def fake_series(dev, start, stop, every):
        calls.append((dev, start, stop, every))
        return [{"ts": start, "temp_c": -79.9, "door_open": False}]

    monkeypatch.setattr(influx, "series", fake_series)
    r = c.get("/api/v1/readings", params={"device_id": "freezer-01", "from": 0, "to": 86400})
    assert r.status_code == 200 and r.json()["interval_s"] == 173  # ceil(86400/500)
    assert r.json()["points"] == [{"ts": 0, "temp_c": -79.9, "door_open": False}]
    assert calls == [("freezer-01", 0, 86400, 173)]
    assert c.get("/api/v1/readings", params={"device_id": "freezer-01", "from": 10, "to": 10}).status_code == 422
    # Flux 문자열 주입 차단
    assert c.get("/api/v1/readings", params={"device_id": 'x") |> drop('}).status_code == 422


def _add_event(dev="freezer-01", started=100, resolved=None):
    with closing(sqlite.connect()) as db, db:
        return db.execute(
            "INSERT INTO events (device_id, type, severity, started_at, resolved_at) VALUES (?,?,?,?,?)",
            (dev, "temp", "WARNING", started, resolved),
        ).lastrowid


def test_events_filter_and_ack(c):
    old = _add_event(started=100, resolved=200)
    cur = _add_event(started=300)
    ids = lambda **p: [e["id"] for e in c.get("/api/v1/events", params=p).json()["events"]]
    assert ids() == [cur, old]  # 최근 시작 순
    assert ids(active="true") == [cur] and ids(active="false") == [old]
    assert ids(**{"from": 200}) == [cur] and ids(device_id="other") == []

    r = c.post(f"/api/v1/events/{cur}/ack")
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "oled"  # viewer도 가능
    first = r.json()["acknowledged_at"]
    auth.create_user("kim", PW, "admin")
    tok = c.post("/api/v1/auth/login", json={"username": "kim", "password": PW}).json()["access_token"]
    r2 = c.post(f"/api/v1/events/{cur}/ack", headers={"Authorization": f"Bearer {tok}"})
    assert r2.json()["acknowledged_by"] == "oled" and r2.json()["acknowledged_at"] == first  # 처음 확인 유지
    assert c.post("/api/v1/events/9999/ack").status_code == 404


def test_all_read_endpoints_require_auth(c):
    anon = TestClient(app)
    for path in ("/api/v1/devices", "/api/v1/events", "/api/v1/readings?device_id=freezer-01"):
        assert anon.get(path).status_code == 401
    assert anon.post("/api/v1/events/1/ack").status_code == 401

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import influx
from app.main import app
from app.services import devices


@pytest.fixture
def written(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    lines = []

    async def fake_write(l):
        lines.extend(l)

    monkeypatch.setattr(influx, "write", fake_write)
    yield lines
    get_settings.cache_clear()


@pytest.fixture
def client(written):
    c = TestClient(app)
    c.headers["X-API-Key"] = devices.create_device("freezer-01")
    return c


def body(**kw):
    return {"device_id": "freezer-01", "ts": int(time.time()), "temp_c": -79.84, "door_open": False, **kw}


def test_ok_single(client, written):
    r = client.post("/api/v1/readings", json=body(seq=1, rssi=-61, uptime_s=10))
    assert r.status_code == 200 and r.json()["ok"] and r.json()["server_time"] > 0
    assert len(written) == 1
    assert "temp_c=-79.84" in written[0] and "door_open=false" in written[0]
    assert "sensor_fault=0i" in written[0] and "rssi=-61i" in written[0]


def test_auth_failures(client, written):
    assert client.post("/api/v1/readings", json=body(), headers={"X-API-Key": "bad"}).status_code == 401
    c2 = TestClient(app)  # 헤더 없음
    assert c2.post("/api/v1/readings", json=body()).status_code == 401
    assert written == []


def test_device_id_must_match_key(client, written):
    assert client.post("/api/v1/readings", json=body(device_id="other")).status_code == 403
    assert written == []


@pytest.mark.parametrize("bad", [{"sensor_fault": 256}, {"device_id": "a b"}, {"door_open": "maybe"}, {"ts": -1}])
def test_invalid_values_422(client, bad):
    assert client.post("/api/v1/readings", json=body(**bad)).status_code == 422


def test_missing_door_open_422(client):
    b = body()
    del b["door_open"]
    assert client.post("/api/v1/readings", json=b).status_code == 422


def test_temp_out_of_range_saved_as_fault(client, written):
    assert client.post("/api/v1/readings", json=body(temp_c=500, sensor_fault=2)).status_code == 200
    assert "temp_c" not in written[0] and "sensor_fault=258i" in written[0]  # 2 | 0x100


def test_null_temp_ok(client, written):
    assert client.post("/api/v1/readings", json=body(temp_c=None, sensor_fault=4)).status_code == 200
    assert "temp_c" not in written[0] and "sensor_fault=4i" in written[0]


def test_batch_sorted_and_deduped(client, written):
    t = int(time.time()) - 600
    batch = [body(ts=t + 20), body(ts=t), body(ts=t + 10), body(ts=t + 10, temp_c=-70.0)]
    assert client.post("/api/v1/readings", json=batch).status_code == 200
    stamps = [int(l.rsplit(" ", 1)[1]) for l in written]
    assert stamps == [t, t + 10, t + 20]
    assert "temp_c=-70.0" in written[1]  # 같은 ts는 마지막 값


def test_empty_and_oversized_batch_422(client):
    assert client.post("/api/v1/readings", json=[]).status_code == 422
    assert client.post("/api/v1/readings", json=[body()] * 501).status_code == 422


def test_bad_ts_replaced_by_server_time(client, written):
    now = int(time.time())
    b = body(ts=now + 86400)  # 하루 뒤: 시계 오류
    b2 = body()
    del b2["ts"]
    for x in (b, b2):
        written.clear()
        assert client.post("/api/v1/readings", json=x).status_code == 200
        assert abs(int(written[0].rsplit(" ", 1)[1]) - now) <= 2


def test_storage_down_returns_503(client, monkeypatch):
    async def boom(_):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(influx, "write", boom)
    assert client.post("/api/v1/readings", json=body()).status_code == 503


def test_time_endpoint(client):
    assert abs(client.get("/api/v1/time", headers={}).json()["server_time"] - time.time()) < 2

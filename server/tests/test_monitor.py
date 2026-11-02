"""monitor 통합 테스트 (SQLite 실제 사용, 알림은 fake)."""
import asyncio
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import sqlite
from app.main import app
from app.services import auth, devices, monitor, notify
from app.services.ingest import Point

T0 = 1_000_000


@pytest.fixture
def sent(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("JWT_SECRET", "t" * 40)
    get_settings.cache_clear()
    out = []

    async def fake(text):
        out.append(text)
        return True

    monkeypatch.setattr(notify, "send", fake)
    yield out
    get_settings.cache_clear()


def P(ts, temp=-80.0, door=False, fault=0):
    return Point("freezer-01", ts, temp, door, fault, None, None)


def run(points, now):
    asyncio.run(monitor.process(points, now))


def events():
    with closing(sqlite.connect()) as db:
        return db.execute("SELECT type, severity, started_at, resolved_at, peak_value FROM events ORDER BY id").fetchall()


def test_live_alert_then_recovery_persisted_across_calls(sent):
    for i in range(61):  # 10분간 -65℃ (호출마다 SQLite에서 상태 복원 = 재시작과 동일)
        run([P(T0 + i * 10, -65.0)], T0 + i * 10)
    assert events() == [("temp", "WARNING", T0, None, -65.0)]
    assert len(sent) == 1 and "WARNING" in sent[0]
    run([P(T0 + 700, -80.0)], T0 + 700)
    assert events()[0][3] == T0 + 700 and len(sent) == 2 and "복구" in sent[1]


def test_backfill_batch_records_history_without_alerts(sent):
    batch = [P(T0 + i * 10, -65.0) for i in range(61)] + [P(T0 + 700, -80.0)]
    run(batch, T0 + 100_000)  # 한참 뒤 재전송
    assert events() == [("temp", "WARNING", T0, T0 + 700, -65.0)]
    assert sent == []


def test_backfill_still_alerting_gets_notified_on_tick(sent):
    devices.create_device("freezer-01")
    batch = [P(T0 + i * 10, -65.0) for i in range(61)]
    run(batch, T0 + 5000)
    assert sent == []
    asyncio.run(monitor.tick(T0 + 5000, started_at=T0 - 10_000))
    assert len(sent) == 1  # 아직 진행 중인 알림을 뒤늦게라도 전달


def test_offline_via_tick_with_grace_and_recovery(sent):
    devices.create_device("freezer-01")
    run([P(T0)], T0)
    asyncio.run(monitor.tick(T0 + 100, started_at=T0 - 1000))
    assert events() == []
    asyncio.run(monitor.tick(T0 + 200, started_at=T0 + 100))  # 시작 유예 중
    assert events() == []
    asyncio.run(monitor.tick(T0 + 200, started_at=T0 - 1000))
    assert events() == [("offline", "CRITICAL", T0, None, None)] and len(sent) == 1
    asyncio.run(monitor.tick(T0 + 200 + 1800, started_at=T0 - 1000))  # CRITICAL 재알림 30분
    assert len(sent) == 2
    run([P(T0 + 3000)], T0 + 3000)
    assert events()[0][3] == T0 + 3000 and "복구" in sent[-1]


def test_sensor_fault_alert(sent):
    for i in range(3):
        run([P(T0 + i * 10, temp=None, fault=4)], T0 + i * 10)
    assert events()[0][:2] == ("sensor", "CRITICAL") and len(sent) == 1


def test_never_seen_registered_device_goes_offline(sent):
    devices.create_device("freezer-01")  # 등록만 하고 한 번도 데이터가 없음
    now = 4_000_000_000  # created_at(현재)보다 한참 뒤
    asyncio.run(monitor.tick(now, started_at=now - 1000))
    assert events()[0][:2] == ("offline", "CRITICAL")


def test_settings_api(sent):
    c = TestClient(app)
    auth.create_user("boss", "long-enough-pw", "admin")
    auth.create_user("view", "long-enough-pw", "viewer")
    assert c.get("/api/v1/settings").status_code == 401
    assert c.get("/api/v1/settings", headers={"Authorization": "Bearer x"}).status_code == 401
    t = auth.login("view", "long-enough-pw", "ip")["access_token"]
    assert c.get("/api/v1/settings", headers={"Authorization": f"Bearer {t}"}).status_code == 403  # viewer
    h = {"Authorization": "Bearer " + auth.login("boss", "long-enough-pw", "ip")["access_token"]}
    assert c.get("/api/v1/settings", headers=h).json()["temp_warn_c"] == -70
    r = c.put("/api/v1/settings", json={"temp_warn_c": -68}, headers=h)
    assert r.status_code == 200 and r.json()["temp_warn_c"] == -68 and r.json()["temp_crit_c"] == -60
    assert c.get("/api/v1/settings", headers=h).json()["temp_warn_c"] == -68  # 영속화
    assert c.put("/api/v1/settings", json={"temp_warn_c": -50}, headers=h).status_code == 422  # crit(-60)보다 높음
    assert c.put("/api/v1/settings", json={"bogus": 1}, headers=h).status_code == 422

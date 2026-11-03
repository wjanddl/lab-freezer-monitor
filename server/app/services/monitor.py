"""엔진(engine)과 I/O(SQLite, 알림)를 잇는 계층. 상태는 매번 SQLite에서 읽고 쓰므로 재시작에 안전하다.

# ponytail: 동기 sqlite3를 async 함수 안에서 쓰고 전역 Lock으로 직렬화. 장치 수십 대/10초 주기까지는 충분.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import influx, sqlite
from app.models.alert_settings import AlertSettings
from app.services import alert_settings, engine, heartbeat, notify
from app.services.engine import State
from app.services.ingest import Point

log = logging.getLogger(__name__)
_lock = asyncio.Lock()
KST = ZoneInfo("Asia/Seoul")  # 저장은 UTC, 표시만 KST

KINDS = ("temp", "door", "sensor", "offline")
SEVERITY = {engine.WARNING: "WARNING", engine.CRITICAL: "CRITICAL"}
LABEL = {"temp": "온도", "door": "문 열림", "sensor": "센서 장애", "offline": "장치 무응답"}


def _text(dev: str, kind: str, a: engine.Action) -> str:
    # 이력(events.message)용 짧은 문구. 발송 시 KST 시각/대시보드 링크는 _apply·notify에서 덧붙인다
    value = ""
    if a.value is not None:
        value = f" {a.value:.1f}℃" if kind == "temp" else f" {a.value:.0f}분" if kind == "door" else ""
    head = {"resolve": "복구됨", "remind": f"[{SEVERITY[a.level]}] 지속 중"}.get(a.op, f"[{SEVERITY[a.level]}]")
    return f"{head} {dev} {LABEL[kind]}{value}"


def _load(db, dev: str, kind: str) -> State:
    row = db.execute("SELECT json FROM alert_state WHERE device_id=? AND kind=?", (dev, kind)).fetchone()
    return State(**json.loads(row[0])) if row else State()


def _save(db, dev: str, kind: str, st: State) -> None:
    db.execute("INSERT OR REPLACE INTO alert_state VALUES (?,?,?)", (dev, kind, json.dumps(asdict(st))))


async def _apply(db, dev: str, kind: str, st: State, actions: list[engine.Action], now: float) -> None:
    for a in actions:
        text = _text(dev, kind, a)
        if a.op == "start":
            cur = db.execute(
                "INSERT INTO events (device_id, type, severity, started_at, peak_value, message) VALUES (?,?,?,?,?,?)",
                (dev, kind, SEVERITY[a.level], int(a.started_at), a.value, text),
            )
            st.event_id = cur.lastrowid
        elif a.op == "escalate":
            db.execute("UPDATE events SET severity=?, message=? WHERE id=?", (SEVERITY[a.level], text, a.event_id))
        elif a.op == "resolve":
            db.execute("UPDATE events SET resolved_at=?, peak_value=? WHERE id=?", (int(a.ts), a.value, a.event_id))
        # 발송 실패 시 notified_*를 갱신하지 않아 다음 틱에서 재시도된다
        kst = datetime.fromtimestamp(a.ts, KST).strftime("%Y-%m-%d %H:%M:%S KST")
        if a.notify and await notify.send(f"{text}\n{kst}") and a.op != "resolve":
            st.notified_at, st.notified_level = now, a.level
    if st.event_id and st.level and st.peak is not None:
        db.execute("UPDATE events SET peak_value=? WHERE id=? AND peak_value IS NOT ?", (st.peak, st.event_id, st.peak))


def _is_bad(p: Point, c: AlertSettings) -> bool:
    return p.sensor_fault != 0 or p.temp_c is None or not c.sensor_min_c <= p.temp_c <= c.sensor_max_c


async def process(points: list[Point], now: float) -> None:
    """저장 성공한 측정값을 판정에 반영 (ts 오름차순). 호출자는 예외를 삼켜 수신 응답에 영향 주지 않는다."""
    async with _lock:
        with closing(sqlite.connect()) as db:
            c = alert_settings.load(db)
            by_dev = defaultdict(list)
            for p in points:
                by_dev[p.device_id].append(p)
            for dev, pts in by_dev.items():
                # 수신 자체가 무응답 해제 신호 (측정값 ts와 무관하게 서버 시각 기준)
                db.execute("INSERT OR REPLACE INTO device_status VALUES (?,?)", (dev, now))
                off = _load(db, dev, "offline")
                await _apply(db, dev, "offline", off, engine.step_offline(off, now, now, False, c), now)
                _save(db, dev, "offline", off)

                sts = {k: _load(db, dev, k) for k in ("temp", "door", "sensor")}
                for p in pts:
                    live = now - p.ts <= c.backfill_after_s
                    bad = _is_bad(p, c)
                    steps = {
                        "door": engine.step_door(sts["door"], p.ts, p.door_open, live, c),
                        "sensor": engine.step_sensor(sts["sensor"], p.ts, bad, live, c),
                    }
                    if not bad:
                        steps["temp"] = engine.step_temp(sts["temp"], p.ts, p.temp_c, live, c)
                    for k, acts in steps.items():
                        await _apply(db, dev, k, sts[k], acts, now)
                for k, st in sts.items():
                    _save(db, dev, k, st)
            db.commit()


async def tick(now: float, started_at: float) -> int:
    """주기 작업: 무응답 판정, 미발송 알림 전달, 재알림. 다음 틱까지 대기할 초를 반환."""
    async with _lock:
        with closing(sqlite.connect()) as db:
            c = alert_settings.load(db)
            grace = now - started_at < c.startup_grace_s
            rows = db.execute(
                "SELECT d.device_id, COALESCE(s.last_seen, CAST(strftime('%s', d.created_at) AS REAL)) "
                "FROM devices d LEFT JOIN device_status s USING (device_id)"
            ).fetchall()
            for dev, last_seen in rows:
                for kind in KINDS:
                    st = _load(db, dev, kind)
                    acts = engine.step_offline(st, now, last_seen, grace, c) if kind == "offline" else []
                    # 방금 발송 시도한 알림을 같은 틱에서 다시 시도하지 않도록 acts가 없을 때만 확인
                    acts = acts or engine.step_notice(st, now, c)
                    await _apply(db, dev, kind, st, acts, now)
                    _save(db, dev, kind, st)
            db.commit()
            return c.tick_interval_s


async def run_forever() -> None:
    started_at = time.time()
    last_beat = 0.0
    while True:
        interval, ok = 30, False
        try:
            interval = await tick(time.time(), started_at)
            ok = await influx.ping()
        except Exception:
            log.exception("monitor tick failed")
        if time.time() - last_beat >= get_settings().heartbeat_interval_s:
            # 틱 성공 + Influx 정상일 때만 성공 ping, 아니면 /fail (healthchecks.io가 알림)
            await heartbeat.ping(ok)
            last_beat = time.time()
        await asyncio.sleep(interval)

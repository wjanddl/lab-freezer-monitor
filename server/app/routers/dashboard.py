"""대시보드(프론트)/OLED용 조회 API. 모두 로그인 필요(viewer/admin). 시각은 전부 epoch 초 UTC."""
import json
import math
import time
from contextlib import closing
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import get_settings
from app.db import influx, sqlite
from app.services import alert_settings
from app.services.auth import User, current_user
from app.services.monitor import SEVERITY

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])
DEVICE_ID = r"^[A-Za-z0-9_-]{1,64}$"  # Reading.device_id와 동일 (Flux 문자열에 들어가므로 필수 검증)


def _devices(db, offline_after_s: float, now: int) -> list[dict]:
    rows = db.execute(
        "SELECT d.device_id, d.created_at, s.last_seen FROM devices d LEFT JOIN device_status s USING (device_id) "
        "ORDER BY 1"
    ).fetchall()
    out = []
    for dev, created, last_seen in rows:
        # SQLite CURRENT_TIMESTAMP는 UTC 'YYYY-MM-DD HH:MM:SS'
        created_ts = int(datetime.fromisoformat(created).replace(tzinfo=timezone.utc).timestamp())
        out.append({
            "device_id": dev,
            "created_at": created_ts,
            "last_seen": last_seen and int(last_seen),
            "online": last_seen is not None and now - last_seen <= offline_after_s,
        })
    return out


@router.get("/devices")
def devices():
    now = int(time.time())
    with closing(sqlite.connect()) as db:
        c = alert_settings.load(db)
        return {"server_time": now, "devices": _devices(db, c.offline_after_min * 60, now)}


@router.get("/status")
async def status():
    """등록된 장치별 최신 측정값 + 엔진의 현재 경보 상태.

    값이 없으면 reading=null (가짜 값을 만들지 않음). online은 last_seen이 무응답 기준 이내인지.
    """
    now = int(time.time())
    with closing(sqlite.connect()) as db:
        c = alert_settings.load(db)
        devs = _devices(db, c.offline_after_min * 60, now)
        states = db.execute("SELECT device_id, kind, json FROM alert_state").fetchall()
    try:
        latest = await influx.latest(get_settings().status_lookback_s)
    except httpx.HTTPError:
        raise HTTPException(503, "storage unavailable")

    alarms = {}
    for dev, kind, js in states:
        st = json.loads(js)
        if st["level"]:
            alarms.setdefault(dev, []).append(
                {"kind": kind, "level": SEVERITY[st["level"]], "since": st["started_at"] and int(st["started_at"])}
            )
    for d in devs:
        a = alarms.get(d["device_id"], [])
        d["reading"] = latest.get(d["device_id"])
        d["alarm_level"] = "CRITICAL" if any(x["level"] == "CRITICAL" for x in a) else "WARNING" if a else "OK"
        d["alarms"] = a
        del d["created_at"]
    return {"server_time": now, "devices": devs}


@router.get("/readings")
async def readings(
    device_id: str = Query(pattern=DEVICE_ID),
    start: int | None = Query(None, alias="from", ge=0),
    stop: int | None = Query(None, alias="to", ge=0),
):
    """그래프용 시계열. 기본 최근 24시간. 점이 max_points를 넘지 않도록 자동으로 창 평균."""
    s = get_settings()
    stop = stop or int(time.time())
    start = stop - 86400 if start is None else start
    if not start < stop:
        raise HTTPException(422, "from < to 이어야 함")
    if stop - start > s.readings_max_range_s:
        raise HTTPException(422, f"기간은 최대 {s.readings_max_range_s}초")
    every = max(1, math.ceil((stop - start) / s.readings_max_points))
    try:
        pts = await influx.series(device_id, start, stop, every)
    except httpx.HTTPError:
        raise HTTPException(503, "storage unavailable")
    return {"device_id": device_id, "from": start, "to": stop, "interval_s": every, "points": pts}


EVENT_COLS = ("id", "device_id", "type", "severity", "started_at", "resolved_at", "peak_value", "message",
              "acknowledged_by", "acknowledged_at")


def _event(row) -> dict:
    return dict(zip(EVENT_COLS, row))


@router.get("/events")
def events(
    device_id: str | None = Query(None, pattern=DEVICE_ID),
    start: int | None = Query(None, alias="from", ge=0),
    stop: int | None = Query(None, alias="to", ge=0),
    active: bool | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    """이상 이력 (최근 시작 순). from/to는 started_at 기준. active=true면 미해제만, false면 해제된 것만."""
    where, args = [], []
    if device_id:
        where.append("device_id=?"); args.append(device_id)
    if start is not None:
        where.append("started_at>=?"); args.append(start)
    if stop is not None:
        where.append("started_at<?"); args.append(stop)
    if active is not None:
        where.append("resolved_at IS NULL" if active else "resolved_at IS NOT NULL")
    sql = f"SELECT {','.join(EVENT_COLS)} FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with closing(sqlite.connect()) as db:
        rows = db.execute(sql + " ORDER BY started_at DESC, id DESC LIMIT ?", (*args, limit)).fetchall()
    return {"events": [_event(r) for r in rows]}


@router.post("/events/{event_id}/ack")
def ack(event_id: int, user: User = Depends(current_user)):
    """이상 확인 처리 (viewer/admin). 이미 확인된 건은 처음 확인한 사람/시각을 유지."""
    with closing(sqlite.connect()) as db, db:
        db.execute(
            "UPDATE events SET acknowledged_by=?, acknowledged_at=? WHERE id=? AND acknowledged_by IS NULL",
            (user.username, int(time.time()), event_id),
        )
        row = db.execute(f"SELECT {','.join(EVENT_COLS)} FROM events WHERE id=?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, "event not found")
    return _event(row)

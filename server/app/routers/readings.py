import logging
import time

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException

from app.config import get_settings
from app.db import influx
from app.models.reading import MAX_BATCH, Reading
from app.services import ingest, monitor
from app.services.devices import device_auth

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.get("/time")
def server_time():
    """장치 부팅 직후 시각 확인용 (인증 불필요, 읽기 전용)."""
    return {"server_time": int(time.time())}


@router.post("/readings")
async def post_readings(
    body: Reading | list[Reading] = Body(...),
    device_id: str = Depends(device_auth),
):
    readings = body if isinstance(body, list) else [body]
    if not 1 <= len(readings) <= MAX_BATCH:
        raise HTTPException(422, f"batch size must be 1..{MAX_BATCH}")
    if any(r.device_id != device_id for r in readings):
        raise HTTPException(403, "device_id does not match api key")

    now = int(time.time())
    points = ingest.normalize(readings, now, get_settings())
    try:
        await influx.write([ingest.to_line(p) for p in points])
    except httpx.HTTPError:
        # 503이면 ESP32가 버퍼에 보관했다가 재전송한다 (데이터 유실 방지)
        raise HTTPException(503, "storage unavailable")
    try:
        await monitor.process(points, now)
    except Exception:
        # 판정 실패가 수신 응답(200)을 막으면 ESP32가 같은 데이터를 계속 재전송하므로 로그만 남긴다
        log.exception("monitor.process failed")
    return {"ok": True, "server_time": now}

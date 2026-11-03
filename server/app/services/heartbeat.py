"""healthchecks.io 생존신호. 서버/Pi가 죽으면 ping이 끊겨 healthchecks.io가 대신 알린다.

URL에 비밀 UUID가 들어 있으므로 로그에 URL/예외 메시지를 남기지 않는다.
"""
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
_transport: httpx.AsyncBaseTransport | None = None  # 테스트에서 MockTransport 주입용


async def ping(ok: bool) -> None:
    """ok면 성공 ping, 아니면 /fail. URL이 비어 있으면 아무것도 안 함. 실패해도 예외를 던지지 않는다."""
    s = get_settings()
    if not s.healthcheck_url:
        return
    url = s.healthcheck_url.rstrip("/") + ("" if ok else "/fail")
    try:
        async with httpx.AsyncClient(timeout=s.heartbeat_timeout_s, transport=_transport) as c:
            r = await c.get(url)
        if r.status_code != 200:
            log.warning("heartbeat 응답 status=%s", r.status_code)
    except httpx.HTTPError as e:
        log.warning("heartbeat 실패 %s", type(e).__name__)

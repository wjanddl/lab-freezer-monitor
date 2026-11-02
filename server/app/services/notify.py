"""텔레그램 알림 발송. 성공 시 True, 실패/미설정 시 False (monitor가 다음 틱에서 재시도)."""
import asyncio
import logging

import httpx

from app.config import get_settings

log = logging.getLogger("notify")

MAX_LEN = 4096  # 텔레그램 메시지 길이 제한
_transport: httpx.AsyncBaseTransport | None = None  # 테스트에서 MockTransport 주입용


async def send(text: str) -> bool:
    s = get_settings()
    log.warning("ALERT %s", text)  # 발송 여부와 무관하게 서버 로그에도 남김
    if not (s.telegram_bot_token and s.telegram_chat_id):
        log.error("텔레그램 미설정(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID): 발송 안 함")
        return False
    if s.dashboard_url:
        text += f"\n{s.dashboard_url}"
    body = {"chat_id": s.telegram_chat_id, "text": text[:MAX_LEN]}
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
    for attempt in range(1 + s.telegram_retries):
        if attempt:
            await asyncio.sleep(s.telegram_retry_delay_s)
        try:
            async with httpx.AsyncClient(timeout=s.telegram_timeout_s, transport=_transport) as c:
                r = await c.post(url, json=body)
            if r.status_code == 200:
                return True
            # 토큰이 URL에 있으므로 예외 객체/URL은 로그에 남기지 않고 상태코드만 기록
            log.error("텔레그램 발송 실패 status=%s (시도 %d)", r.status_code, attempt + 1)
            if r.status_code in (400, 401, 403, 404):
                return False  # 토큰/chat_id 오류는 재시도해도 소용없음
        except httpx.HTTPError as e:
            log.error("텔레그램 발송 오류 %s (시도 %d)", type(e).__name__, attempt + 1)
    return False

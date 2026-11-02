"""텔레그램 notify 테스트 (httpx.MockTransport, 실제 네트워크 없음)."""
import asyncio

import httpx
import pytest

from app.config import get_settings
from app.services import notify


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")
    monkeypatch.setenv("TELEGRAM_RETRY_DELAY_S", "0")
    get_settings.cache_clear()
    yield
    monkeypatch.setattr(notify, "_transport", None)
    get_settings.cache_clear()


def use(monkeypatch, handler):
    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(handler))


def test_success_sends_chat_id_and_dashboard_link(cfg, monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "http://dash.local")
    get_settings.cache_clear()
    got = []

    def h(req):
        got.append(req)
        return httpx.Response(200, json={"ok": True})

    use(monkeypatch, h)
    assert asyncio.run(notify.send("hi")) is True
    assert "/bot123:SECRET/sendMessage" in str(got[0].url)
    assert b'"chat_id":"-100999"' in got[0].content.replace(b" ", b"")
    assert b"hi\\nhttp://dash.local" in got[0].content


def test_retries_on_5xx_then_succeeds(cfg, monkeypatch):
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(502) if len(n) < 3 else httpx.Response(200)

    use(monkeypatch, h)
    assert asyncio.run(notify.send("x")) is True and len(n) == 3


def test_gives_up_after_retries_and_no_retry_on_auth_error(cfg, monkeypatch):
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(500)

    use(monkeypatch, h)
    assert asyncio.run(notify.send("x")) is False and len(n) == 3  # 1 + 재시도 2

    n.clear()
    use(monkeypatch, lambda r: (n.append(1), httpx.Response(401))[1])
    assert asyncio.run(notify.send("x")) is False and len(n) == 1


def test_network_error_returns_false_and_token_not_logged(cfg, monkeypatch, caplog):
    def h(req):
        raise httpx.ConnectError("boom", request=req)

    use(monkeypatch, h)
    assert asyncio.run(notify.send("x")) is False
    assert "SECRET" not in caplog.text


def test_unconfigured_returns_false(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    assert asyncio.run(notify.send("x")) is False
    get_settings.cache_clear()


def test_long_text_truncated(cfg, monkeypatch):
    sizes = []
    use(monkeypatch, lambda r: (sizes.append(len(r.content)), httpx.Response(200))[1])
    asyncio.run(notify.send("a" * 10000))
    assert sizes and sizes[0] < 4300

"""생존신호: URL 없으면 no-op, 성공/실패 경로, 네트워크 오류 무시 + URL 비노출, run_forever 연결."""
import asyncio
import logging

import httpx
import pytest

from app.config import get_settings
from app.services import heartbeat, monitor

URL = "https://hc-ping.com/secret-uuid"


@pytest.fixture
def hits(monkeypatch):
    got = []

    def handler(req):
        got.append(str(req.url))
        return httpx.Response(200)

    monkeypatch.setattr(heartbeat, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("HEALTHCHECK_URL", URL)
    get_settings.cache_clear()
    yield got
    get_settings.cache_clear()


def test_empty_url_noop(hits, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_URL", "")
    get_settings.cache_clear()
    asyncio.run(heartbeat.ping(True))
    assert hits == []


def test_ok_and_fail(hits):
    asyncio.run(heartbeat.ping(True))
    asyncio.run(heartbeat.ping(False))
    assert hits == [URL, URL + "/fail"]


def test_network_error_swallowed_and_url_not_logged(monkeypatch, caplog):
    def boom(req):
        raise httpx.ConnectTimeout(f"timeout to {req.url}")

    monkeypatch.setattr(heartbeat, "_transport", httpx.MockTransport(boom))
    monkeypatch.setenv("HEALTHCHECK_URL", URL)
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        asyncio.run(heartbeat.ping(True))
    get_settings.cache_clear()
    assert "ConnectTimeout" in caplog.text and "secret-uuid" not in caplog.text


@pytest.mark.parametrize("tick_ok, influx_ok, expect", [(True, True, True), (True, False, False), (False, True, False)])
def test_run_forever_pings_with_health(monkeypatch, tick_ok, influx_ok, expect):
    sent = []

    async def tick(now, started):
        if not tick_ok:
            raise RuntimeError("x")
        return 30

    async def ping_influx():
        return influx_ok

    async def beat(ok):
        sent.append(ok)

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(monitor, "tick", tick)
    monkeypatch.setattr(monitor.influx, "ping", ping_influx)
    monkeypatch.setattr(monitor.heartbeat, "ping", beat)
    monkeypatch.setattr(monitor.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor.run_forever())
    assert sent == [expect]

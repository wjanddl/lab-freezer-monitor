import httpx

from app.config import get_settings


async def write(lines: list[str]) -> None:
    """line protocol(초 단위 정밀도) 기록. 실패 시 httpx.HTTPError 전파."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(
            f"{s.influx_url}/api/v2/write",
            params={"org": s.influx_org, "bucket": s.influx_bucket, "precision": "s"},
            headers={"Authorization": f"Token {s.influx_token}"},
            content="\n".join(lines),
        )
        r.raise_for_status()


async def ping() -> bool:
    """InfluxDB /health 호출. 실패 시 False (예외 전파 안 함)."""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{get_settings().influx_url}/health")
        return r.status_code == 200
    except httpx.HTTPError:
        return False

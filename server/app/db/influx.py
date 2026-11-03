import csv
import io
from datetime import datetime, timezone

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


async def _query(flux: str) -> list[dict]:
    """Flux 실행 → 행(dict) 목록. 실패 시 httpx.HTTPError 전파."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{s.influx_url}/api/v2/query",
            params={"org": s.influx_org},
            headers={"Authorization": f"Token {s.influx_token}", "Accept": "application/csv"},
            json={"query": flux, "dialect": {"annotations": []}},
        )
        r.raise_for_status()
    out, header = [], None
    for row in csv.reader(io.StringIO(r.text)):
        if not any(row):
            header = None  # 테이블 경계(빈 줄) 다음엔 헤더가 다시 온다
        elif header is None:
            header = row
        else:
            out.append(dict(zip(header, row)))
    return out


def _ts(rfc3339: str) -> int:
    return int(datetime.fromisoformat(rfc3339).timestamp())


def _rfc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def series(device_id: str, start: int, stop: int, every_s: int) -> list[dict]:
    """[start, stop) 구간을 every_s 초 창으로 묶은 시계열 [{"ts", "temp_c", "temp_max", "door_open"}] (ts 오름차순).

    temp_c = 창 평균, temp_max = 창 최고(평균에 묻히는 짧은 상승을 놓치지 않게), 값 없으면 None.
    door_open = 창 안에서 한 번이라도 열렸으면 True. ts = 창 시작.
    device_id는 호출자가 패턴 검증한 값만 넘긴다 (Flux 문자열에 들어감).
    """
    base = (
        f'from(bucket: "{get_settings().influx_bucket}") |> range(start: {_rfc(start)}, stop: {_rfc(stop)})'
        f' |> filter(fn: (r) => r._measurement == "freezer_reading" and r.device_id == "{device_id}")'
    )
    win = f'aggregateWindow(every: {every_s}s, timeSrc: "_start", createEmpty: false'
    temp = await _query(f'{base} |> filter(fn: (r) => r._field == "temp_c") |> {win}, fn: mean)')
    tmax = await _query(f'{base} |> filter(fn: (r) => r._field == "temp_c") |> {win}, fn: max)')
    door = await _query(f'{base} |> filter(fn: (r) => r._field == "door_open") |> toInt() |> {win}, fn: max)')
    pts = {}
    empty = lambda: {"temp_c": None, "temp_max": None, "door_open": None}
    for d in temp:
        pts.setdefault(_ts(d["_time"]), empty())["temp_c"] = float(d["_value"])
    for d in tmax:
        pts.setdefault(_ts(d["_time"]), empty())["temp_max"] = float(d["_value"])
    for d in door:
        pts.setdefault(_ts(d["_time"]), empty())["door_open"] = d["_value"] == "1"
    return [{"ts": t, **pts[t]} for t in sorted(pts)]


async def latest(lookback_s: int) -> dict[str, dict]:
    """장치별 가장 최근 측정 시점의 값 {device_id: {"ts", "temp_c", "door_open", "sensor_fault"}}.

    필드별 last()는 시각이 서로 다를 수 있다(temp_c는 센서 오류 시 기록 안 됨).
    가장 최근 ts의 필드만 채우고, 그 시점에 없는 필드는 None (옛 온도를 최신처럼 보이지 않게).
    실패 시 httpx.HTTPError 전파.
    """
    q = (
        f'from(bucket: "{get_settings().influx_bucket}") |> range(start: -{lookback_s}s)'
        ' |> filter(fn: (r) => r._measurement == "freezer_reading")'
        ' |> filter(fn: (r) => r._field == "temp_c" or r._field == "door_open" or r._field == "sensor_fault")'
        ' |> last() |> keep(columns: ["device_id", "_field", "_value", "_time"])'
    )
    rows = {}  # device_id -> {field: (ts, raw)}
    for d in await _query(q):
        rows.setdefault(d["device_id"], {})[d["_field"]] = (_ts(d["_time"]), d["_value"])
    out = {}
    for dev, f in rows.items():
        ts = max(t for t, _ in f.values())
        v = {k: raw for k, (t, raw) in f.items() if t == ts}
        out[dev] = {
            "ts": ts,
            "temp_c": float(v["temp_c"]) if "temp_c" in v else None,
            "door_open": v["door_open"] == "true" if "door_open" in v else None,
            "sensor_fault": int(v["sensor_fault"]) if "sensor_fault" in v else None,
        }
    return out


async def ping() -> bool:
    """InfluxDB /health 호출. 실패 시 False (예외 전파 안 함)."""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{get_settings().influx_url}/health")
        return r.status_code == 200
    except httpx.HTTPError:
        return False

from dataclasses import dataclass

from app.config import Settings
from app.models.reading import FAULT_OUT_OF_RANGE, TEMP_MAX, TEMP_MIN, Reading


@dataclass
class Point:
    """검증/보정이 끝난 측정값 (저장과 이상 판정에 공통으로 사용)."""

    device_id: str
    ts: int
    temp_c: float | None  # null 또는 범위 밖이면 None (범위 밖은 fault에 0x100 추가)
    door_open: bool
    sensor_fault: int
    rssi: int | None
    uptime_s: int | None


def normalize(readings: list[Reading], now: int, s: Settings) -> list[Point]:
    """ts 오름차순, (device_id, ts) 중복은 마지막 값만 남긴다.

    ts가 없거나 허용 범위 밖이면 서버 수신시각(now)으로 대체한다.
    # ponytail: 보정된 ts는 모두 now라서 한 배치 안에서 서로 덮어쓴다. 시계가 틀린 장치의
    # 배치 재전송이 문제되면 펌웨어(7단계)에서 시각 확정 후 전송하도록 한다.
    """
    points = {}
    for r in readings:
        ts = r.ts
        if ts is None or not (now - s.ts_max_age_s <= ts <= now + s.ts_future_tolerance_s):
            ts = now
        temp, fault = r.temp_c, r.sensor_fault
        if temp is not None and not (TEMP_MIN <= temp <= TEMP_MAX):
            temp, fault = None, fault | FAULT_OUT_OF_RANGE
        points[(ts, r.device_id)] = Point(r.device_id, ts, temp, r.door_open, fault, r.rssi, r.uptime_s)
    return [points[k] for k in sorted(points)]


def to_line(p: Point) -> str:
    """InfluxDB line protocol 한 줄."""
    f = [] if p.temp_c is None else [f"temp_c={p.temp_c!r}"]
    f += [f"door_open={'true' if p.door_open else 'false'}", f"sensor_fault={p.sensor_fault}i"]
    if p.rssi is not None:
        f.append(f"rssi={p.rssi}i")
    if p.uptime_s is not None:
        f.append(f"uptime_s={p.uptime_s}i")
    return f"freezer_reading,device_id={p.device_id} {','.join(f)} {p.ts}"

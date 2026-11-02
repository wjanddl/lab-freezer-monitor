"""이상 판정 엔진 (순수 로직: DB/네트워크/시계 호출 없음, 시간은 인자로 주입).

종류(kind)별 상태 머신: NORMAL → PENDING(since_* 기록) → ALERTING(level>0) → RESOLVED.
step_* 함수는 전달받은 State를 직접 갱신하고, 수행할 Action 목록을 돌려준다.
- live=False(과거분 재전송)면 이력(start/resolve)만 만들고 notify=False.
- ts 기준: 온도/도어/센서는 측정값 ts, 무응답은 서버 수신시각.
"""
from dataclasses import dataclass

from app.models.alert_settings import AlertSettings

WARNING, CRITICAL = 1, 2


@dataclass
class State:
    level: int = 0  # 0=정상, 1=WARNING, 2=CRITICAL
    last_ts: float = 0  # 마지막으로 처리한 측정값 ts (이보다 오래된 값은 무시)
    since_w: float | None = None  # 온도 > warn 이 연속된 시작 시각
    since_c: float | None = None  # 온도 > crit 이 연속된 시작 시각
    since: float | None = None  # 도어 열림 / 센서 이상 시작 시각
    bad: int = 0  # 센서 이상 연속 횟수
    ok: int = 0  # 센서 정상 연속 횟수 (알림 중에만 셈)
    peak: float | None = None
    started_at: float | None = None
    notified_at: float | None = None
    notified_level: int = 0
    event_id: int | None = None


@dataclass
class Action:
    op: str  # start | escalate | resolve | notify | remind
    level: int
    ts: float
    value: float | None = None
    notify: bool = False
    event_id: int | None = None
    started_at: float | None = None


def _start(st, level, started_at, ts, value, live):
    st.level, st.started_at = level, started_at
    return Action("start", level, ts, value, live, started_at=started_at)


def _escalate(st, level, ts, value, live):
    st.level = level
    return Action("escalate", level, ts, value, live, st.event_id)


def _resolve(st, ts, live):
    # 시작 알림이 한 번도 나가지 않았다면 복구 알림도 보내지 않는다
    a = Action("resolve", st.level, ts, st.peak, live and st.notified_at is not None, st.event_id)
    last_ts = st.last_ts
    st.__init__()
    st.last_ts = last_ts
    return a


def step_temp(st: State, ts: float, temp: float, live: bool, c: AlertSettings) -> list[Action]:
    """정상 측정된 온도 1건 처리 (센서 이상 값은 호출하지 않는다)."""
    if ts <= st.last_ts:
        return []
    st.last_ts = ts
    # 순간 스파이크 무시: 임계값 이하로 내려가면 지속 타이머 리셋
    st.since_w = (ts if st.since_w is None else st.since_w) if temp > c.temp_warn_c else None
    st.since_c = (ts if st.since_c is None else st.since_c) if temp > c.temp_crit_c else None
    if st.level or st.since_w is not None:
        st.peak = temp if st.peak is None else max(st.peak, temp)
    else:
        st.peak = None

    target = 0
    if st.since_c is not None and ts - st.since_c >= c.temp_crit_min * 60:
        target = CRITICAL
    elif st.since_w is not None and ts - st.since_w >= c.temp_warn_min * 60:
        target = WARNING

    if st.level == 0:
        if target:
            began = st.since_w if st.since_w is not None else st.since_c
            return [_start(st, target, began, ts, st.peak, live)]
        return []
    if target > st.level:
        return [_escalate(st, target, ts, st.peak, live)]
    # 해제: 히스테리시스 임계값 이하로 내려와야 함. CRITICAL→WARNING 하향은 조용히.
    if st.level == CRITICAL and temp <= c.temp_crit_clear_c:
        if temp <= c.temp_warn_clear_c:
            return [_resolve(st, ts, live)]
        st.level = WARNING
    elif st.level == WARNING and temp <= c.temp_warn_clear_c:
        return [_resolve(st, ts, live)]
    return []


def step_door(st: State, ts: float, door_open: bool, live: bool, c: AlertSettings) -> list[Action]:
    if ts <= st.last_ts:
        return []
    st.last_ts = ts
    if not door_open:
        st.since = None
        return [_resolve(st, ts, live)] if st.level else []
    if st.since is None:
        st.since = ts
    mins = (ts - st.since) / 60
    st.peak = mins
    target = CRITICAL if mins >= c.door_crit_min else WARNING if mins >= c.door_warn_min else 0
    if st.level == 0 and target:
        return [_start(st, target, st.since, ts, mins, live)]
    if target > st.level:
        return [_escalate(st, target, ts, mins, live)]
    return []


def step_sensor(st: State, ts: float, bad: bool, live: bool, c: AlertSettings) -> list[Action]:
    if ts <= st.last_ts:
        return []
    st.last_ts = ts
    if bad:
        st.ok = 0
        st.bad += 1
        if st.since is None:
            st.since = ts
        if st.level == 0 and st.bad >= c.sensor_bad_count:
            return [_start(st, CRITICAL, st.since, ts, None, live)]
        return []
    st.bad = 0
    st.since = None
    st.ok = st.ok + 1 if st.level else 0
    if st.level and st.ok >= c.sensor_ok_count:
        return [_resolve(st, ts, live)]
    return []


def step_offline(st: State, now: float, last_seen: float, grace: bool, c: AlertSettings) -> list[Action]:
    """last_seen = 서버가 마지막으로 데이터를 받은 시각. grace=True면 새 알림만 보류."""
    if now - last_seen >= c.offline_after_min * 60:
        if st.level == 0 and not grace:
            return [_start(st, CRITICAL, last_seen, now, None, True)]
        return []
    return [_resolve(st, now, True)] if st.level else []


def step_notice(st: State, now: float, c: AlertSettings) -> list[Action]:
    """알림 중인데 미발송/미전달(과거분, 발송 실패)이면 발송, 아니면 쿨다운 후 재알림."""
    if not st.level:
        return []
    if st.notified_at is None or st.notified_level < st.level:
        return [Action("notify", st.level, now, st.peak, True, st.event_id)]
    interval = (c.remind_crit_min if st.level == CRITICAL else c.remind_warn_min) * 60
    if now - st.notified_at >= interval:
        return [Action("remind", st.level, now, st.peak, True, st.event_id)]
    return []

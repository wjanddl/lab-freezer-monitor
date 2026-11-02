"""엔진 시나리오 테스트 (fake clock: 시각은 숫자로 직접 주입)."""
from app.models.alert_settings import AlertSettings
from app.services.engine import CRITICAL, WARNING, State, step_door, step_notice, step_offline, step_sensor, step_temp

C = AlertSettings()
T0 = 1_000_000


def drive(fn, st, t0, secs, val, live=True, step=10):
    acts = []
    for t in range(t0, t0 + secs + 1, step):
        acts += fn(st, t, val, live, C)
    return acts


def notified(st, level):
    st.notified_at, st.notified_level = T0, level


def test_temp_warning_after_sustained_10min():
    st = State()
    assert drive(step_temp, st, T0, 590, -69) == []
    (a,) = step_temp(st, T0 + 600, -69, True, C)
    assert (a.op, a.level, a.started_at, a.notify) == ("start", WARNING, T0, True)


def test_temp_spike_ignored():
    st = State()
    assert drive(step_temp, st, T0, 180, -65) == []
    assert drive(step_temp, st, T0 + 190, 600, -80) == []
    assert st.level == 0 and st.since_w is None


def test_temp_critical_after_5min():
    st = State()
    (a,) = drive(step_temp, st, T0, 300, -55)
    assert (a.op, a.level, a.started_at) == ("start", CRITICAL, T0)


def test_warning_then_escalate_to_critical():
    st = State()
    drive(step_temp, st, T0, 600, -65)
    assert st.level == WARNING
    notified(st, WARNING)
    acts = drive(step_temp, st, T0 + 610, 300, -55)
    assert [(a.op, a.level) for a in acts] == [("escalate", CRITICAL)]


def test_hysteresis_and_recovery():
    st = State()
    drive(step_temp, st, T0, 600, -69)
    notified(st, WARNING)
    assert drive(step_temp, st, T0 + 610, 300, -71) == []  # 임계값 아래지만 해제선(-73) 위: 유지
    assert st.level == WARNING
    (a,) = step_temp(st, T0 + 1000, -73, True, C)
    assert (a.op, a.notify) == ("resolve", True) and a.value == -69
    assert st.level == 0 and st.peak is None


def test_critical_downgrade_is_silent_then_resolves():
    st = State()
    drive(step_temp, st, T0, 300, -55)
    notified(st, CRITICAL)
    assert step_temp(st, T0 + 310, -65, True, C) == []  # -63 이하 → WARNING으로 조용히 하향
    assert st.level == WARNING
    assert [a.op for a in step_temp(st, T0 + 320, -75, True, C)] == ["resolve"]


def test_out_of_order_reading_ignored():
    st = State()
    step_temp(st, T0, -69, True, C)
    assert step_temp(st, T0 - 10, -30, True, C) == [] and st.since_c is None


def test_door_open_warning_critical_resolve():
    st = State()
    assert drive(step_door, st, T0, 170, True) == []
    assert [a.level for a in drive(step_door, st, T0 + 180, 0, True)] == [WARNING]
    notified(st, WARNING)
    assert [(a.op, a.level) for a in drive(step_door, st, T0 + 190, 410, True)] == [("escalate", CRITICAL)]
    notified(st, CRITICAL)
    (a,) = step_door(st, T0 + 700, False, True, C)
    assert a.op == "resolve" and a.notify and a.value >= 10


def test_door_short_open_ignored():
    st = State()
    drive(step_door, st, T0, 120, True)
    assert step_door(st, T0 + 130, False, True, C) == [] and st.since is None


def test_sensor_needs_3_consecutive_bad():
    st = State()
    drive(step_sensor, st, T0, 10, True)  # 2회
    drive(step_sensor, st, T0 + 20, 0, False)  # 정상이 끼면 리셋
    assert drive(step_sensor, st, T0 + 30, 10, True) == []
    (a,) = drive(step_sensor, st, T0 + 50, 0, True)
    assert (a.op, a.level, a.started_at) == ("start", CRITICAL, T0 + 30)
    notified(st, CRITICAL)
    assert drive(step_sensor, st, T0 + 60, 10, False) == []  # 정상 2회
    assert [a.op for a in drive(step_sensor, st, T0 + 80, 0, False)] == ["resolve"]


def test_offline_start_grace_and_resolve():
    st = State()
    assert step_offline(st, T0 + 179, T0, False, C) == []
    assert step_offline(st, T0 + 500, T0, True, C) == []  # 시작 유예
    (a,) = step_offline(st, T0 + 180, T0, False, C)
    assert (a.op, a.level, a.started_at) == ("start", CRITICAL, T0)
    notified(st, CRITICAL)
    (r,) = step_offline(st, T0 + 200, T0 + 200, False, C)  # 데이터 수신 재개
    assert (r.op, r.notify) == ("resolve", True)


def test_backfill_records_history_without_notifying_then_notice():
    st = State()
    (a,) = drive(step_temp, st, T0, 600, -69, live=False)
    assert (a.op, a.notify) == ("start", False)
    (n,) = step_notice(st, T0 + 700, C)  # 아직 알림이 안 나갔으니 현재 진행 중 알림
    assert n.op == "notify"
    st2 = State()
    drive(step_temp, st2, T0, 600, -69, live=False)
    (r,) = step_temp(st2, T0 + 700, -80, False, C)
    assert (r.op, r.notify) == ("resolve", False)  # 알린 적 없으니 복구도 조용히


def test_reminder_cooldown():
    st = State(level=CRITICAL)
    notified(st, CRITICAL)
    assert step_notice(st, T0 + 1799, C) == []
    assert [a.op for a in step_notice(st, T0 + 1800, C)] == ["remind"]
    st = State(level=WARNING)
    notified(st, WARNING)
    assert step_notice(st, T0 + 3599, C) == [] and step_notice(st, T0 + 3600, C)[0].op == "remind"


def test_unnotified_escalation_is_retried():
    st = State(level=CRITICAL)
    notified(st, WARNING)  # CRITICAL 승격 알림 발송 실패
    assert step_notice(st, T0 + 30, C)[0].op == "notify"

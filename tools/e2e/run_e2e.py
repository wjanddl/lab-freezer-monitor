"""E2E 시나리오 (docker-compose.e2e.yml의 runner 컨테이너 안에서 실행).

실제 api/InfluxDB/가짜 텔레그램을 띄운 상태에서 시뮬레이터로 측정값을 보내고
알림 문구, 이력, 조회 API를 확인한다. 판정 시간은 settings API로 초 단위로 줄인다.
"""
import json
import math
import sys
import time
import urllib.request

sys.path[:0] = ["/e2e_tools", "/srv"]  # 시뮬레이터, api 이미지의 app 패키지
from simulate import post, reading  # noqa: E402

from app.services import auth, devices  # noqa: E402  (같은 SQLite 볼륨에 직접 등록)

BASE, TG, DEV = "http://api:8000", "http://telegram:8081", "freezer-01"
STEP = 2  # 측정 주기(초)
results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)


def call(method, path, token, body=None, params=""):
    req = urllib.request.Request(BASE + path + params, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                                 method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def login(user, pw):
    req = urllib.request.Request(BASE + "/api/v1/auth/login", json.dumps({"username": user, "password": pw}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["access_token"]


def msgs():
    with urllib.request.urlopen(TG + "/messages", timeout=5) as r:
        return json.load(r)


def wait_msgs(n, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        m = msgs()
        if len(m) >= n:
            return m
        time.sleep(0.5)
    return msgs()


def send_for(seconds, temp=-80.0, door=False, fault=0):
    """seconds 동안 STEP초 간격 전송. 매 전송 뒤 쉬므로 다음 단계 첫 측정값 ts가 겹치지 않는다
    (같은 ts는 서버가 중복으로 보고 판정에서 무시함)."""
    for _ in range(max(1, seconds // STEP)):
        post(BASE, KEY, reading(DEV, temp, door, fault))
        time.sleep(STEP)


def expect_new(label, prev, *needles):
    """prev개 이후 새 메시지가 needles 순서대로 왔는지."""
    m = wait_msgs(prev + len(needles))
    new = m[prev:]
    ok = len(new) == len(needles) and all(all(x in t for x in n) for t, n in zip(new, needles))
    check(label, ok, f"new={new}")
    return len(m)


KEY = devices.create_device(DEV)
auth.create_user("e2e-admin", "e2e-admin-password", "admin")
auth.create_user("e2e-viewer", "e2e-viewer-password", "viewer")
admin, viewer = login("e2e-admin", "e2e-admin-password"), login("e2e-viewer", "e2e-viewer-password")

# 0) 과거 2시간치(6초 간격) 백필 → 다운샘플링 확인용. 과거분이라 알림 없음
now = int(time.time())
hist = [reading(DEV, round(-80 + 0.5 * math.sin(i / 50), 2), False, 0, now - 7200 + i * 6) for i in range(1180)]
for i in range(0, len(hist), 400):
    post(BASE, KEY, hist[i:i + 400])

call("PUT", "/api/v1/settings", admin, {
    "temp_warn_min": 0.1, "temp_crit_min": 0.1, "door_warn_min": 0.1, "door_crit_min": 0.2,
    "offline_after_min": 0.25, "tick_interval_s": 5, "startup_grace_s": 0,
    "remind_warn_min": 1000, "remind_crit_min": 1000,
})

r = call("GET", "/api/v1/readings", viewer, params=f"?device_id={DEV}&from={now - 7200}&to={now}")
temps = [p["temp_c"] for p in r["points"]]
check("readings: 1180점 → 500점 이하로 다운샘플", r["interval_s"] == 15 and 400 <= len(temps) <= 500,
      f"interval={r['interval_s']} n={len(temps)}")
check("readings: 창 평균값 범위 정상", all(-80.6 <= t <= -79.4 for t in temps), f"min={min(temps)} max={max(temps)}")

# 1) 정상
send_for(6, -79.8)
st = call("GET", "/api/v1/status", viewer)["devices"][0]
check("정상: 알림 없음, status OK/online", msgs() == [] and st["alarm_level"] == "OK" and st["online"]
      and abs(st["reading"]["temp_c"] + 79.8) < 0.01, f"msgs={msgs()} st={st}")

# 2) WARNING → 3) CRITICAL → 4) 복구
n = 0
send_for(10, -68.0)
n = expect_new("온도 WARNING (지속시간 후)", n, ("[WARNING]", "온도", "-68.0"))
check("status WARNING", call("GET", "/api/v1/status", viewer)["devices"][0]["alarm_level"] == "WARNING")
send_for(10, -58.0)
n = expect_new("온도 CRITICAL 승격", n, ("[CRITICAL]", "온도", "-58.0"))
send_for(4, -80.0)
n = expect_new("온도 복구 알림", n, ("복구됨", "온도"))

# 5) 문 장시간 열림 → WARNING → CRITICAL → 닫힘 복구
send_for(16, -80.0, door=True)
n = expect_new("문 열림 WARNING→CRITICAL", n, ("[WARNING]", "문 열림"), ("[CRITICAL]", "문 열림"))
send_for(2, -80.0)
n = expect_new("문 닫힘 복구", n, ("복구됨", "문 열림"))

# 6) 센서 장애 (fault 연속 3회) → 정상 3회 복구
send_for(6, None, fault=1)
n = expect_new("센서 장애 CRITICAL", n, ("[CRITICAL]", "센서 장애"))
send_for(6, -80.0)
n = expect_new("센서 복구", n, ("복구됨", "센서 장애"))

# 7) 무응답 (전송 중단) → 재개 시 복구
time.sleep(15)
n = expect_new("무응답 CRITICAL (데이터 끊김 = 이상)", n, ("[CRITICAL]", "장치 무응답"))
check("status offline", not call("GET", "/api/v1/status", viewer)["devices"][0]["online"])
send_for(2, -80.0)
n = expect_new("무응답 복구", n, ("복구됨", "장치 무응답"))

# 8) 조회 API (실데이터)
now = int(time.time())
r = call("GET", "/api/v1/readings", viewer, params=f"?device_id={DEV}&from={now - 150}&to={now + 1}")
check("readings: 최근 구간에 문 열림 창 포함", any(p["door_open"] for p in r["points"]))
check("readings: 센서 오류 구간 temp 없음은 null 또는 생략",
      all(p["temp_c"] is None or -81 <= p["temp_c"] <= -57 for p in r["points"]))

ev = call("GET", "/api/v1/events", viewer)["events"]
by = {e["type"]: e for e in ev}
check("events: temp/door/sensor/offline 각 1건, 모두 해제",
      sorted(by) == ["door", "offline", "sensor", "temp"] and len(ev) == 4 and all(e["resolved_at"] for e in ev),
      json.dumps(ev, ensure_ascii=False))
check("events: 온도 최고 단계 CRITICAL, peak -58", by["temp"]["severity"] == "CRITICAL" and by["temp"]["peak_value"] == -58.0)
check("events: 문 최고 CRITICAL", by["door"]["severity"] == "CRITICAL")
check("events?active=true 비어 있음", call("GET", "/api/v1/events", viewer, params="?active=true")["events"] == [])

a = call("POST", f"/api/v1/events/{by['temp']['id']}/ack", viewer)
check("ack: viewer가 확인", a["acknowledged_by"] == "e2e-viewer" and a["acknowledged_at"])

st = call("GET", "/api/v1/status", viewer)["devices"][0]
check("최종 status OK/online/알림 10건(재알림 없음)", st["alarm_level"] == "OK" and st["online"] and len(msgs()) == 10,
      f"st={st} msgs={len(msgs())}")

print(f"\n결과: {sum(results)}/{len(results)} PASS", flush=True)
sys.exit(0 if all(results) else 1)

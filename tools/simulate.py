"""센서 없이 측정값을 보내는 시뮬레이터 (표준 라이브러리만 사용).

예) 정상값 10초마다 무한 전송:
    set FREEZER_KEY=<장치 API 키>
    python tools/simulate.py --base http://100.80.80.16:8000 --temp -79.8 --interval 10
예) 문 열림 5번:  --door --count 5      센서 오류:  --fault 1 --no-temp
주의: 운영 서버로 보내면 판정 엔진이 실제 텔레그램 알림을 보낼 수 있다.
"""
import argparse
import json
import os
import random
import time
import urllib.request


def reading(device_id, temp_c, door_open=False, sensor_fault=0, ts=None):
    return {"device_id": device_id, "ts": int(time.time()) if ts is None else ts,
            "temp_c": temp_c, "door_open": door_open, "sensor_fault": sensor_fault}


def post(base, key, readings):
    """측정값(1건 또는 목록) 전송 → 응답 JSON. HTTP 오류는 urllib.error.HTTPError."""
    req = urllib.request.Request(f"{base}/api/v1/readings", json.dumps(readings).encode(),
                                 {"Content-Type": "application/json", "X-API-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--key", default=os.environ.get("FREEZER_KEY"), help="기본: 환경변수 FREEZER_KEY")
    p.add_argument("--device", default="freezer-01")
    p.add_argument("--temp", type=float, default=-79.8)
    p.add_argument("--jitter", type=float, default=0.2, help="온도 랜덤 흔들림(±℃)")
    p.add_argument("--no-temp", action="store_true", help="temp_c=null (센서 오류 흉내)")
    p.add_argument("--door", action="store_true", help="문 열림")
    p.add_argument("--fault", type=int, default=0, help="MAX31865 fault 비트")
    p.add_argument("--interval", type=float, default=10)
    p.add_argument("--count", type=int, default=0, help="0이면 무한")
    a = p.parse_args()
    if not a.key:
        p.error("--key 또는 FREEZER_KEY 필요")
    n = 0
    while not a.count or n < a.count:
        t = None if a.no_temp else round(a.temp + random.uniform(-a.jitter, a.jitter), 2)
        print(post(a.base, a.key, reading(a.device, t, a.door, a.fault)), flush=True)
        n += 1
        if not a.count or n < a.count:
            time.sleep(a.interval)


if __name__ == "__main__":
    main()

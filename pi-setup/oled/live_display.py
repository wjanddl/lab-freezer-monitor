"""냉동고 서버(/api/v1/status)를 10초마다 읽어 OLED(ssd1306 128x32)에 표시.

왼쪽: 최신 온도 / 오른쪽 위: 서버 판정 상태 / 오른쪽 아래: 측정 시각(KST HH:MM).
- 값이 없거나 STALE_S보다 오래됐으면 NO DATA (가짜 값 표시 안 함)
- 서버에 못 붙으면 NO SERVER
- ALARM(서버 CRITICAL)은 반전 + 깜빡임
로그인 정보: ~/freezer-oled/.oled_cred (JSON: base, username, password, 권한 600)
"""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

DEVICE_ID = "freezer-01"
POLL_S = 10
STALE_S = 180  # 측정값이 이보다 오래되면 NO DATA
LOW_C = -85  # 서버 판정이 OK여도 이보다 낮으면 LOW 표시 (표시 전용)
BLINK_S = 0.5
KST = ZoneInfo("Asia/Seoul")
CRED = json.loads((Path.home() / "freezer-oled" / ".oled_cred").read_text())

serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=128, height=32)
device.persist = True
big = ImageFont.load_default(size=20)
mid = ImageFont.load_default(size=14)
small = ImageFont.load_default(size=11)

_tokens = {}


def _post(path, body):
    req = urllib.request.Request(CRED["base"] + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def _login():
    _tokens.update(_post("/api/v1/auth/login", {"username": CRED["username"], "password": CRED["password"]}))


def _refresh():
    try:
        _tokens.update(_post("/api/v1/auth/refresh", {"refresh_token": _tokens["refresh_token"]}))
    except (urllib.error.HTTPError, KeyError):
        _login()


def get_status():
    if "access_token" not in _tokens:
        _login()
    for attempt in range(2):
        req = urllib.request.Request(CRED["base"] + "/api/v1/status",
                                     headers={"Authorization": f"Bearer {_tokens['access_token']}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 401 or attempt:
                raise
            _refresh()  # access 만료(1시간) → refresh 후 한 번 더


def view(st):
    """상태 응답 → (왼쪽 글자, 왼쪽 큰글씨 여부, 상태, 시각)."""
    dev = next((d for d in st["devices"] if d["device_id"] == DEVICE_ID), None)
    if dev is None:
        return "NO DEV", False, "?", "--:--"
    level = {"CRITICAL": "ALARM", "WARNING": "WARN"}.get(dev["alarm_level"], "OK")
    rd = dev["reading"]
    if not rd or st["server_time"] - rd["ts"] > STALE_S:
        hhmm = datetime.fromtimestamp(rd["ts"], KST).strftime("%H:%M") if rd else "--:--"
        return "NO DATA", False, level, hhmm
    hhmm = datetime.fromtimestamp(rd["ts"], KST).strftime("%H:%M")
    if rd["temp_c"] is None:
        return "SENSOR?", False, level, hhmm
    if level == "OK" and rd["temp_c"] < LOW_C:
        level = "LOW"
    return f"{rd['temp_c']:.1f}°C", True, level, hhmm


def draw(left, is_big, level, hhmm, inverted):
    fg = "black" if inverted else "white"
    with canvas(device) as d:
        if inverted:
            d.rectangle(device.bounding_box, fill="white")
        if level == "LOW":
            d.rectangle((0, 0, 127, 31), outline=fg)
        d.text((2, 6) if is_big else (2, 8), left, font=big if is_big else mid, fill=fg)
        d.line((84, 0, 84, 31), fill=fg)
        d.text((88, 2), level, font=small, fill=fg)
        d.text((88, 18), hhmm, font=small, fill=fg)


def main():
    while True:
        try:
            frame = view(get_status())
        except (urllib.error.URLError, OSError, ValueError) as e:
            frame = ("NO SERVER", False, "?", "--:--")
            print(f"서버 오류: {type(e).__name__}", flush=True)
            _tokens.clear()  # 서버 재시작 등으로 토큰이 무효일 수 있으니 다음엔 새로 로그인
        print(f"{datetime.now(KST):%H:%M:%S} 표시: {frame[0]} | {frame[2]} | {frame[3]}", flush=True)
        end = time.time() + POLL_S
        inverted = True
        while time.time() < end:
            draw(*frame, inverted=frame[2] == "ALARM" and inverted)
            if frame[2] != "ALARM":
                time.sleep(max(0, end - time.time()))
                break
            inverted = not inverted
            time.sleep(BLINK_S)


if __name__ == "__main__":
    main()

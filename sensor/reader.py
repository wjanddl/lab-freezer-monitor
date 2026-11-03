"""Pi 센서 리더: MAX31865(SPI)로 온도, (선택) 리드스위치(GPIO)로 문 상태를 읽어 서버로 전송.

실행: python reader.py config.json   (설정 예시: config.example.json, 실제 파일은 권한 600)
- 전송 실패 시 메모리 버퍼에 쌓아 두었다가 다음 성공 때 한 번에 재전송 (데이터 유실 방지)
- 서버가 같은 ts를 중복으로 무시하므로 한 주기에 1건, ts는 초 단위로 항상 증가
- door_gpio가 null이면 문 센서 없음 → door_open=false 고정 (문 열림 경보는 동작하지 않음)
"""
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from collections import deque

log = logging.getLogger("reader")
MAX_BATCH = 500  # 서버 수신 API 배치 상한


class Reader:
    def __init__(self, cfg: dict, sensor, door=None, now=time.time):
        self.cfg, self.sensor, self.door, self.now = cfg, sensor, door, now
        self.buf = deque(maxlen=cfg.get("buffer_max", 8640))  # 기본: 10초 주기 24시간분
        self.last_ts = 0

    def sample(self) -> dict:
        temp, fault = self.sensor.read()
        ts = max(int(self.now()), self.last_ts + 1)
        self.last_ts = ts
        return {"device_id": self.cfg["device_id"], "ts": ts,
                "temp_c": None if temp is None else round(temp, 2),
                "door_open": bool(self.door()) if self.door else False, "sensor_fault": fault}

    def post(self, batch: list[dict]) -> None:
        req = urllib.request.Request(self.cfg["base"].rstrip("/") + "/api/v1/readings", json.dumps(batch).encode(),
                                     {"Content-Type": "application/json", "X-API-Key": self.cfg["api_key"]})
        with urllib.request.urlopen(req, timeout=self.cfg.get("timeout_s", 5)):
            pass

    def step(self) -> None:
        """1주기: 측정 → 버퍼에 추가 → 오래된 것부터 배치 전송. 실패하면 버퍼에 남겨 다음 주기에 재시도."""
        try:
            self.buf.append(self.sample())
        except Exception as e:  # 센서 통신 자체 실패도 '데이터 없음'으로 서버가 판단하게 둔다
            log.error("센서 읽기 실패 %s", type(e).__name__)
        while self.buf:
            batch = list(self.buf)[:MAX_BATCH]
            try:
                self.post(batch)
            except urllib.error.HTTPError as e:
                if e.code in (400, 422):  # 형식 오류는 재전송해도 같음. 401/403(키)·5xx는 보관 후 재시도
                    log.error("서버가 형식 거부 %s: %d건 폐기", e.code, len(batch))
                    for _ in batch:
                        self.buf.popleft()
                    continue
                log.warning("전송 실패 %s, 버퍼 %d건", e.code, len(self.buf))
                return
            except (urllib.error.URLError, OSError) as e:
                log.warning("전송 실패 %s, 버퍼 %d건", type(e).__name__, len(self.buf))
                return
            for _ in batch:
                self.buf.popleft()


def main(path: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.load(open(path, encoding="utf-8"))
    import spidev  # Pi에서만 필요 (테스트는 가짜 SPI 사용)

    from max31865 import MAX31865

    spi = spidev.SpiDev()
    spi.open(cfg.get("spi_bus", 0), cfg.get("spi_device", 0))
    spi.max_speed_hz, spi.mode = 1_000_000, 1
    sensor = MAX31865(spi, cfg.get("wires", 3), cfg.get("rref", 430.0), cfg.get("r0", 100.0), cfg.get("filter_hz", 60))
    door = None
    if cfg.get("door_gpio") is not None:
        from gpiozero import Button
        # 리드스위치: 문 닫힘 = 자석 붙음 = 스위치 닫힘(GND 연결) = is_pressed. 배선이 반대면 door_open_when_pressed=true
        btn = Button(cfg["door_gpio"], pull_up=True)
        inv = cfg.get("door_open_when_pressed", False)
        door = (lambda: btn.is_pressed) if inv else (lambda: not btn.is_pressed)
    r = Reader(cfg, sensor, door)
    interval = cfg.get("interval_s", 10)
    while True:
        start = time.monotonic()
        r.step()
        time.sleep(max(0, interval - (time.monotonic() - start)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config.json")

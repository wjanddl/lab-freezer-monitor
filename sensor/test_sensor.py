"""하드웨어 없이 검증: CVD 변환(IEC 60751 표값), 가짜 SPI로 MAX31865 레지스터 동작, 전송 버퍼/재전송."""
import urllib.error

import pytest

from max31865 import CFG_3WIRE, CFG_VBIAS, MAX31865, resistance_to_temp
from reader import Reader


@pytest.mark.parametrize("r, t", [(100.0, 0.0), (138.51, 100.0), (68.33, -80.0), (60.26, -100.0), (18.52, -200.0)])
def test_cvd_matches_iec_table(r, t):
    assert resistance_to_temp(r) == pytest.approx(t, abs=0.02)


class FakeSPI:
    """MAX31865 레지스터 흉내. rtd_ohm로 ADC 값을 만들고, fault를 줄 수 있다."""

    def __init__(self, rtd_ohm=68.33, rref=430.0, fault=0):
        self.cfg_writes, self.fault = [], fault
        adc = round(rtd_ohm / rref * 32768)
        self.rtd = (adc << 1) | (1 if fault else 0)

    def xfer2(self, data):
        if data[0] & 0x80:
            self.cfg_writes.append(data[1])
            return [0, 0]
        reg = data[0]
        if reg == 0x01:
            return [0, self.rtd >> 8, self.rtd & 0xFF]
        if reg == 0x07:
            return [0, self.fault]
        raise AssertionError(reg)


def test_read_3wire_minus80():
    spi = FakeSPI(68.33)
    t, fault = MAX31865(spi, wires=3, sleep=lambda s: None).read()
    assert fault == 0 and t == pytest.approx(-80.0, abs=0.05)
    assert all(w & CFG_3WIRE for w in spi.cfg_writes)  # 3선 비트 항상 유지
    assert spi.cfg_writes[-1] & CFG_VBIAS == 0  # 측정 후 바이어스 끔


def test_read_fault_returns_none():
    t, fault = MAX31865(FakeSPI(fault=0x84), sleep=lambda s: None).read()
    assert t is None and fault == 0x84


class FakeSensor:
    def __init__(self):
        self.vals = iter([(-80.0, 0), (None, 0x40), (-79.5, 0), (-79.4, 0)])

    def read(self):
        return next(self.vals)


def test_buffer_retries_and_ts_increase():
    cfg = {"base": "http://x", "device_id": "freezer-01", "api_key": "k"}
    r = Reader(cfg, FakeSensor(), now=lambda: 1000)  # 시계가 안 움직여도 ts는 증가
    sent, fail = [], [True, True, False, False]

    def post(batch):
        if fail.pop(0):
            raise urllib.error.URLError("down")
        sent.extend(batch)

    r.post = post
    for _ in range(4):
        r.step()
    assert [p["ts"] for p in sent] == [1000, 1001, 1002, 1003]  # 실패분 포함 순서대로 재전송
    assert sent[1]["temp_c"] is None and sent[1]["sensor_fault"] == 0x40
    assert all(p["door_open"] is False for p in sent) and not r.buf


def test_format_error_drops_but_auth_error_keeps():
    cfg = {"base": "http://x", "device_id": "freezer-01", "api_key": "k"}
    r = Reader(cfg, FakeSensor(), now=lambda: 1000)

    def err(code):
        def post(batch):
            raise urllib.error.HTTPError("u", code, "x", {}, None)
        return post

    r.post = err(401)
    r.step()
    assert len(r.buf) == 1  # 키 문제는 고칠 수 있으니 보관
    r.post = err(422)
    r.step()
    assert len(r.buf) == 0

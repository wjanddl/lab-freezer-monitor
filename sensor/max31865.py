"""MAX31865 (PT100 RTD 변환기) 최소 드라이버. spidev 호환 객체(xfer2)만 있으면 동작 → 테스트에서 가짜 SPI 주입.

데이터시트 기준: 설정 레지스터 0x00(쓰기 0x80), RTD 0x01~0x02(15비트 + fault 플래그), fault 상태 0x07.
"""
import time

REG_CONFIG, REG_RTD_MSB, REG_FAULT = 0x00, 0x01, 0x07
CFG_VBIAS, CFG_1SHOT, CFG_3WIRE, CFG_FAULT_CLEAR, CFG_50HZ = 0x80, 0x20, 0x10, 0x02, 0x01

# IEC 60751 Callendar–Van Dusen 계수 (PT100, α=0.00385)
A, B, C = 3.9083e-3, -5.775e-7, -4.183e-12


def resistance_to_temp(r: float, r0: float = 100.0) -> float:
    """RTD 저항(Ω) → 온도(℃). 0℃ 이상은 2차식 해, 미만은 C항 포함 식을 뉴턴법으로 푼다."""
    if r >= r0:
        return (-A + (A * A - 4 * B * (1 - r / r0)) ** 0.5) / (2 * B)
    t = (r / r0 - 1) / A  # 초기값(선형 근사)
    for _ in range(20):
        f = r0 * (1 + A * t + B * t * t + C * (t - 100) * t ** 3) - r
        df = r0 * (A + 2 * B * t + C * (4 * t ** 3 - 300 * t * t))
        step = f / df
        t -= step
        if abs(step) < 1e-6:
            break
    return t


class MAX31865:
    def __init__(self, spi, wires: int = 3, rref: float = 430.0, r0: float = 100.0, filter_hz: int = 60,
                 sleep=time.sleep):
        if wires not in (2, 3, 4):
            raise ValueError("wires는 2, 3, 4")
        self.spi, self.rref, self.r0, self.sleep = spi, rref, r0, sleep
        self.base = (CFG_3WIRE if wires == 3 else 0) | (CFG_50HZ if filter_hz == 50 else 0)
        self._write(self.base | CFG_FAULT_CLEAR)

    def _write(self, cfg: int) -> None:
        self.spi.xfer2([0x80 | REG_CONFIG, cfg])

    def _read(self, reg: int, n: int) -> list[int]:
        return self.spi.xfer2([reg] + [0] * n)[1:]

    def read(self) -> tuple[float | None, int]:
        """1회 측정 → (온도℃ 또는 None, fault 바이트). fault가 있으면 지우고 온도는 None."""
        self._write(self.base | CFG_VBIAS)
        self.sleep(0.01)  # 바이어스 안정화
        self._write(self.base | CFG_VBIAS | CFG_1SHOT)
        self.sleep(0.065)  # 변환 시간 (60Hz 필터 ~52ms, 50Hz ~62.5ms)
        msb, lsb = self._read(REG_RTD_MSB, 2)
        fault = self._read(REG_FAULT, 1)[0] if lsb & 1 else 0
        self._write(self.base | (CFG_FAULT_CLEAR if fault else 0))  # 바이어스 끄기(자기발열 최소화)
        if fault:
            return None, fault
        adc = ((msb << 8) | lsb) >> 1
        return resistance_to_temp(adc / 32768 * self.rref, self.r0), 0

from pydantic import BaseModel, Field

TEMP_MIN, TEMP_MAX = -200.0, 100.0
# MAX31865 fault 비트는 8비트(0x01~0x80). 서버가 추가하는 "온도 범위 이상" 비트는 그 위에 둔다.
FAULT_OUT_OF_RANGE = 0x100
MAX_BATCH = 500


class Reading(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    ts: int | None = Field(None, ge=0)  # epoch 초(UTC). 없으면 서버 수신시각
    seq: int | None = Field(None, ge=0)  # 현재는 저장하지 않음 (중복은 device_id+ts로 판단)
    temp_c: float | None = Field(None, allow_inf_nan=False)  # 센서 오류 시 null
    door_open: bool  # fail-safe: 필수값
    sensor_fault: int = Field(0, ge=0, le=255)
    rssi: int | None = None
    uptime_s: int | None = Field(None, ge=0)

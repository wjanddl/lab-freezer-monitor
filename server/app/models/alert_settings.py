from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertSettings(BaseModel):
    """이상 판정 설정. 기본값은 확정된 초기값이며 API/DB로 변경 가능."""

    model_config = ConfigDict(extra="forbid")

    # 온도 (℃ / 분)
    temp_warn_c: float = -70
    temp_warn_min: float = Field(10, gt=0)
    temp_warn_clear_c: float = -73  # 히스테리시스: 이 값 이하로 내려와야 해제
    temp_crit_c: float = -60
    temp_crit_min: float = Field(5, gt=0)
    temp_crit_clear_c: float = -63
    # 도어 (분)
    door_warn_min: float = Field(3, gt=0)
    door_crit_min: float = Field(10, gt=0)
    # 센서 장애
    sensor_bad_count: int = Field(3, ge=1)  # 연속 N회 이상이면 장애
    sensor_ok_count: int = Field(3, ge=1)  # 연속 N회 정상이면 복구
    sensor_min_c: float = -120
    sensor_max_c: float = 50
    # 무응답 / 재알림
    offline_after_min: float = Field(3, gt=0)
    remind_warn_min: float = Field(60, gt=0)
    remind_crit_min: float = Field(30, gt=0)
    # 운영
    startup_grace_s: int = Field(180, ge=0)  # 서버 시작 직후 무응답 판정 유예
    backfill_after_s: int = Field(60, ge=0)  # 이보다 오래된 측정값은 과거분(알림 없음)
    tick_interval_s: int = Field(30, ge=5)

    @model_validator(mode="after")
    def _check_order(self):
        if not self.temp_warn_clear_c < self.temp_warn_c < self.temp_crit_c:
            raise ValueError("temp_warn_clear_c < temp_warn_c < temp_crit_c 이어야 함")
        if not self.temp_crit_clear_c < self.temp_crit_c:
            raise ValueError("temp_crit_clear_c < temp_crit_c 이어야 함")
        if not self.door_warn_min < self.door_crit_min:
            raise ValueError("door_warn_min < door_crit_min 이어야 함")
        if not self.sensor_min_c < self.sensor_max_c:
            raise ValueError("sensor_min_c < sensor_max_c 이어야 함")
        return self

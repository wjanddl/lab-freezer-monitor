from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    influx_url: str = "http://influxdb:8086"
    influx_org: str = "lab"
    influx_bucket: str = "freezer"
    influx_token: str = ""
    sqlite_path: str = "/data/sqlite/app.db"
    jwt_secret: str = ""  # 비밀값. 32자 이상 랜덤. 비어 있으면 인증 API는 503
    access_ttl_s: int = 3600
    refresh_ttl_s: int = 14 * 86400
    login_max_fails: int = 5
    login_lock_s: int = 900
    telegram_bot_token: str = ""  # 비밀값. .env에만 둔다
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"  # E2E에서 가짜 텔레그램 서버로 바꿀 때만 변경
    dashboard_url: str = ""  # 비우면 알림에 링크 생략
    healthcheck_url: str = ""  # 비밀값(healthchecks.io ping URL). 비우면 생존신호 안 보냄
    heartbeat_interval_s: int = 60
    heartbeat_timeout_s: float = 5
    telegram_timeout_s: float = 10
    telegram_retries: int = 2  # 최초 시도 외 추가 시도 횟수
    telegram_retry_delay_s: float = 2
    # ts 검증: 미래 허용 오차 / 과거 허용 최대 나이(초). 벗어나면 서버 수신시각으로 대체
    ts_future_tolerance_s: int = 300
    ts_max_age_s: int = 30 * 86400
    status_lookback_s: int = 30 * 86400  # /status 최신값 조회 범위. 이보다 오래 끊긴 장치는 reading=null
    readings_max_points: int = 500  # /readings 응답 점 개수 상한 (넘으면 창 평균)
    readings_max_range_s: int = 366 * 86400
    cors_origins: str = ""  # 프론트 주소, 쉼표 구분 (예: http://localhost:5173). 비우면 CORS 미허용


@lru_cache
def get_settings() -> Settings:
    return Settings()

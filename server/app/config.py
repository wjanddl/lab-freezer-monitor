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
    dashboard_url: str = ""  # 비우면 알림에 링크 생략
    telegram_timeout_s: float = 10
    telegram_retries: int = 2  # 최초 시도 외 추가 시도 횟수
    telegram_retry_delay_s: float = 2
    # ts 검증: 미래 허용 오차 / 과거 허용 최대 나이(초). 벗어나면 서버 수신시각으로 대체
    ts_future_tolerance_s: int = 300
    ts_max_age_s: int = 30 * 86400


@lru_cache
def get_settings() -> Settings:
    return Settings()

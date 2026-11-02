import os
import sqlite3

from app.config import get_settings

# 테이블은 단계가 진행되며 여기에 추가 (CREATE IF NOT EXISTS)
SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id  TEXT PRIMARY KEY,
    key_hash   TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_status (
    device_id TEXT PRIMARY KEY,
    last_seen REAL NOT NULL            -- 마지막 수신 시각(서버 기준, epoch 초 UTC)
);
CREATE TABLE IF NOT EXISTS alert_state (
    device_id TEXT NOT NULL,
    kind      TEXT NOT NULL,           -- temp | door | sensor | offline
    json      TEXT NOT NULL,
    PRIMARY KEY (device_id, kind)
);
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT NOT NULL,
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL,     -- 도달한 최고 심각도 WARNING | CRITICAL
    started_at      INTEGER NOT NULL,  -- epoch 초 UTC
    resolved_at     INTEGER,
    peak_value      REAL,              -- temp: 최고온도, door: 최장 열림(분)
    message         TEXT,
    acknowledged_by TEXT,
    acknowledged_at INTEGER
);
CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,
    pw_hash    TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,           -- SHA-256(평문 토큰). 평문은 저장하지 않음
    username   TEXT NOT NULL,
    expires_at INTEGER NOT NULL,           -- epoch 초 UTC
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_attempts (
    key          TEXT PRIMARY KEY,         -- username|ip
    fails        INTEGER NOT NULL,
    locked_until REAL NOT NULL             -- epoch 초 UTC
);
CREATE INDEX IF NOT EXISTS idx_events_dev_started ON events (device_id, started_at);
"""


def connect() -> sqlite3.Connection:
    """SQLite 연결 (경로 폴더/테이블 자동 생성). 호출자가 contextlib.closing으로 닫을 것."""
    path = get_settings().sqlite_path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db

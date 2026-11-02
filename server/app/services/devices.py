import hashlib
import hmac
import secrets
from contextlib import closing

from fastapi import Header, HTTPException

from app.db import sqlite


def _hash(key: str) -> str:
    # 키가 고엔트로피 랜덤값이라 솔트 없는 SHA-256으로 충분
    return hashlib.sha256(key.encode()).hexdigest()


def create_device(device_id: str) -> str:
    """장치 등록(이미 있으면 키 교체). 평문 키는 반환값으로만 존재한다."""
    key = secrets.token_urlsafe(32)
    with closing(sqlite.connect()) as db, db:
        db.execute(
            "INSERT OR REPLACE INTO devices (device_id, key_hash) VALUES (?, ?)",
            (device_id, _hash(key)),
        )
    return key


def device_auth(x_api_key: str | None = Header(None)) -> str:
    """X-API-Key → device_id. 실패 시 401."""
    if x_api_key:
        h = _hash(x_api_key)
        with closing(sqlite.connect()) as db:
            row = db.execute("SELECT device_id, key_hash FROM devices WHERE key_hash=?", (h,)).fetchone()
        if row and hmac.compare_digest(row[1], h):
            return row[0]
    raise HTTPException(401, "invalid api key")

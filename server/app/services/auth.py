"""사용자 인증: scrypt 비밀번호, JWT access, 회전하는 refresh 토큰, 로그인 실패 잠금.

# ponytail: 잠금 키는 username|IP. Docker 브리지 뒤에선 IP가 모두 같아 사실상 username 기준
  (공격자가 특정 계정을 15분 잠글 수는 있음). 내부망/Tailscale 전용이라 수용, 필요 시 IP 단독 제한 추가.
"""
import hashlib
import hmac
import secrets
import time
from contextlib import closing

import jwt
from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite

ROLES = ("admin", "viewer")
MIN_PASSWORD_LEN = 10
_SCRYPT = dict(n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024)


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT).hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(got, bytes.fromhex(h))


# 없는 사용자도 같은 연산량을 쓰게 해 응답 시간으로 계정 존재 여부가 드러나지 않게 한다
_DUMMY = hash_password("dummy-password")


def create_user(username: str, password: str, role: str) -> None:
    """사용자 생성(이미 있으면 비밀번호/역할 교체, 기존 refresh 토큰 폐기)."""
    if role not in ROLES:
        raise ValueError(f"role은 {ROLES} 중 하나")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상")
    with closing(sqlite.connect()) as db, db:
        db.execute(
            "INSERT INTO users (username, pw_hash, role) VALUES (?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash, role=excluded.role",
            (username, hash_password(password), role),
        )
        db.execute("DELETE FROM refresh_tokens WHERE username=?", (username,))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _secret() -> str:
    s = get_settings().jwt_secret
    if len(s) < 32:
        raise HTTPException(503, "auth not configured (JWT_SECRET 32자 이상 필요)")
    return s


def _issue(db, username: str, role: str, now: float) -> dict:
    c = get_settings()
    access = jwt.encode(
        {"sub": username, "role": role, "iat": int(now), "exp": int(now) + c.access_ttl_s}, _secret(), "HS256"
    )
    refresh = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO refresh_tokens (token_hash, username, expires_at) VALUES (?,?,?)",
        (_sha(refresh), username, int(now) + c.refresh_ttl_s),
    )
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": c.access_ttl_s}


def login(username: str, password: str, ip: str, now: float | None = None) -> dict:
    now = now or time.time()
    c = get_settings()
    _secret()
    key = f"{username.lower()}|{ip}"
    with closing(sqlite.connect()) as db, db:
        row = db.execute("SELECT fails, locked_until FROM login_attempts WHERE key=?", (key,)).fetchone()
        fails, locked_until = row or (0, 0)
        if locked_until > now:
            raise HTTPException(429, "too many failed attempts", {"Retry-After": str(int(locked_until - now) + 1)})
        user = db.execute("SELECT pw_hash, role FROM users WHERE username=?", (username,)).fetchone()
        ok = verify_password(password, user[0] if user else _DUMMY)
        if not (user and ok):
            fails += 1
            lock = now + c.login_lock_s if fails >= c.login_max_fails else 0
            db.execute(
                "INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)", (key, 0 if lock else fails, lock)
            )
            db.commit()  # 예외로 with db가 롤백하기 전에 실패 횟수를 확정
            raise HTTPException(401, "invalid username or password")
        db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
        return _issue(db, username, user[1], now)


def refresh(token: str, now: float | None = None) -> dict:
    """refresh 토큰 회전. 이미 폐기된 토큰의 재사용은 탈취로 보고 해당 사용자의 모든 토큰을 폐기한다."""
    now = now or time.time()
    _secret()
    with closing(sqlite.connect()) as db, db:
        row = db.execute(
            "SELECT username, expires_at, revoked FROM refresh_tokens WHERE token_hash=?", (_sha(token),)
        ).fetchone()
        if not row:
            raise HTTPException(401, "invalid refresh token")
        username, exp, revoked = row
        if revoked:
            db.execute("DELETE FROM refresh_tokens WHERE username=?", (username,))
            db.commit()  # 예외로 with db가 롤백하기 전에 확정
            raise HTTPException(401, "refresh token reused")
        user = db.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        if exp <= now or not user:
            raise HTTPException(401, "invalid refresh token")
        db.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=?", (_sha(token),))
        db.execute("DELETE FROM refresh_tokens WHERE expires_at <= ?", (int(now),))  # 만료분 청소
        return _issue(db, username, user[0], now)


def logout(token: str) -> None:
    with closing(sqlite.connect()) as db, db:
        db.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=?", (_sha(token),))


class User(BaseModel):
    username: str
    role: str


def current_user(authorization: str | None = Header(None)) -> User:
    """Authorization: Bearer <access> → User. 역할은 토큰이 아니라 DB 기준(역할 변경/삭제가 즉시 반영)."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token", {"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token", {"WWW-Authenticate": "Bearer"})
    with closing(sqlite.connect()) as db:
        row = db.execute("SELECT role FROM users WHERE username=?", (claims["sub"],)).fetchone()
    if not row:
        raise HTTPException(401, "user not found", {"WWW-Authenticate": "Bearer"})
    return User(username=claims["sub"], role=row[0])


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

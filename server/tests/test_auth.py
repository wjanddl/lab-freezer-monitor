"""인증 테스트: 로그인/me/refresh 회전/재사용 탐지/잠금/만료/역할."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import auth

PW = "long-enough-pw"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("JWT_SECRET", "t" * 40)
    get_settings.cache_clear()
    auth.create_user("kim", PW, "admin")
    yield TestClient(app)
    get_settings.cache_clear()


def login(c, pw=PW, user="kim"):
    return c.post("/api/v1/auth/login", json={"username": user, "password": pw})


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_login_me_and_bad_credentials(c):
    r = login(c)
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    assert c.get("/api/v1/auth/me", headers=bearer(r.json()["access_token"])).json() == {"username": "kim", "role": "admin"}
    assert login(c, "wrong-password").status_code == 401
    assert login(c, user="nobody").status_code == 401  # 존재 여부를 구분하지 않음
    assert c.get("/api/v1/auth/me").status_code == 401


def test_password_is_hashed_and_min_length(c):
    assert auth.verify_password(PW, auth.hash_password(PW)) and not auth.verify_password("x", auth.hash_password(PW))
    with pytest.raises(ValueError):
        auth.create_user("a", "short", "admin")
    with pytest.raises(ValueError):
        auth.create_user("a", PW, "root")


def test_refresh_rotates_and_reuse_revokes_all(c):
    first = login(c).json()
    second = c.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    assert second["refresh_token"] != first["refresh_token"]
    # 이미 쓴 토큰 재사용 → 401 + 그 사용자의 모든 refresh 폐기
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh(c):
    t = login(c).json()
    assert c.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 200
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_lockout_after_max_fails_then_expires(c):
    for _ in range(5):
        assert login(c, "bad-password-x").status_code == 401
    r = login(c)  # 올바른 비밀번호여도 잠금 중
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # 잠금 시간이 지나면 다시 가능
    assert auth.login("kim", PW, "testclient", now=time.time() + 901)["access_token"]


def test_expired_and_forged_tokens_rejected(c):
    now = int(time.time())
    expired = jwt.encode({"sub": "kim", "iat": now - 7200, "exp": now - 3600}, "t" * 40, "HS256")
    forged = jwt.encode({"sub": "kim", "exp": now + 3600}, "other-secret-other-secret-other-secret", "HS256")
    for t in (expired, forged):
        assert c.get("/api/v1/auth/me", headers=bearer(t)).status_code == 401


def test_unconfigured_secret_returns_503(c, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    get_settings.cache_clear()
    assert login(c).status_code == 503

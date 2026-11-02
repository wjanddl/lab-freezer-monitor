from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.services import auth

router = APIRouter(prefix="/api/v1/auth")


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/login")
def login(body: LoginIn, request: Request):
    return auth.login(body.username, body.password, auth.client_ip(request))


@router.post("/refresh")
def refresh(body: RefreshIn):
    return auth.refresh(body.refresh_token)


@router.post("/logout")
def logout(body: RefreshIn):
    auth.logout(body.refresh_token)
    return {"ok": True}


@router.get("/me", response_model=auth.User)
def me(user: auth.User = Depends(auth.current_user)):
    return user

import json
from contextlib import closing

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError

from app.db import sqlite
from app.models.alert_settings import AlertSettings
from app.services import alert_settings
from app.services.auth import require_admin

router = APIRouter(prefix="/api/v1/settings")


@router.get("", response_model=AlertSettings, dependencies=[Depends(require_admin)])
def get_alert_settings():
    with closing(sqlite.connect()) as db:
        return alert_settings.load(db)


@router.put("", response_model=AlertSettings, dependencies=[Depends(require_admin)])
def put_alert_settings(body: dict = Body(...)):
    """보낸 항목만 덮어쓴다(나머지는 현재 값 유지). 알 수 없는 항목/잘못된 값은 422."""
    with closing(sqlite.connect()) as db:
        old = alert_settings.load(db)
        try:
            new = AlertSettings(**{**old.model_dump(), **body})
        except ValidationError as e:
            raise HTTPException(422, json.loads(e.json()))
        alert_settings.save(db, new, old)
    return new

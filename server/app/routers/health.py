from fastapi import APIRouter

from app.db import influx

router = APIRouter()


@router.get("/health")
async def health():
    ok = await influx.ping()
    return {"status": "ok" if ok else "degraded", "influx": ok}

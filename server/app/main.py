import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, dashboard, health, readings, settings
from app.services import monitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor.run_forever())  # 무응답 판정/재알림 주기 작업
    yield
    task.cancel()


app = FastAPI(title="Freezer Monitor", lifespan=lifespan)
if origins := [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]:
    # 인증은 Authorization 헤더(쿠키 아님)라 credentials 불필요
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(readings.router)
app.include_router(settings.router)
app.include_router(auth.router)
app.include_router(dashboard.router)

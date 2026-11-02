import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import auth, health, readings, settings
from app.services import monitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor.run_forever())  # 무응답 판정/재알림 주기 작업
    yield
    task.cancel()


app = FastAPI(title="Freezer Monitor", lifespan=lifespan)
app.include_router(health.router)
app.include_router(readings.router)
app.include_router(settings.router)
app.include_router(auth.router)

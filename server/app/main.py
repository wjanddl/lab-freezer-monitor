import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    """웹 대시보드(정적 페이지 1장). 페이지 자체는 공개, 데이터는 로그인(JWT) 후 API로 받는다."""
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")

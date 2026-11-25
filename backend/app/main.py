import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .db import SessionLocal
from .deps import client_ip, limiter
from .routers import admin, admin_devices, agent_api, auth, customer, payments, public
from .services import scheduler, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("gat")
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.ensure_dirs()
    from . import seed
    with SessionLocal() as db:
        seed.run(db)
    if settings.SECRET_KEY_IS_EPHEMERAL:
        log.warning("SECRET_KEY 환경변수가 없어 임시 키를 사용합니다. 재시작 시 로그인 세션과 암호화된 설정을 읽을 수 없습니다.")
    if settings.RUN_SCHEDULER:
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Google Auto Tester API", version=VERSION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and settings.ENV != "test" and not path.startswith("/api/agent/"):
        if not limiter.allow(f"all:{client_ip(request)}", settings.RATE_LIMIT_PER_MIN):
            return JSONResponse({"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."}, status_code=429)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not path.startswith("/api/docs"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob: https://play-lh.googleusercontent.com; font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' https://js.tosspayments.com; frame-src https://*.tosspayments.com; "
            "connect-src 'self' https://*.tosspayments.com; frame-ancestors 'none'")
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health():
    """Railway 헬스체크: DB 연결과 저장소 쓰기 가능 여부를 확인한다."""
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {exc.__class__.__name__}") from exc
    return {"status": "ok", "version": VERSION, "storage_writable": os.access(storage.root(), os.W_OK)}


for module in (auth, public, customer, payments, agent_api, admin, admin_devices):
    app.include_router(module.router)


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(rest: str):
    raise HTTPException(404, "존재하지 않는 API입니다.")


DIST = os.path.abspath(settings.FRONTEND_DIST)
if os.path.isdir(os.path.join(DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """프론트엔드(SPA) 제공. 실제 파일이 있으면 그 파일, 없으면 index.html."""
    index = os.path.join(DIST, "index.html")
    if not os.path.isfile(index):
        return JSONResponse({"detail": "frontend not built", "api_docs": "/api/docs"}, status_code=200)
    candidate = os.path.realpath(os.path.join(DIST, path))
    if path and candidate.startswith(DIST + os.sep) and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db, queue
from app.account.router import router as account_router
from app.auth.router import router as auth_router
from app.config import settings
from app.consult.router import router as consult_router
from app.files.router import router as files_router
from app.project.router import router as project_router
from app.shared.errors import (
    AppError,
    app_error_handler,
    error_body,
    http_error_handler,
    validation_error_handler,
)
from app.shared.request_guards import BodyLimit, CatchAll
from app.vendor.router import router as vendor_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await db.engine.dispose()
    await queue.redis.aclose()


# API 문서(/docs, /openapi.json)는 운영에서는 닫는다. 웹 타입 생성은 로컬·CI에서 한다.
_public_docs = settings.app_env != "production"

app = FastAPI(
    title="믿집 API",
    version="0.1.0",
    root_path=settings.api_root_path,
    lifespan=lifespan,
    docs_url="/docs" if _public_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _public_docs else None,
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)

# 기능 router는 한 줄에 하나씩, 이름 순으로 더한다 (여러 사람이 동시에 더해도 충돌이 덜 나게).
ROUTERS = [
    account_router,
    auth_router,
    consult_router,
    files_router,
    project_router,
    vendor_router,
]
for r in ROUTERS:
    app.include_router(r)

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def check_origin(request: Request, call_next):
    """다른 사이트가 로그인한 사람의 쿠키로 상태를 바꾸지 못하게 Origin을 확인한다 (SameSite=Lax와 함께)."""
    origin = request.headers.get("origin")
    if request.method in _UNSAFE and origin and origin not in settings.origins:
        return JSONResponse(
            error_body("bad_origin", "허용하지 않은 주소에서 온 요청이에요."), status_code=403
        )
    return await call_next(request)


# 바깥부터: CatchAll(처리 못 한 오류 → 같은 모양) → BodyLimit(본문 크기) → check_origin → 기능 router
app.add_middleware(BodyLimit)
app.add_middleware(CatchAll)


@app.get("/health/live")
async def live() -> dict[str, str]:
    """프로세스가 떠 있는지만 본다. 컨테이너 healthcheck용."""
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    """DB와 Redis에 실제로 붙는지 본다. 하나라도 안 되면 503."""
    checks: dict[str, str] = {}
    for name, check in (("db", db.ping), ("redis", queue.ping)):
        try:
            await check()
            checks[name] = "ok"
        except (OSError, TimeoutError, SQLAlchemyError, RedisError) as exc:
            # 연결 오류는 종류 이름만 돌려준다 (접속 정보는 응답에 넣지 않는다)
            checks[name] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "error", "checks": checks},
        status_code=200 if ok else 503,
    )

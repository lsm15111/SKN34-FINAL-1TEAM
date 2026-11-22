import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db, queue
from app.account.router import router as account_router
from app.agent import llm
from app.assistant.router import router as assistant_router
from app.assistant.router import vendor_router as assistant_vendor_router
from app.auth.router import router as auth_router
from app.chat.router import router as ai_router
from app.config import settings
from app.files.router import router as files_router
from app.guest.router import router as guest_router
from app.guest.router import rule_router as guest_rule_router
from app.notify.router import router as notify_router
from app.project.router import router as project_router
from app.quote.router import router as quote_router
from app.realtime.router import router as realtime_router
from app.report.router import router as report_router
from app.review.router import router as review_router
from app.schedule.router import router as schedule_router
from app.shared.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    validation_error_handler,
)
from app.shared.request_guards import BodyLimit, CatchAll, OriginGuard, SecurityHeaders
from app.thread.router import router as thread_router
from app.v2.router import router as v2_router
from app.vendor.router import router as vendor_router
from app.visit.router import router as visit_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # LLM SDK를 작업 스레드에서 미리 불러온다(첫 LLM 턴이 늦은 import로 멈추지 않게, 시작은 막지 않음)
    warm = asyncio.create_task(asyncio.to_thread(llm.warm))
    yield
    warm.cancel()
    await db.engine.dispose()
    await queue.redis.aclose()


# API 문서(/docs, /openapi.json)는 로컬 · 테스트에서만 연다(스테이징 · 운영은 닫음).
# 웹 타입 생성은 app.openapi()를 바로 불러서(로컬 · CI) 문서 경로가 없어도 된다.
_public_docs = settings.app_env in ("local", "test")

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
    ai_router,
    assistant_router,
    assistant_vendor_router,
    auth_router,
    files_router,
    guest_router,
    guest_rule_router,
    notify_router,
    project_router,
    quote_router,
    realtime_router,
    report_router,
    review_router,
    schedule_router,
    thread_router,
    v2_router,
    vendor_router,
    visit_router,
]
for r in ROUTERS:
    app.include_router(r)

# 바깥부터: SecurityHeaders(응답 보안 머리) → CatchAll(처리 못 한 오류 → 같은 모양) → BodyLimit(본문 크기)
#          → OriginGuard(출처: Origin · Sec-Fetch-Site · Referer, /stream · WebSocket 포함) → 기능 router
# 모두 순수 ASGI라 나눠 오는 본문의 413 · SSE 흐름이 그대로 간다(BaseHTTPMiddleware를 쓰지 않는다).
app.add_middleware(OriginGuard)
app.add_middleware(BodyLimit)
app.add_middleware(CatchAll)
app.add_middleware(SecurityHeaders)


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

"""요청 입구 보호 (ASGI 미들웨어 두 개).

- BodyLimit: 경로별 본문 크기 한도. Content-Length가 크면 읽기 전에 413, 나눠 오는 본문은 세다가 넘으면 413.
  FastAPI는 인증보다 본문 읽기를 먼저 하므로, 로그인 안 한 사람의 큰 본문도 여기서 막는다.
- CatchAll: 처리하지 못한 오류를 같은 오류 모양으로 바꾼다. DB · 디스크 연결 문제는 503, 나머지는 500.
  로그에는 오류 종류와 위치만 남긴다(메시지에 이메일 같은 값이 섞일 수 있어서).
"""

import logging
import traceback

from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.errors import error_body

log = logging.getLogger(__name__)
MB = 1024 * 1024

# 경로별 본문 한도. 파일을 받는 경로가 생기면 그 경로만 여기에 더한다 (예: "/files": 21 * MB). 나머지는 1MB.
LIMITS: dict[str, int] = {}
DEFAULT_LIMIT = 1 * MB


def _route_path(scope: Scope) -> str:
    path, root = scope.get("path", ""), scope.get("root_path", "")
    return path[len(root) :] if root and path.startswith(root) else path


class _TooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(413)


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = LIMITS.get(_route_path(scope), DEFAULT_LIMIT)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            await JSONResponse(error_body("too_large", "보낸 내용이 너무 커요."), 413)(
                scope, receive, send
            )
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise _TooLarge()  # FastAPI가 HTTPException으로 그대로 올려 413이 된다
            return msg

        await self.app(scope, counted, send)


_UNAVAILABLE = (OperationalError, ConnectionError, TimeoutError, OSError)


class CatchAll:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, receive, tracked)
        except Exception as exc:  # noqa: BLE001 - 모든 처리 못 한 오류를 한 모양으로
            where = "".join(traceback.format_tb(exc.__traceback__, limit=-3)).strip()
            log.error(
                "처리하지 못한 오류 %s %s: %s\n%s",
                scope["method"],
                _route_path(scope),
                type(exc).__name__,
                where,
            )
            if started:
                return
            down = isinstance(exc, _UNAVAILABLE) or (
                isinstance(exc, DBAPIError) and exc.connection_invalidated
            )
            body = (
                error_body("unavailable", "잠시 서비스를 쓸 수 없어요. 조금 뒤 다시 해 주세요.")
                if down
                else error_body("server_error", "잠시 문제가 생겼어요. 다시 해 주세요.")
            )
            await JSONResponse(body, 503 if down else 500)(scope, receive, send)

"""요청 입구 보호 (ASGI 미들웨어 네 개).

- BodyLimit: 경로별 본문 크기 한도. Content-Length가 크면 읽기 전에 413, 나눠 오는 본문은 세다가 넘으면 413.
  FastAPI는 인증보다 본문 읽기를 먼저 하므로, 로그인 안 한 사람의 큰 본문도 여기서 막는다.
  경로에 id가 들어가는 곳은 무늬(`/threads/{id}/messages`)로 맞춘다.
- OriginGuard: 쿠키로 상태를 바꾸는 요청(POST 등)과 실시간 줄기(GET /stream)가 우리 화면에서 왔는지 본다.
  Origin이 있으면 허용 목록, 없으면 Sec-Fetch-Site(same-origin만), 그것도 없으면 Referer로 본다.
  셋 다 없으면 브라우저가 아닌 요청(curl · 서버끼리)이라 통과시킨다. 지금 브라우저는 늘 Origin이나
  Sec-Fetch-Site를 보내고, 다른 사이트의 공격은 브라우저를 거쳐야 하기 때문이다(Go net/http와 같은 판단).
- SecurityHeaders: API 응답의 기본 보안 머리. 경로가 이미 정한 값(파일 내려받기 · 줄기)은 그대로 둔다.
- CatchAll: 처리하지 못한 오류를 같은 오류 모양으로 바꾼다. DB · 디스크 연결 문제와 DB 풀 기다림 시간 초과는
  503(Retry-After), 나머지는 500. 로그에는 오류 종류와 위치만 남긴다(메시지에 이메일 같은 값이 섞일 수 있어서).
"""

import logging
import re
import traceback
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.shared.errors import error_body

log = logging.getLogger(__name__)
KB = 1024
MB = 1024 * KB

# 경로별 본문 한도: 사진 10MB · 도면 20MB · 사업자등록증 10MB에 multipart 머리 몫을 더한 값. 나머지 JSON은 1MB.
# {이름}은 id 한 칸(빗금 없는 글자)에 맞는다. 받는 경로가 생기면 한 줄씩 더한다.
LIMITS: dict[str, int] = {
    "/ai/turns": 16 * KB,  # AI 칸 질문(글 + 보던 화면). 사진은 받지 않는다
    "/auth/vendor-signup": 11 * MB,
    "/files": 21 * MB,
    "/guest/standard": 4 * KB,  # 로그인 없는 표준견적서 계산 (api.md 1장)
    "/threads/{id}/messages": 8 * KB,  # 채팅 글 1,000자(\u 이스케이프여도 6KB) + 칸. 사진은 /files
    "/v2/ask": 2 * MB,  # AI 상담: 사진 2장(base64)까지
}
DEFAULT_LIMIT = 1 * MB


def _compile(limits: dict[str, int]) -> tuple[dict[str, int], list[tuple[re.Pattern[str], int]]]:
    exact: dict[str, int] = {}
    shaped: list[tuple[re.Pattern[str], int]] = []
    for path, n in limits.items():
        if "{" not in path:
            exact[path] = n
            continue
        parts = re.split(r"\{[^/{}]+\}", path)
        shaped.append((re.compile("[^/]+".join(re.escape(p) for p in parts)), n))
    return exact, shaped


_EXACT, _SHAPED = _compile(LIMITS)


def limit_for(path: str) -> int:
    """그 경로의 본문 한도. 끝 빗금은 떼고 본다(`/files/`도 `/files`와 같게)."""
    path = path.rstrip("/") or "/"
    if path in _EXACT:
        return _EXACT[path]
    for pattern, n in _SHAPED:
        if pattern.fullmatch(path):
            return n
    return DEFAULT_LIMIT


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
        limit = limit_for(_route_path(scope))
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


UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# GET이지만 쿠키로 오래 열려 있는 연결(SSE 실시간 줄기)도 연결할 때 출처를 본다 (security-04 규칙 2)
STREAM_PREFIXES = ("/stream",)


def _origin_of(url: str) -> str:
    try:
        u = urlsplit(url)
    except ValueError:
        return ""
    return f"{u.scheme.lower()}://{u.netloc.lower()}" if u.scheme and u.netloc else ""


def origin_ok(headers: Headers, allowed: set[str]) -> bool:
    """허용한 화면에서 온 요청인지. 'Origin: null' · 다른 사이트 · 같은 사이트의 다른 주소는 거절한다."""
    origin = headers.get("origin")
    if origin is not None:
        return origin in allowed
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site.lower() == "same-origin"
    referer = headers.get("referer")
    if referer:
        return _origin_of(referer) in allowed
    return True  # 브라우저가 아닌 요청: 다른 사이트가 사용자 쿠키를 실어 보낼 수 없다


def _guarded(scope: Scope) -> bool:
    if scope["type"] == "websocket":
        return True  # 연결(업그레이드)마다 본다. 지금은 쓰지 않지만 생기면 바로 막히게
    method = scope["method"]
    return method in UNSAFE or (method == "GET" and _route_path(scope).startswith(STREAM_PREFIXES))


class OriginGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not _guarded(scope):
            await self.app(scope, receive, send)
            return
        if origin_ok(Headers(scope=scope), settings.origins):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})  # 서버가 403으로 거절한다
            return
        await JSONResponse(
            error_body("bad_origin", "허용하지 않은 주소에서 온 요청이에요."), status_code=403
        )(scope, receive, send)


# API 응답마다 붙인다 (OWASP REST 보안 머리). 화면(Next)의 머리는 frontend/proxy.ts가 맡는다.
# 경로가 이미 정한 값은 그대로 둔다: 파일 내려받기(private, no-store · sandbox) · 줄기(no-cache, no-transform)
HEADERS: tuple[tuple[str, str], ...] = (
    ("x-content-type-options", "nosniff"),
    ("cache-control", "no-store"),
    ("content-security-policy", "default-src 'none'; frame-ancestors 'none'"),
    # CSP를 따로 정한 파일 응답도 다른 사이트 틀 안에는 못 들어가게 (우리 화면 틀은 됨)
    ("x-frame-options", "SAMEORIGIN"),
    ("cross-origin-resource-policy", "same-origin"),
    ("referrer-policy", "no-referrer"),
)
# API 문서 화면(Swagger)은 CDN 스크립트를 불러서 CSP를 붙이지 않는다. 운영에서는 닫혀 있다
NO_CSP_PREFIXES = ("/docs",)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = _route_path(scope).startswith(NO_CSP_PREFIXES)

        async def with_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                msg.setdefault("headers", [])
                headers = MutableHeaders(scope=msg)
                for name, value in HEADERS:
                    if not (docs and name == "content-security-policy"):
                        headers.setdefault(name, value)
            await send(msg)

        await self.app(scope, receive, with_headers)


# PoolTimeoutError: DB 풀에서 db_pool_timeout초 안에 빈 연결을 못 얻음(넘침). 내장 TimeoutError와 다른 종류다
_UNAVAILABLE = (OperationalError, ConnectionError, TimeoutError, OSError, PoolTimeoutError)


def retry_after() -> dict[str, str]:
    return {"Retry-After": str(settings.busy_retry_after)}


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
            headers = retry_after() if down else None
            await JSONResponse(body, 503 if down else 500, headers=headers)(scope, receive, send)

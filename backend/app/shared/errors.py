"""오류 응답 모양을 하나로 맞춘다: {"error": {"code", "message", "fields"?}}.

code는 화면이 분기에 쓰는 영어 이름, message는 그대로 보여 줘도 되는 한국어 문장이다.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        fields: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers
        self.fields = fields  # 칸별 오류 [{"loc": [칸 이름], "msg": 문장}] (빠진 칸 여러 개)


def error_body(code: str, message: str, fields: list[dict] | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return {"error": body}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        error_body(exc.code, exc.message, exc.fields), status_code=exc.status, headers=exc.headers
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # 입력값은 응답에 되돌려 보내지 않는다 (비밀번호 · 연락처가 섞일 수 있음)
    fields = [
        {
            "loc": [str(p) for p in e.get("loc", ()) if p != "body"],
            "msg": str(e.get("msg", "")).removeprefix("Value error, "),
        }
        for e in exc.errors()
    ]
    return JSONResponse(
        error_body("invalid", "입력한 내용을 확인해 주세요.", fields), status_code=422
    )


# FastAPI · Starlette가 직접 내는 오류(없는 주소, 안 되는 방법, 너무 큰 본문, 못 읽는 본문)도 같은 모양으로
_HTTP = {
    400: ("bad_request", "요청을 읽지 못했어요."),
    404: ("not_found", "찾을 수 없어요."),
    405: ("method_not_allowed", "이 방법으로는 요청할 수 없어요."),
    413: ("too_large", "보낸 내용이 너무 커요."),
}


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP.get(exc.status_code, ("http_error", "요청을 처리하지 못했어요."))
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)


# ---- v3 오류 코드 목록 (api.md 0장). 화면은 code로 나누고 message는 그대로 보여 준다 ----
# 기능 service는 여기 이름을 쓴다. 기본 문장은 상황에 맞게 바꿔도 되지만 code는 바꾸지 않는다.
CODES: dict[str, tuple[int, str]] = {
    # 권한 (남의 것은 있는지도 알리지 않는다)
    "login_required": (401, "로그인해 주세요."),
    "forbidden": (403, "이 기능을 쓸 권한이 없어요."),
    "not_found": (404, "찾을 수 없어요."),
    # 상태 다툼 409
    "stale": (409, "그사이 상태가 바뀌었어요. 새로 불러올게요."),
    "already": (409, "이미 했어요."),
    "slots_full": (409, "3곳까지 담을 수 있어요. 하나를 빼면 담을 수 있어요."),
    "slot_taken": (409, "방금 다른 고객이 골랐어요. 다른 일정을 골라 주세요."),
    "expired": (409, "기한이 지났어요."),
    "locked": (409, "실측을 요청한 뒤라 고칠 수 없어요."),
    "read_only": (409, "읽기만 되는 대화예요."),
    "paper_unsupported": (409, "이 업체는 고른 벽지를 하지 않아요."),
    "no_estimate": (409, "가견적이 준비 중인 업체예요."),
    "blocked_retry": (409, "두 번 요청했지만 답이 없던 업체라 이 공사에는 담을 수 없어요."),
    "in_progress": (409, "같은 요청을 처리하고 있어요. 잠시 뒤에 다시 해 주세요."),
    # 입력 · 한도
    "invalid": (422, "입력한 내용을 확인해 주세요."),
    "too_large": (413, "보낸 내용이 너무 커요."),
    "too_many_attempts": (429, "요청이 너무 많아요. 잠시 뒤에 다시 해 주세요."),
    # 0단계 뼈대: 계약(모양)만 있고 아직 동작하지 않는 길
    "not_ready": (501, "아직 준비 중이에요."),
}


def app_error(code: str, message: str | None = None, **kw) -> AppError:
    """CODES의 상태 번호와 기본 문장으로 AppError를 만든다."""
    status, default = CODES[code]
    return AppError(status, code, message or default, **kw)


def not_ready() -> AppError:
    """0단계 router 뼈대가 내는 501 {"error": {"code": "not_ready", ...}}."""
    return app_error("not_ready")

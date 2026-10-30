"""오류 응답 모양을 하나로 맞춘다: {"error": {"code", "message", "fields"?}}.

code는 화면이 분기에 쓰는 영어 이름, message는 그대로 보여 줘도 되는 한국어 문장이다.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def error_body(code: str, message: str, fields: list[dict] | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return {"error": body}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        error_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers
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

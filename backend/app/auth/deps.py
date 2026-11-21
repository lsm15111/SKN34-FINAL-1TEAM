"""세션 쿠키 읽기 · 쓰기와 역할 검사. 로그인이 필요한 기능은 모두 여기 것을 쓴다.

응답이 오래 가는 경로(SSE 턴)는 *_short를 쓴다. get_session(요청 세션)은 FastAPI가 응답을 다 보낸 뒤에 닫아서,
로그인 확인 SELECT 하나로 DB 연결을 턴 내내 트랜잭션 연 채 쥐기 때문이다(동시 턴 10개면 풀 10개가 바닥남).
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.models import User
from app.config import settings
from app.db import SessionLocal, get_session
from app.shared.errors import AppError


async def current_user_optional(
    request: Request, s: AsyncSession = Depends(get_session)
) -> User | None:
    token = request.cookies.get(settings.session_cookie)
    return await service.user_from_token(s, token) if token else None


async def current_user_short(request: Request) -> User | None:
    """current_user_optional과 같은 확인(만료 · 정지, 마지막 사용 시각 쓰기)을 짧은 세션으로 하고 바로 닫는다."""
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    async with SessionLocal() as s:
        return await service.user_from_token(s, token)


async def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise AppError(401, "login_required", "로그인해 주세요.")
    return user


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden", "이 기능을 쓸 권한이 없어요.")
        return user

    return dep


def require_role_short(*roles: str) -> Callable[..., Awaitable[User]]:
    """require_role과 같은 검사(401 · 403)를 짧은 세션으로. 스트림을 열기 전에 DB 연결을 돌려준다."""

    async def dep(user: User | None = Depends(current_user_short)) -> User:
        if user is None:
            raise AppError(401, "login_required", "로그인해 주세요.")
        if user.role not in roles:
            raise AppError(403, "forbidden", "이 기능을 쓸 권한이 없어요.")
        return user

    return dep


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,  # 화면 스크립트가 읽지 못하게
        secure=settings.is_https,
        samesite="lax",  # 다른 사이트에서 보낸 POST에는 쿠키가 안 붙는다
        path="/",
    )

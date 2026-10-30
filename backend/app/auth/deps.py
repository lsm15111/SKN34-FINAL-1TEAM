"""세션 쿠키 읽기 · 쓰기와 역할 검사. 로그인이 필요한 기능은 모두 여기 것을 쓴다."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.models import User
from app.config import settings
from app.db import get_session
from app.shared.errors import AppError


async def current_user_optional(
    request: Request, s: AsyncSession = Depends(get_session)
) -> User | None:
    token = request.cookies.get(settings.session_cookie)
    return await service.user_from_token(s, token) if token else None


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

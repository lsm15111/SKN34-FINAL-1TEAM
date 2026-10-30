from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.deps import current_user, set_session_cookie
from app.auth.models import User
from app.auth.schemas import LoginIn, MeOut, MePatch, SignupIn
from app.config import settings
from app.db import get_session
from app.shared.ratelimit import client_ip

router = APIRouter(tags=["회원"])


@router.post("/auth/signup", status_code=201, response_model=MeOut, summary="일반 회원가입")
async def signup(
    data: SignupIn, request: Request, response: Response, s: AsyncSession = Depends(get_session)
) -> MeOut:
    user, token = await service.signup_customer(s, data, client_ip(request))
    set_session_cookie(response, token)
    return await service.me(s, user)


@router.post("/auth/login", response_model=MeOut, summary="로그인")
async def login(
    data: LoginIn, request: Request, response: Response, s: AsyncSession = Depends(get_session)
) -> MeOut:
    user, token = await service.login(s, data, client_ip(request))
    set_session_cookie(response, token)
    return await service.me(s, user)


@router.post("/auth/logout", status_code=204, summary="로그아웃")
async def logout(
    request: Request, response: Response, s: AsyncSession = Depends(get_session)
) -> Response:
    await service.logout(s, request.cookies.get(settings.session_cookie))
    response.delete_cookie(
        settings.session_cookie, path="/", secure=settings.is_https, httponly=True, samesite="lax"
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut, summary="내 정보 · 권한 (화면 분기용)")
async def read_me(
    user: User = Depends(current_user), s: AsyncSession = Depends(get_session)
) -> MeOut:
    return await service.me(s, user)


@router.patch("/me", response_model=MeOut, summary="내 정보 수정")
async def patch_me(
    data: MePatch, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)
) -> MeOut:
    return await service.update_me(s, user, data)

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.account import service
from app.auth.deps import current_user
from app.auth.models import User
from app.config import settings
from app.db import get_session
from app.shared.ratelimit import client_ip

router = APIRouter(tags=["회원"])


class WithdrawIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/me/withdraw", status_code=204, summary="회원 탈퇴 (비밀번호 다시 확인)")
async def withdraw(
    data: WithdrawIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> Response:
    await service.withdraw(s, user, data.password, client_ip(request))
    response.delete_cookie(
        settings.session_cookie, path="/", secure=settings.is_https, httponly=True, samesite="lax"
    )
    response.status_code = 204
    return response

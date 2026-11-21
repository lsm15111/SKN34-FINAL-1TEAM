"""업체 기능 권한: 업체 역할이고 관리자가 승인한 업체만."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role, require_role_short
from app.auth.models import User
from app.db import SessionLocal, get_session
from app.shared.errors import AppError
from app.vendor import repository as repo


def _approved(user: User, review) -> User:
    if review is None or review[0] != "approved":
        raise AppError(403, "vendor_not_approved", "승인된 업체만 쓸 수 있어요.")
    return user


async def approved_vendor(
    user: User = Depends(require_role("vendor")), s: AsyncSession = Depends(get_session)
) -> User:
    return _approved(user, await repo.review_of(s, user.id))


_vendor_short = require_role_short("vendor")


async def approved_vendor_short(user: User = Depends(_vendor_short)) -> User:
    """approved_vendor와 같은 검사를 짧은 세션으로(SSE 턴). 스트림을 열기 전에 DB 연결을 돌려준다."""
    async with SessionLocal() as s:
        review = await repo.review_of(s, user.id)
    return _approved(user, review)

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.auth.models import User
from app.db import get_session
from app.quote import service
from app.quote.schemas import SourcingOut
from app.shared import ratelimit

router = APIRouter(tags=["가견적"])
customer_only = require_role("customer")


@router.get(
    "/projects/{project_id}/sourcing",
    response_model=SourcingOut,
    summary="가견적 후보 업체 · 받는 길 · 비용 · 출처",
)
async def sourcing(
    project_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Depends(get_session),
) -> SourcingOut:
    # 후보 설명에 LLM 유료 호출이 붙을 수 있어 사람마다 시간당 횟수를 묶는다
    await ratelimit.hit(
        ratelimit.key("sourcing", str(user.id)),
        60,
        3600,
        "업체 찾기를 너무 자주 했어요. 잠시 뒤에 다시 해 주세요.",
    )
    return await service.sourcing(s, user, project_id)

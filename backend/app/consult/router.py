from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.auth.models import User
from app.consult import service
from app.consult.schemas import ConsultIn, ConsultOut
from app.db import get_session
from app.shared import ratelimit

router = APIRouter(tags=["상담"])


@router.post("/consult/dobae", response_model=ConsultOut, summary="도배 상담 한 턴")
async def dobae_turn(
    data: ConsultIn,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> ConsultOut:
    # LLM 유료 호출이 붙는 경로라 사람마다 시간당 횟수를 묶는다
    await ratelimit.hit(
        ratelimit.key("consult", str(user.id)),
        60,
        3600,
        "상담 요청이 너무 많아요. 잠시 뒤에 다시 해 주세요.",
    )
    return await service.turn(s, user, data)

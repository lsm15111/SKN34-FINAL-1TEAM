from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.directory import service
from app.directory.schemas import OptOutIn, OptOutOut
from app.shared import ratelimit
from app.shared.clock import now_utc

router = APIRouter(tags=["외부 업체"])
DONE = "수신을 거부했어요. 믿집은 이 업체에 더 연락하지 않고, 업체 목록에서도 뺐어요."


@router.post(
    "/directory/opt-out", response_model=OptOutOut, summary="외부 업체 수신거부 (로그인 없음)"
)
async def opt_out(
    data: OptOutIn, request: Request, s: AsyncSession = Depends(get_session)
) -> OptOutOut:
    # 로그인 없이 부르는 곳이라 보낸 곳(IP)마다 횟수를 묶는다
    await ratelimit.hit(
        ratelimit.key("optout", ratelimit.client_ip(request)),
        20,
        3600,
        "요청이 너무 많아요. 잠시 뒤에 다시 해 주세요.",
    )
    await service.opt_out(s, data.token, now=now_utc())
    return OptOutOut(done=True, message=DONE)

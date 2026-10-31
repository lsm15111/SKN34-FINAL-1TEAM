import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.auth.models import User
from app.db import get_session
from app.quote import service
from app.quote.schemas import InboxItemOut, QuoteRequestIn, QuoteRequestOut, SourcingOut
from app.shared import ratelimit

router = APIRouter(tags=["가견적"])
customer_only = require_role("customer")
vendor_only = require_role("vendor")


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


@router.post(
    "/projects/{project_id}/quote-requests",
    status_code=201,
    response_model=QuoteRequestOut,
    summary="앱 업체에 가견적 요청",
)
async def create_quote_request(
    project_id: uuid.UUID,
    data: QuoteRequestIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Depends(get_session),
) -> QuoteRequestOut:
    await ratelimit.hit(
        ratelimit.key("quote-request", str(user.id)),
        30,
        3600,
        "가견적 요청을 너무 많이 보냈어요. 잠시 뒤에 다시 해 주세요.",
    )
    return await service.create_quote_request(s, user, project_id, data)


@router.get(
    "/vendor/quote-requests",
    response_model=list[InboxItemOut],
    summary="업체 받은편지함 · 받은 가견적 요청",
)
async def vendor_inbox(
    user: User = Depends(vendor_only), s: AsyncSession = Depends(get_session)
) -> list[InboxItemOut]:
    return await service.vendor_inbox(s, user)


@router.post(
    "/vendor/quote-requests/{request_id}/viewed",
    response_model=InboxItemOut,
    summary="업체가 가견적 요청을 확인",
)
async def mark_viewed(
    request_id: uuid.UUID,
    user: User = Depends(vendor_only),
    s: AsyncSession = Depends(get_session),
) -> InboxItemOut:
    return await service.mark_viewed(s, user, request_id)

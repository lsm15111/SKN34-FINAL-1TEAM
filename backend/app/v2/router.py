import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user, require_role
from app.auth.models import User
from app.calc.plan_qty import SpaceKind
from app.db import get_session
from app.shared.clock import today_seoul
from app.v2 import ask, ask_chat, case_service, preview_service, service
from app.v2 import case_schemas as cs
from app.v2 import schemas as v2
from app.v2.preview_schemas import (
    V2MaterialsOut,
    V2PlanBriefOut,
    V2PlanQtyOut,
    V2PreviewIn,
    V2PreviewOut,
)

router = APIRouter(prefix="/v2", tags=["v2"])


@router.get("/floor-plans", response_model=list[V2PlanBriefOut], summary="예시 평면도 목록")
async def plans(_: User = Depends(current_user)) -> list[V2PlanBriefOut]:
    return preview_service.list_plans()


@router.get("/floor-plans/{plan_id}/qty", response_model=V2PlanQtyOut, summary="평면도 수량")
async def plan_qty(
    plan_id: str,
    expanded: bool = True,
    kinds: list[SpaceKind] | None = Query(default=None, max_length=9),
    ceiling: bool = True,
    _: User = Depends(current_user),
) -> V2PlanQtyOut:
    return preview_service.plan_qty(plan_id, expanded, kinds, ceiling)


@router.get("/materials", response_model=V2MaterialsOut, summary="목공 자재 · 정해진 단가 항목")
async def materials(_: User = Depends(current_user)) -> V2MaterialsOut:
    return preview_service.materials()


@router.post(
    "/projects/{project_id}/preview",
    response_model=V2PreviewOut,
    summary="견적 미리 보기 (도면 · 목공 자재 · 시장 범위, 저장하지 않음)",
)
async def preview(
    project_id: uuid.UUID,
    body: V2PreviewIn,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> V2PreviewOut:
    return await preview_service.preview(s, user, project_id, body)


# ---- v2 화면 (v10 이식). 저장하지 않고 계산만 한다 ----
@router.post("/quote", response_model=v2.V2QuoteOut, summary="v2 표준견적서")
async def v2_quote(body: v2.V2QuoteIn, _: User = Depends(current_user)) -> v2.V2QuoteOut:
    return service.quote(body, today_seoul())


@router.get(
    "/market-extras",
    response_model=list[v2.V2MarketExtraOut],
    summary="v2 받은 견적 맞춰 보기 목공 추가 항목",
)
async def v2_market_extras(_: User = Depends(current_user)) -> list[v2.V2MarketExtraOut]:
    return service.market_extras()


@router.post("/plan", response_model=v2.V2PlanOut, summary="v2 예상 공정표")
async def v2_plan(body: v2.V2PlanIn, _: User = Depends(current_user)) -> v2.V2PlanOut:
    return service.plan(body, today_seoul())


@router.post("/check", response_model=v2.V2CheckOut, summary="v2 받은 견적 맞춰 보기")
async def v2_check(body: v2.V2CheckIn, _: User = Depends(current_user)) -> v2.V2CheckOut:
    return service.check(body, today_seoul())


@router.post("/estimate", response_model=v2.V2EstimateOut, summary="v2 업체 가견적")
async def v2_estimate(body: v2.V2EstimateIn, _: User = Depends(current_user)) -> v2.V2EstimateOut:
    return service.estimate(body)


@router.post("/entered", response_model=v2.V2EnteredOut, summary="v2 실측 견적서 금액")
async def v2_entered(body: v2.V2EnteredIn, _: User = Depends(current_user)) -> v2.V2EnteredOut:
    return service.entered(body)


@router.post(
    "/calc7",
    response_model=v2.V2WallOut | v2.V2TrimOut | v2.V2PaintOut,
    summary="v2 셀프 계산기",
)
async def v2_calc7(
    body: v2.V2Calc7In, _: User = Depends(current_user)
) -> v2.V2WallOut | v2.V2TrimOut | v2.V2PaintOut:
    return service.calc7(body)


@router.post("/extras-range", response_model=v2.V2ExtrasOut, summary="v2 추가 항목 범위")
async def v2_extras(body: v2.V2ExtrasIn, _: User = Depends(current_user)) -> v2.V2ExtrasOut:
    return service.extras_range(body)


@router.post("/quick-budget", response_model=v2.V2QuickOut, summary="v2 빠른 예산")
async def v2_quick(body: v2.V2QuickIn, _: User = Depends(current_user)) -> v2.V2QuickOut:
    return service.quick(body)


# 유료 LLM 길이라 고객만(가이드는 로그인한 고객만, AGENTS 4장). 업체 신청만 한 계정이 쓰지 못하게(점검 R6 B3)
@router.post("/ask", response_model=v2.V2AskOut, summary="v2 AI 상담 한 턴 시작")
async def v2_ask(body: v2.V2AskIn, user: User = Depends(require_role("customer"))) -> v2.V2AskOut:
    return await ask_chat.start(user.id, body, today_seoul())


@router.post(
    "/ask/{turn_id}", response_model=v2.V2AskOut, summary="v2 AI 상담: 화면 도구 결과 보내기"
)
async def v2_ask_resume(
    turn_id: str, body: v2.V2AskResumeIn, user: User = Depends(require_role("customer"))
) -> v2.V2AskOut:
    return await ask_chat.resume(user.id, turn_id, body)


@router.get("/ask/health", response_model=v2.V2AskHealthOut, summary="v2 AI 상태")
async def v2_ask_health(_: User = Depends(current_user)) -> v2.V2AskHealthOut:
    return ask.health()


# ---- 인테리어 한 건 저장 (고객만, 본인 것만) ----
customer = require_role("customer")


@router.get("/cases", response_model=list[cs.V2CaseItemOut], summary="내 인테리어 목록")
async def cases(
    user: User = Depends(customer), s: AsyncSession = Depends(get_session)
) -> list[cs.V2CaseItemOut]:
    return await case_service.list_mine(s, user)


@router.post(
    "/cases", response_model=cs.V2CaseOut, status_code=201, summary="인테리어 한 건 만들기"
)
async def case_create(
    body: cs.V2CaseSaveIn, user: User = Depends(customer), s: AsyncSession = Depends(get_session)
) -> cs.V2CaseOut:
    return await case_service.create(s, user, body, today_seoul())


@router.get("/cases/{case_id}", response_model=cs.V2CaseOut, summary="인테리어 한 건 열기")
async def case_get(
    case_id: uuid.UUID, user: User = Depends(customer), s: AsyncSession = Depends(get_session)
) -> cs.V2CaseOut:
    return await case_service.get(s, user, case_id)


@router.put(
    "/cases/{case_id}",
    response_model=cs.V2CaseItemOut,
    summary="인테리어 한 건 저장 (견적서 · 공정표는 서버가 다시 계산)",
)
async def case_save(
    case_id: uuid.UUID,
    body: cs.V2CaseSaveIn,
    user: User = Depends(customer),
    s: AsyncSession = Depends(get_session),
) -> cs.V2CaseItemOut:
    return await case_service.save(s, user, case_id, body, today_seoul())


@router.patch("/cases/{case_id}", response_model=cs.V2CaseItemOut, summary="인테리어 이름 바꾸기")
async def case_rename(
    case_id: uuid.UUID,
    body: cs.V2CaseTitleIn,
    user: User = Depends(customer),
    s: AsyncSession = Depends(get_session),
) -> cs.V2CaseItemOut:
    return await case_service.rename(s, user, case_id, body.title)


@router.delete("/cases/{case_id}", status_code=204, summary="인테리어 한 건 지우기")
async def case_delete(
    case_id: uuid.UUID, user: User = Depends(customer), s: AsyncSession = Depends(get_session)
) -> None:
    await case_service.delete(s, user, case_id)

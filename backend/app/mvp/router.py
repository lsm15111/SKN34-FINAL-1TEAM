import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user
from app.auth.models import User
from app.calc.plan_qty import SpaceKind
from app.db import get_session
from app.mvp import service, v2_service
from app.mvp import v2_schemas as v2
from app.mvp.schemas import (
    MvpMaterialsOut,
    MvpPlanBriefOut,
    MvpPlanQtyOut,
    MvpPreviewIn,
    MvpPreviewOut,
)
from app.shared.clock import today_seoul

router = APIRouter(prefix="/mvp", tags=["mvp"])


@router.get("/plans", response_model=list[MvpPlanBriefOut], summary="예시 평면도 목록")
async def plans(_: User = Depends(current_user)) -> list[MvpPlanBriefOut]:
    return service.list_plans()


@router.get("/plans/{plan_id}/qty", response_model=MvpPlanQtyOut, summary="평면도 수량")
async def plan_qty(
    plan_id: str,
    expanded: bool = True,
    kinds: list[SpaceKind] | None = Query(default=None, max_length=9),
    ceiling: bool = True,
    _: User = Depends(current_user),
) -> MvpPlanQtyOut:
    return service.plan_qty(plan_id, expanded, kinds, ceiling)


@router.get("/materials", response_model=MvpMaterialsOut, summary="목공 자재 · 정해진 단가 항목")
async def materials(_: User = Depends(current_user)) -> MvpMaterialsOut:
    return service.materials()


@router.post(
    "/projects/{project_id}/preview",
    response_model=MvpPreviewOut,
    summary="견적 미리 보기 (도면 · 목공 자재 · 시장 범위, 저장하지 않음)",
)
async def preview(
    project_id: uuid.UUID,
    body: MvpPreviewIn,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> MvpPreviewOut:
    return await service.preview(s, user, project_id, body)


# ---- v2 화면 (커스텀 MVP v10 이식). 저장하지 않고 계산만 한다 ----
@router.post("/v2/quote", response_model=v2.MvpV2QuoteOut, summary="v2 표준견적서")
async def v2_quote(body: v2.MvpV2QuoteIn, _: User = Depends(current_user)) -> v2.MvpV2QuoteOut:
    return v2_service.quote(body, today_seoul())


@router.get(
    "/v2/market-extras",
    response_model=list[v2.MvpV2MarketExtraOut],
    summary="v2 받은 견적 맞춰 보기 목공 추가 항목",
)
async def v2_market_extras(_: User = Depends(current_user)) -> list[v2.MvpV2MarketExtraOut]:
    return v2_service.market_extras()


@router.post("/v2/plan", response_model=v2.MvpV2PlanOut, summary="v2 예상 공정표")
async def v2_plan(body: v2.MvpV2PlanIn, _: User = Depends(current_user)) -> v2.MvpV2PlanOut:
    return v2_service.plan(body, today_seoul())


@router.post("/v2/check", response_model=v2.MvpV2CheckOut, summary="v2 받은 견적 맞춰 보기")
async def v2_check(body: v2.MvpV2CheckIn, _: User = Depends(current_user)) -> v2.MvpV2CheckOut:
    return v2_service.check(body, today_seoul())


@router.post("/v2/estimate", response_model=v2.MvpV2EstimateOut, summary="v2 업체 가견적")
async def v2_estimate(
    body: v2.MvpV2EstimateIn, _: User = Depends(current_user)
) -> v2.MvpV2EstimateOut:
    return v2_service.estimate(body)


@router.post("/v2/entered", response_model=v2.MvpV2EnteredOut, summary="v2 실측 견적서 금액")
async def v2_entered(
    body: v2.MvpV2EnteredIn, _: User = Depends(current_user)
) -> v2.MvpV2EnteredOut:
    return v2_service.entered(body)


@router.post(
    "/v2/calc7",
    response_model=v2.MvpV2WallOut | v2.MvpV2TrimOut | v2.MvpV2PaintOut,
    summary="v2 셀프 계산기",
)
async def v2_calc7(
    body: v2.MvpV2Calc7In, _: User = Depends(current_user)
) -> v2.MvpV2WallOut | v2.MvpV2TrimOut | v2.MvpV2PaintOut:
    return v2_service.calc7(body)


@router.post("/v2/extras-range", response_model=v2.MvpV2ExtrasOut, summary="v2 추가 항목 범위")
async def v2_extras(body: v2.MvpV2ExtrasIn, _: User = Depends(current_user)) -> v2.MvpV2ExtrasOut:
    return v2_service.extras_range(body)


@router.post("/v2/llm", response_model=v2.MvpV2LlmOut, summary="v2 AI 한 번 부르기")
async def v2_llm(body: v2.MvpV2LlmIn, user: User = Depends(current_user)) -> v2.MvpV2LlmOut:
    return await v2_service.ask_llm(str(user.id), body)


@router.get("/v2/llm/health", response_model=v2.MvpV2LlmHealthOut, summary="v2 AI 상태")
async def v2_llm_health(_: User = Depends(current_user)) -> v2.MvpV2LlmHealthOut:
    return v2_service.llm_health()

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user
from app.auth.models import User
from app.calc.plan_qty import SpaceKind
from app.db import get_session
from app.mvp import service
from app.mvp.schemas import (
    MvpMaterialsOut,
    MvpPlanBriefOut,
    MvpPlanQtyOut,
    MvpPreviewIn,
    MvpPreviewOut,
)

router = APIRouter(prefix="/mvp", tags=["mvp"])


@router.get("/plans", response_model=list[MvpPlanBriefOut], summary="예시 평면도 목록")
async def plans(_: User = Depends(current_user)) -> list[MvpPlanBriefOut]:
    return service.list_plans()


@router.get("/plans/{plan_id}/qty", response_model=MvpPlanQtyOut, summary="평면도 수량")
async def plan_qty(
    plan_id: str,
    expanded: bool = True,
    kinds: list[SpaceKind] | None = Query(default=None, max_length=9),
    _: User = Depends(current_user),
) -> MvpPlanQtyOut:
    return service.plan_qty(plan_id, expanded, kinds)


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

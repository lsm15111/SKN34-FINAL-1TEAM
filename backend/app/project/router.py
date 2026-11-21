import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user, require_role
from app.auth.models import User
from app.db import get_session
from app.project import service
from app.project.schemas import (
    ConditionOut,
    DiyIn,
    DiyOut,
    EmdOut,
    ProjectBody,
    ProjectCheckIn,
    ProjectCheckOut,
    ProjectOut,
)
from app.shared import ratelimit
from app.shared.clock import today_seoul
from app.shared.regions import SIDO

# v3: 손님 답 옮기기 멱등 키 (기기 답의 key, UUID 문자열). 같은 키 두 번이면 만든 공사를 200으로 돌려주고,
# 같은 키가 아직 처리 중이면 409 in_progress (dev-03, api.md 0장)
IdempotencyKey = Annotated[
    uuid.UUID | None,
    Header(alias="Idempotency-Key", description="손님 답 옮기기 멱등 키 (기기 답의 key)"),
]
# 지금 화면 몸통(ProjectCreate) 또는 v3 기본 정보(HomeInfoIn). v3에만 있는 칸이 하나라도 있으면 v3로 본다
Bodies = Annotated[
    ProjectBody,
    Body(
        description="지금 화면 몸통(ProjectCreate) 또는 v3 기본 정보(HomeInfoIn, 손님 계산과 같은 칸)."
        " emd · area_m2 같은 v3 칸이 있으면 v3로 검사해요(422 fields.loc는 칸 이름만)"
    ),
]

router = APIRouter(tags=["프로젝트"])


@router.get("/regions", summary="시 · 도 → 시 · 군 · 구 목록")
async def regions() -> list[dict]:
    return [
        {
            "id": sid,
            "name": name,
            "full": full,
            "groups": [{"label": lb, "prefix": pf, "items": items} for lb, pf, items in groups],
        }
        for sid, (name, full, groups) in SIDO.items()
    ]


@router.get(
    "/regions/{sido}/{sgg}",
    response_model=list[EmdOut],
    summary="v3 읍면동 목록 (B6 자료, 자료가 없는 시 · 군 · 구는 404)",
)
async def region_emds(sido: str, sgg: str) -> list[EmdOut]:
    return service.emds(sido, sgg)


@router.post(
    "/projects",
    status_code=201,
    response_model=ProjectOut,
    summary="프로젝트 만들기 (같은 Idempotency-Key면 200 같은 공사)",
    responses={200: {"description": "같은 Idempotency-Key로 이미 만든 공사"}},
)
async def create_project(
    response: Response,
    data: Bodies,
    idempotency_key: IdempotencyKey = None,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """손님 답 옮기기(v3 몸통 + Idempotency-Key)는 source guest, 키 없는 v3 몸통은 member, 지금 화면 몸통은 v2."""
    await ratelimit.hit(
        ratelimit.key("project", str(user.id)),
        30,
        3600,
        "프로젝트를 너무 많이 만들었어요. 잠시 뒤에 다시 해 주세요.",
    )
    out, created = await service.create_once(s, user, data, today_seoul(), idempotency_key)
    if not created:
        response.status_code = 200
    return out


@router.get(
    "/projects/{project_id}",
    response_model=ProjectOut,
    summary="프로젝트 보기 (만든 사람 · 관리자)",
)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> ProjectOut:
    return await service.get_for(s, user, project_id)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectOut,
    summary="집 정보 고치기 (실측 요청 전까지, 만든 사람만)",
)
async def update_project(
    project_id: uuid.UUID,
    data: Bodies,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """첫 실측 요청 뒤에는 409 locked (C50). 몸통 모양은 만들기와 같다."""
    return await service.update(s, user, project_id, data, today_seoul())


@router.put(
    "/projects/{project_id}/checks/{key}",
    response_model=list[ProjectCheckOut],
    summary="공사 전에 할 일 체크 켜기 · 끄기 (만든 고객만)",
)
async def set_check(
    project_id: uuid.UUID,
    key: Literal["office_report"],
    data: ProjectCheckIn,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> list[ProjectCheckOut]:
    return await service.set_check(s, user, project_id, key, data.done)


@router.put(
    "/projects/{project_id}/diy",
    response_model=DiyOut,
    summary="직접 할 일(반셀프 칩) 고치기 (만든 고객만, 빈 목록이면 '없어요')",
)
async def put_diy(
    project_id: uuid.UUID,
    data: DiyIn,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> DiyOut:
    """덮어써요. 모은 조건 칩(GET /projects/{id}/conditions)에 '직접 할 일: …'로 보여요."""
    return await service.put_diy(s, user, project_id, list(data.diy))


@router.get(
    "/projects/{project_id}/conditions",
    response_model=list[ConditionOut],
    summary="AI 상담으로 모은 조건 (만든 고객만)",
)
async def list_conditions(
    project_id: uuid.UUID,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> list[ConditionOut]:
    return await service.condition_list(s, user, project_id)


@router.delete(
    "/projects/{project_id}/conditions/{key}",
    response_model=list[ConditionOut],
    summary="모은 조건 한 칸 지우기 (만든 고객만, 지우면 AI가 다시 물어요)",
)
async def delete_condition(
    project_id: uuid.UUID,
    key: Annotated[
        str, Path(min_length=3, max_length=40, pattern=r"^[a-z_]+(?:\.[a-z_]+)?$")
    ],  # '공종.칸' 또는 공종 없는 칸(demolition)
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> list[ConditionOut]:
    return await service.delete_condition(s, user, project_id, key)

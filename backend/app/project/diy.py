"""반셀프(고객이 직접 할 일) 칩. 기본 정보 · 반셀프 갈래가 같이 쓰는 약속이에요(2026-11-21 사용자 결정).

- 표준견적서를 본 뒤 칩으로 한 번 물어요. 고객이 직접 고른 값만 둬요(에이전트 추측 · 기억 글은 넣지 않아요).
- 모은 조건(project_conditions)에 key `diy.<키>`, value `self`, trade `diy`로 둬요. 칸마다 한 줄이에요.
- '없어요'를 고르면 `diy.none`만 남겨 '물어봤음'을 표시해요(다시 묻지 않게). 칩을 고르면 `diy.none`은 지워요.
- 권한 확인 · commit은 부르는 쪽(project.service)이 해요.
"""

import uuid
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.project.models import ProjectCondition
from app.shared.ids import uuid7

DiyKey = Literal["paint", "outlet", "light", "silicone", "handle", "clean"]
DIY: dict[str, str] = {
    "paint": "페인트(문틀 · 몰딩)",
    "outlet": "콘센트 · 스위치 커버",
    "light": "조명 교체",
    "silicone": "실리콘 · 줄눈",
    "handle": "손잡이 · 문고리",
    "clean": "입주 청소",
}
TRADE = "diy"
PREFIX = "diy."
NONE_KEY = "diy.none"
SELF = "self"


async def diy_for(s: AsyncSession, project_id: uuid.UUID) -> list[str] | None:
    """고른 칩 키(DIY 순서). 아직 묻지 않았으면 None, '없어요'면 []."""
    keys = set(
        await s.scalars(
            select(ProjectCondition.key).where(
                ProjectCondition.project_id == project_id, ProjectCondition.key.like(f"{PREFIX}%")
            )
        )
    )
    if not keys:
        return None
    return [k for k in DIY if f"{PREFIX}{k}" in keys]


async def set_diy(s: AsyncSession, project_id: uuid.UUID, keys: list[str]) -> list[str]:
    """칩 덮어쓰기. 빈 목록이면 '없어요'(diy.none). 모르는 키는 버려요. 돌려주는 값은 diy_for와 같은 순서."""
    picked = [k for k in DIY if k in set(keys)]
    await s.execute(
        delete(ProjectCondition).where(
            ProjectCondition.project_id == project_id, ProjectCondition.key.like(f"{PREFIX}%")
        )
    )
    for key in [f"{PREFIX}{k}" for k in picked] or [NONE_KEY]:
        stmt = insert(ProjectCondition).values(
            id=uuid7(), project_id=project_id, trade=TRADE, key=key, value=SELF
        )
        await s.execute(
            stmt.on_conflict_do_update(
                constraint="uq_project_conditions_key",
                set_={"value": SELF, "trade": TRADE, "updated_at": func.now()},
            )
        )
    return picked

"""반셀프(고객이 직접 할 일) 칩. 기본 정보 · 반셀프 갈래가 같이 쓰는 약속이에요(2026-11-21 사용자 결정).

- 표준견적서를 본 뒤 칩으로 한 번 물어요. 고객이 직접 고른 값만 둬요(에이전트 추측 · 기억 글은 넣지 않아요).
- 모은 조건(project_conditions)에 key `diy.<키>`, value `self`, trade `diy`로 둬요. 칸마다 한 줄이에요.
- '없어요'를 고르면 `diy.none`만 남겨 '물어봤음'을 표시해요(다시 묻지 않게). 칩을 고르면 `diy.none`은 지워요.
- 권한 확인 · commit은 부르는 쪽(project.service)이 해요. 저장은 공사 행을 잠가 같은 공사의 저장끼리 줄 세워요.
"""

import uuid
from collections.abc import Iterable
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.project.models import Project, ProjectCondition
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


def picked_of(keys: Iterable[str]) -> list[str] | None:
    """모은 조건 키(diy.*) → 고른 칩 키(DIY 순서). 줄이 없으면 None(아직 안 물음), '없어요'(diy.none)면 []."""
    got = set(keys)
    if not got:
        return None
    return [k for k in DIY if f"{PREFIX}{k}" in got]


def diy_ver(picked: list[str] | None) -> str:
    """칩 지문(승인 카드 판에 붙여 화면에서 칩이 바뀌면 지난 카드로 본다): 아직 안 물음 '-', 없어요 'd', 고른 칩은
    칩 순서 번호를 붙인다('d05' = 페인트 · 입주 청소)."""
    if picked is None:
        return "-"
    return "d" + "".join(str(i) for i, k in enumerate(DIY) if k in set(picked))


async def diy_for(s: AsyncSession, project_id: uuid.UUID) -> list[str] | None:
    """고른 칩 키(DIY 순서). 아직 묻지 않았으면 None, '없어요'면 []."""
    return picked_of(
        await s.scalars(
            select(ProjectCondition.key).where(
                ProjectCondition.project_id == project_id, ProjectCondition.key.like(f"{PREFIX}%")
            )
        )
    )


async def set_diy(s: AsyncSession, project_id: uuid.UUID, keys: list[str]) -> list[str]:
    """칩 덮어쓰기. 빈 목록이면 '없어요'(diy.none). 모르는 키는 버려요. 돌려주는 값은 diy_for와 같은 순서.
    공사 행을 먼저 잠근다: 두 저장(화면 칩 · 비서 승인)이 겹쳐도 뒤 저장의 지우기가 앞 저장이 넣은 줄을 보고 지워
    두 목록이 합쳐지지 않는다(이미 잠근 트랜잭션이면 그대로 지나간다)."""
    await s.execute(select(Project.id).where(Project.id == project_id).with_for_update())
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

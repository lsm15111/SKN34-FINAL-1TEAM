"""도배 전 앞 공사 점검(선행 공정) 답. 비서 도배 전 점검 카드 · 승인 카드가 같이 쓰는 약속이에요(갈래 P2, 2026-11-24).

- 목공 · 전기 · 필름 · 바닥이 끝났는지만 물어요(업체 연결 · 견적은 하지 않아요, 고정 선 8).
- 모은 조건(project_conditions)에 key `prework.<공정>`, value 단추 값(done 끝났어요 · todo 아직이에요 · none 안 해요),
  trade `prework`로 둬요. 칸마다 한 줄이에요. 단추 값 밖의 값 · 모르는 공정은 DB CHECK가 막아요(0060).
- 고객이 카드 단추로 고른 값만 둬요(에이전트 추측 · 기억 글은 넣지 않아요). 저장은 사람이 누른 승인 카드로만 해요(고정 선 1).
- 권한 확인 · commit은 부르는 쪽이 해요. 저장은 공사 행을 잠가 같은 공사의 저장끼리 줄 세워요.
- 공정 순서는 지문(prework_ver) 자리라 새 공정은 끝에 더해요(이미 만든 승인 카드 지문이 그대로 맞게).
"""

import uuid
from collections.abc import Mapping
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.project.models import Project, ProjectCondition
from app.shared.ids import uuid7

PreworkKey = Literal["mokgong", "electric", "film", "floor"]
PreworkState = Literal["done", "todo", "none"]
PREWORK: dict[str, str] = {"mokgong": "목공", "electric": "전기", "film": "필름", "floor": "바닥"}
STATES: dict[str, str] = {"done": "끝났어요", "todo": "아직이에요", "none": "안 해요"}
PREFIX = "prework."
TRADE = "prework"
LABEL = "앞 공사"  # 모은 조건 칩 '앞 공사 · 목공: 끝났어요'


def key_of(trade: str) -> str:
    return f"{PREFIX}{trade}"


def answers_of(said: Mapping[str, str]) -> dict[str, str]:
    """모은 조건 {칸: 값} → 저장된 답 {공정: 단추 값}(공정 순서, 모르는 칸 · 값은 버려요)."""
    out = {}
    for k in PREWORK:
        v = said.get(key_of(k))
        if v in STATES:
            out[k] = v
    return out


def prework_ver(answers: Mapping[str, str]) -> str:
    """답 지문(승인 카드 판에 붙여 그사이 답이 바뀌면 지난 카드로 봐요): 'p' + 공정 순서 번호와 값 첫 글자('p0d2t')."""
    return "p" + "".join(f"{i}{answers[k][0]}" for i, k in enumerate(PREWORK) if k in answers)


def clean(answers: Mapping[str, str]) -> dict[str, str]:
    """받은 답 → 공정 순서 {공정: 단추 값}. 모르는 공정 · 단추 값 밖이면 ValueError."""
    bad = [k for k, v in answers.items() if k not in PREWORK or v not in STATES]
    if bad:
        raise ValueError(
            "앞 공사 답은 목공 · 전기 · 필름 · 바닥의 끝났어요 · 아직이에요 · 안 해요만 받아요"
        )
    return {k: answers[k] for k in PREWORK if k in answers}


async def prework_for(s: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """저장된 답 {공정: 단추 값}(공정 순서). 아직 고른 답이 없으면 빈 사전."""
    rows = await s.execute(
        select(ProjectCondition.key, ProjectCondition.value).where(
            ProjectCondition.project_id == project_id, ProjectCondition.key.like(f"{PREFIX}%")
        )
    )
    return answers_of(dict(rows.all()))


async def set_prework(
    s: AsyncSession, project_id: uuid.UUID, answers: Mapping[str, str]
) -> dict[str, str]:
    """답 덮어쓰기(준 공정만, 다른 공정 답은 그대로). 돌려주는 값은 저장한 뒤 모든 답(prework_for와 같은 꼴).
    공사 행을 먼저 잠근다(이미 잠근 트랜잭션이면 그대로 지나간다). 모르는 공정 · 값이면 ValueError."""
    got = clean(answers)
    await s.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    for k, v in got.items():
        stmt = insert(ProjectCondition).values(
            id=uuid7(), project_id=project_id, trade=TRADE, key=key_of(k), value=v
        )
        await s.execute(
            stmt.on_conflict_do_update(
                constraint="uq_project_conditions_key",
                set_={"value": v, "trade": TRADE, "updated_at": func.now()},
            )
        )
    return await prework_for(s, project_id)

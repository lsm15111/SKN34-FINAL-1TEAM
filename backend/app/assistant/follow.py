"""이어 하기(사용자 11-24 '취소도 띄워주고 취소사용자가하면 바로 이어서 면적 바꾸는것까지 띄워줘야'): 사람이 누른 승인
카드가 실행된 뒤 다음 걸음의 승인 카드를 코드가 바로 내미는 대화 줄(먼저 말 건 줄 trigger follow_up, 문장은 정해 둔 틀).

- 지금 잇는 것: 잠긴 집 정보 바꾸기. propose_home_info가 살아 있는 실측 요청에 막히면(견적서 전) 요청마다 취소 카드에
  then {kind home_info · group · fields}를 달아요(propose.need_cancel). 같은 묶음의 취소 카드가 모두 실행되고 집 정보
  잠금이 풀리면 그 fields로 집 정보 카드를 만들어 줄 하나로 보내요. 같은 묶음은 dedup_key로 한 번만이에요.
- 하나라도 거절 · 기한 지남 · 실패면 잇지 않아요(고객이 요청을 두기로 했어요). 잠금이 안 풀렸으면(견적서가 옴) 잇지 않아요.
- 카드는 LLM 없이 같은 도구 함수(propose_home_info)로 만들어 금액 · 차액도 계산 엔진 값 그대로예요.
- 실패해도 취소는 그대로예요(이 줄은 덤이라 종류 이름만 로그). 실행이 끝난(commit 뒤) 승인 요청 안에서 불러서, 화면이
  승인 뒤 대화를 다시 읽으면 이 줄이 이미 있어요.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.assistant.models import AssistantAction, AssistantNudge
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import SEOUL

log = logging.getLogger(__name__)

TRIGGER = "follow_up"
HOME_BODY = "보낸 실측 요청을 모두 취소했어요. 이어서 집 정보를 바꾸는 카드예요. 눌러야 바뀌어요."


def then_of(a: AssistantAction) -> dict | None:
    """이 행동에 달린 이어 할 일(지금은 집 정보만)."""
    then = (a.payload or {}).get("then")
    if isinstance(then, dict) and then.get("kind") == "home_info" and then.get("group"):
        return then
    return None


async def after_execute(user: User, a: AssistantAction, now: datetime) -> None:
    """실행된 행동 뒤: 이어 할 일이 있으면 묶음이 다 끝났는지 보고 다음 카드를 내밀어요. 실패는 삼켜요."""
    then = then_of(a)
    if then is None or a.project_id is None:
        return
    try:
        await _home(user, a.project_id, then, now)
    except Exception as e:  # noqa: BLE001 - 덤 줄이라 취소 결과는 그대로 둔다(종류 이름만 로그)
        log.warning("이어 하기 실패 (%s)", type(e).__name__)


async def _home(user: User, project_id: uuid.UUID, then: dict, now: datetime) -> None:
    from app.assistant import proactive
    from app.assistant.runtime import RefTable
    from app.assistant.tools import ToolCtx, ToolError, propose
    from app.project import service as project_service

    group = str(then["group"])
    key = f"follow:{group}"
    async with SessionLocal() as s:
        rows = (
            await s.scalars(
                select(AssistantAction).where(
                    AssistantAction.user_id == user.id,
                    AssistantAction.kind == "visit_cancel",
                    AssistantAction.payload["then"]["group"].astext == group,
                )
            )
        ).all()
        # 묶음의 다른 카드가 아직 열렸거나 처리 중이면 그 카드가 실행될 때 다시 봐요. 거절 · 만료 · 실패가 있으면 잇지 않아요
        if not rows or any(r.status != "executed" for r in rows):
            return
        made = await s.scalar(
            select(AssistantNudge.id).where(
                AssistantNudge.user_id == user.id, AssistantNudge.dedup_key == key
            )
        )
        if made is not None:
            return
        p = await project_service.get_for(s, user, project_id)
        if p.locked:  # 견적서가 왔거나 다른 요청이 살아 있어요
            return
    tc = ToolCtx(
        user=user,
        surface="customer",
        turn_id=None,
        chat_id=project_id,  # 집 정보 카드는 이름표를 쓰지 않아요(빈 표)
        project_id=project_id,
        visit_id=None,
        today=now.astimezone(SEOUL).date(),
        now=now,
        refs=RefTable(project_id),
        mode="free",
        pressed=True,  # 고객이 고쳐 달라고 한 값 그대로: 전에 거절한 같은 카드도 다시 만들어요
        origin="nudge",
    )
    try:
        out = await propose.propose_home_info(
            tc, propose.HomeIn(fields=propose.HomeFields.model_validate(then["fields"]))
        )
    except ToolError:  # 그사이 같은 값으로 바뀜 · 칸이 맞지 않게 됨: 잇지 않아요
        return
    if not out.actions:
        return
    n = AssistantNudge(
        user_id=user.id,
        surface="customer",
        project_id=project_id,
        trigger=TRIGGER,
        ref_id=project_id,
        dedup_key=key,
        channel="feed",
        status="sent",
        score=0,
        body=HOME_BODY,
        src="guide",
        card=out.cards[0].model_dump(mode="json") if out.cards else None,
        action_id=out.actions[0].action_id,
        due_at=now,
        sent_at=now,
    )
    async with SessionLocal() as s:
        s.add(n)
        try:
            await s.commit()
        except IntegrityError:  # 같은 묶음의 두 실행이 함께 왔어요: 먼저 넣은 줄 하나
            await s.rollback()
            return
    await proactive.signal(n)

"""대화 표 읽기 · 쓰기. commit은 하지 않는다 (service가 한다)."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Chat, ChatMessage


async def insert_chat(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> Chat:
    """project_id는 service가 세션 기준으로 본인 공사인지 확인한 값만 넘긴다."""
    chat = Chat(user_id=user_id, project_id=project_id)
    s.add(chat)
    await s.flush()  # id · rev를 바로 쓰려고 DB에 먼저 보낸다
    return chat


async def get_owned(s: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID) -> Chat | None:
    """내 대화만 꺼낸다. 남의 것과 없는 것을 구별하지 않는다(둘 다 None)."""
    return await s.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))


async def recent_messages(s: AsyncSession, chat_id: uuid.UUID, limit: int) -> list[ChatMessage]:
    """최근 limit줄을 오래된 것부터. 같은 턴이면 고객 질문이 답보다 먼저다."""
    rows = await s.scalars(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat_id)
        # 최근 것부터 limit줄을 자른 뒤 뒤집는다. 같은 턴 안에서는 답(assistant)이 먼저 오게 정렬
        .order_by(ChatMessage.turn.desc(), (ChatMessage.role == "assistant").desc())
        .limit(limit)
    )
    return list(reversed(rows.all()))


async def bump_rev(
    s: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID, rev: int, waiting: str | None
) -> bool:
    """번호표가 시작할 때 본 rev 그대로일 때만 1 올리고 waiting을 덮어쓴다. 됐으면 True.

    조건부 UPDATE 한 번이라, 두 요청이 동시에 와도 한쪽만 1행을 바꾼다.
    """
    res = await s.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.user_id == user_id, Chat.rev == rev)
        .values(rev=rev + 1, waiting=waiting, updated_at=func.now())
    )
    return res.rowcount == 1


def add_turn(
    s: AsyncSession,
    chat_id: uuid.UUID,
    turn: int,
    question: str,
    answer: str,
    intent: dict | None,
) -> None:
    """한 턴의 고객 질문 · 답 두 줄. intent: {label, confidence, source} 또는 None."""
    s.add_all(
        [
            ChatMessage(
                chat_id=chat_id,
                turn=turn,
                role="user",
                text=question,
                intent_label=intent and intent["label"],
                intent_confidence=intent and intent["confidence"],
                intent_source=intent and intent["source"],
            ),
            ChatMessage(chat_id=chat_id, turn=turn, role="assistant", text=answer),
        ]
    )


async def set_project(
    s: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    """공사 칸이 빈 내 대화에만 공사를 적는다(이미 다른 공사에 묶인 대화는 옮기지 않는다)."""
    await s.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.user_id == user_id, Chat.project_id.is_(None))
        .values(project_id=project_id)
    )


async def list_chats(
    s: AsyncSession, user_id: uuid.UUID, limit: int = 20, project_id: uuid.UUID | None = None
) -> list[Chat]:
    """내 대화방 최근 것부터. project_id를 주면 그 공사 대화만."""
    q = select(Chat).where(Chat.user_id == user_id)
    if project_id is not None:
        q = q.where(Chat.project_id == project_id)
    rows = await s.scalars(q.order_by(Chat.updated_at.desc()).limit(limit))
    return list(rows.all())


async def last_questions(s: AsyncSession, chat_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """대화방마다 마지막 고객 질문(미리 보기)."""
    if not chat_ids:
        return {}
    last = (
        select(ChatMessage.chat_id, func.max(ChatMessage.turn).label("turn"))
        .where(ChatMessage.chat_id.in_(chat_ids), ChatMessage.role == "user")
        .group_by(ChatMessage.chat_id)
        .subquery()
    )
    rows = await s.execute(
        select(ChatMessage.chat_id, ChatMessage.text)
        .join(last, (ChatMessage.chat_id == last.c.chat_id) & (ChatMessage.turn == last.c.turn))
        .where(ChatMessage.role == "user")
    )
    return {r.chat_id: r.text for r in rows}

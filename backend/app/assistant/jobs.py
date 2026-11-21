"""비서 기한 일 처리 함수(HANDLERS, worker.sweep_jobs가 부른다). 계약: jobs.service.JobHandler.

- assistant_memory: 비서 턴 저장(finish_turn)이 같은 트랜잭션에 넣은 일. ref_id = 그 턴의 고객 메시지.
  비서 대화(chats.kind=assistant)의 고객 줄만 읽고, 읽은 뒤 트랜잭션을 닫고 Haiku(memory.extract)를 부른다.
  검사(memory.validate)를 지난 것만 저장하고, 그 말이 직접 할 일을 업체에 넘기면 앞 기억에서 뺀다(Haiku는 뺀 일을
  뽑지 않는다). commit은 worker가 한다.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import memory
from app.chat.models import Chat, ChatMessage
from app.jobs.models import Job
from app.jobs.service import JobHandler


async def remember(s: AsyncSession, job: Job, now: datetime) -> bool:
    """고객 메시지 한 줄 → 기억. 메시지가 없거나 비서 대화의 고객 줄이 아니면 False(skipped)."""
    if job.ref_id is None:
        return False
    row = (
        await s.execute(
            select(ChatMessage.text, Chat.user_id)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(
                ChatMessage.id == job.ref_id,
                ChatMessage.role == "user",
                Chat.kind == "assistant",
            )
        )
    ).first()
    if row is None:
        return False
    text, user_id = row
    await s.commit()  # LLM을 기다리는 동안 트랜잭션을 쥐지 않는다(읽기만 했다)
    items = memory.validate(await memory.extract(text, user_id), text)
    return await memory.save(s, user_id, job.ref_id, items, now, said=text) > 0


HANDLERS: dict[str, JobHandler] = {"assistant_memory": remember}

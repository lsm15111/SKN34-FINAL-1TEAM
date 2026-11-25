"""v2 상담 한 턴을 대화 표(chat)에 잇는다 (C안, #111). 한 턴 순서는 협약 8절.

열기(get_for · recent) → ask.start / resume(LLM ↔ 도구, DB 세션을 쥐지 않음) → 끝난 턴만 저장(save_turn).
- 열 때 본 rev · 질문은 ask 턴 정보("chat")에 같이 둔다. 화면 도구를 기다리는 동안에도 남는다
- 새 대화는 첫 턴을 저장할 때 만든다. 범위 밖 · 실패로 끝난 질문 때문에 빈 대화가 남지 않게
- 실패한 답 · 범위 밖 고정 안내는 저장하지 않는다. rev · waiting이 그대로라 다음 질문은 그대로 이어진다 (#128)
- 되물었는지는 답 끝의 [되물음] 표시로 안다(chat 지시문). 표시는 떼고, 그 역할 라벨을 waiting에 남긴다
  다음 턴 관문이 waiting을 받아 짧은 답("32평")도 같은 역할로 보낸다 (#120)
- 대화 표에는 일반 상담(kind=chat)만 쌓는다. 견적서 · 공정표 화면 버튼의 설명은 한 번으로 끝난다
"""

import uuid
from datetime import date

from app.agent.schemas import Intent
from app.chat import service as chat_service
from app.db import SessionLocal
from app.v2 import ask
from app.v2 import schemas as v2

ASKED = "[되물음]"  # chat 지시문이 되물을 때만 답 끝에 붙인다. 화면에는 보내지 않는다


async def start(user_id: uuid.UUID, b: v2.V2AskIn, today: date) -> v2.V2AskOut:
    history: list[dict] = []
    rev, waiting = 1, None
    keep = b.kind == "chat"
    if keep and b.chat_id is not None:
        async with SessionLocal() as s:  # 짧게 열고 닫는다. LLM을 기다리는 동안 쥐지 않는다
            chat = await chat_service.get_for(s, user_id, b.chat_id)
            turns = await chat_service.recent(s, chat)
            rev, waiting = chat.rev, chat.waiting
        history = [{"role": t.role, "content": t.text} for t in turns]
    meta = {
        "keep": keep,
        "id": str(b.chat_id) if keep and b.chat_id else None,
        "rev": rev,
        "question": b.message,
    }
    out = await ask.start(str(user_id), b, today, history, waiting, meta)
    return await _finish(user_id, out, meta)


async def resume(user_id: uuid.UUID, turn_id: str, b: v2.V2AskResumeIn) -> v2.V2AskOut:
    # 같은 턴 재개가 겹치면 늦은 쪽은 여기서 404, 결과 id가 틀리면 지우지 않고 422
    turn = await ask.take(turn_id, str(user_id), [r.id for r in b.results])
    out = await ask.resume(str(user_id), turn_id, b, turn)
    meta = turn["chat"]
    return await _finish(user_id, out, meta)


def asked_back(text: str, dropped: list[str]) -> tuple[str, bool]:
    """(표시를 뗀 답, 되물었는지). eval도 같은 판정을 쓴다.

    답이 표시로 끝날 때만 되물음이다(따로 된 줄이든 질문 끝에 붙었든). 중간 · 앞 도구 라운드의 표시는 아니다.
    출력 검사가 문장을 뺐으면 질문이 남았는지 알 수 없어 되물음으로 보지 않는다. 표시는 어디 있든 뗀다.
    """
    body = text.rstrip()
    return body.replace(ASKED, "").strip(), body.endswith(ASKED) and not dropped


async def _finish(user_id: uuid.UUID, out: v2.V2AskOut, meta: dict) -> v2.V2AskOut:
    chat_id = uuid.UUID(meta["id"]) if meta["id"] else None
    if not out.done or out.failed or out.gate == "out" or not meta["keep"]:
        return out.model_copy(update={"chat_id": chat_id})
    intent = Intent.model_validate(out.intent.model_dump()) if out.intent else None
    text, asked = asked_back(out.text, out.dropped)
    if not text:  # 표시만 남은 답(출력 검사가 질문을 뺀 경우 포함)은 실패로 보고 저장하지 않는다
        return out.model_copy(
            update={"chat_id": chat_id, "text": ask.FAILED["chat"], "failed": True}
        )
    # 되물은 역할: 관문 라벨, 없으면 가이드(orchestrator). 되묻지 않았으면 비운다
    waiting = (intent.label if intent else "orchestrator") if asked else None
    async with SessionLocal() as s:
        if chat_id is None:
            chat_id = await chat_service.create(s, user_id)
        await chat_service.save_turn(
            s,
            user_id=user_id,
            chat_id=chat_id,
            rev=meta["rev"],
            question=meta["question"],
            answer=text,
            intent=intent,
            waiting=waiting,
        )
    return out.model_copy(update={"chat_id": chat_id, "text": text})

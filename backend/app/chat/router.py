"""AI 칸 API (`/ai/*`, api.md 16절). 고객만 묻는다(로그인 전은 자주 묻는 질문 칩만, 9판 N1 A).

- POST /ai/turns → SSE(`draft` 먼저 보일 무료 답 · `token` 문장 · `card` 화면 조각 · `done` 전체 답).
  오류는 스트림을 열기 전에 같은 오류 모양으로. 답은 저장(commit)까지 끝난 뒤 보낸다(완료 신호는 commit 뒤).
  LLM 모드는 글을 다시 쓰는 동안(수 초) 검사를 통과한 무료 답을 `draft`로 먼저 보낸다. 화면은 done이 오면 바꾼다.
- 사용자 · 프로젝트는 세션 · 요청 경로로만 정하고(남의 것 404) 답 · 도구 인자로 받지 않는다.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.auth.models import User
from app.chat import service
from app.chat.schemas import AiAnswer, AiFaqOut, AiThreadDetailOut, AiThreadOut, AiTurnIn, AiTurnOut
from app.db import get_session
from app.shared.clock import today_seoul
from app.shared.ratelimit import client_ip

router = APIRouter(prefix="/ai", tags=["ai"])
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(out: AiTurnOut) -> AsyncIterator[str]:
    for i, sec in enumerate(out.answer.sections):
        for text in sec.sentences:
            yield _event("token", {"section": i, "text": text})
    for text in out.answer.unknown:
        yield _event("token", {"section": None, "text": text})
    for i, card in enumerate(out.answer.cards):
        yield _event("card", {"index": i, **card.model_dump(mode="json")})
    yield _event("done", out.model_dump(mode="json"))


@router.post(
    "/turns",
    summary="AI 칸에 묻기 (SSE: token · card · done)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "done 몸통 = AiTurnOut"}},
)
async def turn(body: AiTurnIn, user: User = Depends(require_role("customer"))) -> StreamingResponse:
    q: asyncio.Queue[AiAnswer] = asyncio.Queue()
    job = asyncio.create_task(service.ai_turn(user, body, today_seoul(), on_draft=q.put))
    got = asyncio.create_task(q.get())
    await asyncio.wait({job, got}, return_when=asyncio.FIRST_COMPLETED)
    if job.done() and not got.done():
        got.cancel()
        out = (
            job.result()
        )  # 오류(404 · 409 · 422)는 여기서 나와 스트림을 열기 전에 같은 오류 모양이 돼요
        return StreamingResponse(_stream(out), media_type="text/event-stream", headers=SSE_HEADERS)
    first = got.result()

    async def stream() -> AsyncIterator[str]:
        yield _event("draft", first.model_dump(mode="json"))
        try:
            out = await job
        except Exception:  # noqa: BLE001 - 스트림이 열린 뒤라 오류 이벤트로 알려요(입력값은 넣지 않음)
            yield _event("error", {"code": "failed", "message": "답을 끝까지 만들지 못했어요."})
            return
        async for x in _stream(out):
            yield x

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads", response_model=list[AiThreadOut], summary="내 AI 대화 목록")
async def threads(
    project_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> list[AiThreadOut]:
    return await service.ai_threads(s, user, project_id)


@router.get("/threads/{chat_id}", response_model=AiThreadDetailOut, summary="AI 대화 이어 보기")
async def thread(
    chat_id: uuid.UUID,
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> AiThreadDetailOut:
    return await service.ai_thread(s, user, chat_id)


@router.get("/faq", response_model=list[AiFaqOut], summary="로그인 전 자주 묻는 질문 칩")
async def faq(request: Request) -> list[AiFaqOut]:
    return await service.faq(client_ip(request))

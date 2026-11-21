"""AI 칸 API (`/ai/*`, api.md 16절). 고객만 묻는다(로그인 전은 자주 묻는 질문 칩만, 9판 N1 A).

- POST /ai/turns → SSE(`part` 먼저 보일 고정 몫 · `token` 문장 · `card` 화면 조각 · `done` 전체 답).
  오류는 스트림을 열기 전에 같은 오류 모양으로. 답은 저장(commit)까지 끝난 뒤 보낸다(완료 신호는 commit 뒤).
  LLM 모드는 답 작성기를 기다리는 동안(수 초) 고정 몫(계산 결과 · 정해 둔 글)을 `part`로 먼저 보낸다(비어 있어도).
  done의 앞 묶음은 part와 같아서, 화면은 이미 보인 글을 바꾸지 않고 그 아래에 이어 붙인다.
  로그인 확인은 짧은 세션으로 끝내 턴 동안 DB 연결을 쥐지 않고, 동시 턴 자리가 다 차면 503 busy(Retry-After).
- 사용자 · 프로젝트는 세션 · 요청 경로로만 정하고(남의 것 404) 답 · 도구 인자로 받지 않는다.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role, require_role_short
from app.auth.models import User
from app.chat import service
from app.chat.schemas import AiAnswer, AiFaqOut, AiThreadDetailOut, AiThreadOut, AiTurnIn, AiTurnOut
from app.db import get_session
from app.shared.clock import today_seoul
from app.shared.ratelimit import client_ip
from app.shared.request_guards import turn_slot

router = APIRouter(prefix="/ai", tags=["ai"])
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
# 턴: 로그인 확인은 짧은 세션으로(턴 동안 DB 연결을 쥐지 않음) + 동시 턴 자리(로그인 확인 뒤에 잡는다)
TurnCustomer = Depends(require_role_short("customer"))
TurnSlot = Depends(turn_slot)


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
    summary="AI 칸에 묻기 (SSE: part · token · card · done)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "done 몸통 = AiTurnOut"}},
)
async def turn(
    body: AiTurnIn, user: User = TurnCustomer, _slot: None = TurnSlot
) -> StreamingResponse:
    q: asyncio.Queue[AiAnswer] = asyncio.Queue()
    job = asyncio.create_task(service.ai_turn(user, body, today_seoul(), on_part=q.put))
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
        yield _event("part", first.model_dump(mode="json"))
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


# /threads/{chat_id}보다 먼저 둬요('latest'가 대화 id 자리로 들어가 422가 되지 않게)
@router.get(
    "/threads/latest",
    response_model=AiThreadDetailOut | None,
    summary="화면을 옮겨도 이어 갈 대화(같은 공사 · 24시간 안 마지막 대화, 없으면 null)",
)
async def latest_thread(
    project_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(require_role("customer")),
    s: AsyncSession = Depends(get_session),
) -> AiThreadDetailOut | None:
    return await service.ai_latest(s, user, project_id)


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

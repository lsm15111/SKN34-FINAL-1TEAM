"""비서 API (계약서 3장): 고객 /assistant(require_role customer) · 업체 /vendor/assistant(approved_vendor).

- POST …/turns → SSE(ack · status · card · action · token · done | error). 스트림을 열기 전 오류(404 · 409 ·
  429 · 503)는 같은 오류 모양이다. 같은 client_key로 끝난 턴이면 저장한 결과를 같은 이벤트로 다시 보낸다.
  로그인 확인은 짧은 세션으로 끝내 스트림 동안 DB 연결을 쥐지 않고, 동시 턴 자리가 다 차면 503 busy(Retry-After).
- 사용자 · 공사 · 요청은 세션 · 요청 경로로만 정하고 LLM 출력으로 받지 않는다. 남의 것은 404, 역할이 다르면 403.
- 먼저 말 걸기: POST …/nudges/{id}/open · dismiss(고객 · 업체 같은 꼴, 닫으면 같은 일을 3일 쉰다).
- 기억: GET /assistant/memory · DELETE /assistant/memory/{id}(고객만). 기억 쓰기 API · 도구는 없다.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from app.assistant import service
from app.assistant.models import AssistantTurn
from app.assistant.schemas import (
    ActionOut,
    ApproveIn,
    AssistantThreadOut,
    BoardOut,
    FeedPage,
    HealthOut,
    MemoryOut,
    NudgeOut,
    QuoteChecklistData,
    TodayData,
    TurnIn,
    TurnOut,
    VendorBriefData,
    VendorTodayData,
    VendorTurnIn,
)
from app.auth.deps import require_role, require_role_short
from app.auth.models import User
from app.shared.request_guards import turn_slot
from app.vendor.deps import approved_vendor, approved_vendor_short

router = APIRouter(prefix="/assistant", tags=["assistant"])
vendor_router = APIRouter(prefix="/vendor/assistant", tags=["assistant"])
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
SSE_DOC = {
    200: {
        "content": {"text/event-stream": {}},
        "description": "ack → status · card · action → token → done(실패면 error). data마다 seq",
    }
}
Customer = Depends(require_role("customer"))
Vendor = Depends(approved_vendor)
# SSE 턴: 같은 검사를 짧은 세션으로(스트림 동안 DB 연결을 쥐지 않음) + 동시 턴 자리(로그인 확인 뒤에 잡는다)
TurnCustomer = Depends(require_role_short("customer"))
TurnVendor = Depends(approved_vendor_short)
TurnSlot = Depends(turn_slot)
Status = Literal["proposed", "approved", "executed", "rejected", "expired", "failed"]


def _sse(user: User, got) -> StreamingResponse:
    body = service.replay(user, got) if isinstance(got, AssistantTurn) else service.stream(got)
    return StreamingResponse(body, media_type="text/event-stream", headers=SSE_HEADERS)


# ---- 고객 ----


@router.post(
    "/turns",
    summary="비서에게 묻기 (SSE)",
    response_class=StreamingResponse,
    responses=SSE_DOC,
)
async def turn(
    body: TurnIn, user: User = TurnCustomer, _slot: None = TurnSlot
) -> StreamingResponse:
    got = await service.start_turn(
        user,
        surface="customer",
        client_key=body.client_key,
        text=body.text,
        project_id=body.project_id,
        context=body.context,
    )
    return _sse(user, got)


@router.get("/turns/{turn_id}", response_model=TurnOut, summary="턴 하나 다시 보기")
async def turn_detail(turn_id: uuid.UUID, user: User = Customer) -> TurnOut:
    return await service.turn_out(user, turn_id, "customer")


@router.get(
    "/threads/latest",
    response_model=AssistantThreadOut | None,
    summary="이 공사의 비서 대화(없으면 null)",
)
async def latest(
    project_id: uuid.UUID = Query(), user: User = Customer
) -> AssistantThreadOut | None:
    return await service.latest_thread(user, project_id)


@router.get("/feed", response_model=FeedPage, summary="비서 대화 기록 한 쪽")
async def feed(
    project_id: uuid.UUID = Query(),
    before: int | None = Query(default=None, ge=1, description="이 턴보다 앞 쪽"),
    limit: int = Query(default=30, ge=2, le=60),
    user: User = Customer,
) -> FeedPage:
    return await service.feed_for(user, "customer", project_id, before, limit)


@router.get("/board", response_model=BoardOut, summary="내 공사 보드")
async def board(project_id: uuid.UUID = Query(), user: User = Customer) -> BoardOut:
    return await service.board_for(user, project_id)


@router.get("/today", response_model=TodayData, summary="오늘 정할 일")
async def today(project_id: uuid.UUID = Query(), user: User = Customer) -> TodayData:
    return await service.today_for(user, project_id)


@router.get("/actions", response_model=list[ActionOut], summary="제안 행동 목록")
async def actions_list(
    project_id: uuid.UUID | None = Query(default=None),
    status: Status | None = Query(default=None),
    user: User = Customer,
) -> list[ActionOut]:
    return await service.actions_for(user, "customer", project_id, status)


@router.post("/actions/{action_id}/approve", response_model=ActionOut, summary="승인(실행)")
async def approve(
    action_id: uuid.UUID, body: ApproveIn | None = None, user: User = Customer
) -> ActionOut:
    return await service.approve(user, action_id, body or ApproveIn(), "customer")


@router.post("/actions/{action_id}/reject", response_model=ActionOut, summary="거절")
async def reject(action_id: uuid.UUID, user: User = Customer) -> ActionOut:
    return await service.reject(user, action_id, "customer")


@router.post("/nudges/{nudge_id}/open", response_model=NudgeOut, summary="먼저 말 건 줄 열기")
async def nudge_open(nudge_id: uuid.UUID, user: User = Customer) -> NudgeOut:
    return await service.nudge_act(user, nudge_id, "customer", "opened")


@router.post(
    "/nudges/{nudge_id}/dismiss",
    response_model=NudgeOut,
    summary="먼저 말 건 줄 닫기(같은 일을 3일 쉬어요)",
)
async def nudge_dismiss(nudge_id: uuid.UUID, user: User = Customer) -> NudgeOut:
    return await service.nudge_act(user, nudge_id, "customer", "dismissed")


@router.get("/memory", response_model=list[MemoryOut], summary="비서가 기억하는 것(내 말에서만)")
async def memory(user: User = Customer) -> list[MemoryOut]:
    return await service.memory_for(user)


@router.delete("/memory/{memory_id}", status_code=204, summary="기억 한 줄 지우기")
async def forget(memory_id: uuid.UUID, user: User = Customer) -> Response:
    await service.forget(user, memory_id)
    return Response(status_code=204)


@router.get("/health", response_model=HealthOut, summary="비서가 지금 LLM으로 답하는지")
async def health(user: User = Customer) -> HealthOut:
    return await service.health(user)


# ---- 업체 ----


@vendor_router.post(
    "/turns",
    summary="업체 비서에게 묻기 (SSE)",
    response_class=StreamingResponse,
    responses=SSE_DOC,
)
async def vendor_turn(
    body: VendorTurnIn, vendor: User = TurnVendor, _slot: None = TurnSlot
) -> StreamingResponse:
    got = await service.start_turn(
        vendor,
        surface="vendor",
        client_key=body.client_key,
        text=body.text,
        visit_id=body.visit_id,
        context=body.context,
    )
    return _sse(vendor, got)


@vendor_router.get("/turns/{turn_id}", response_model=TurnOut, summary="턴 하나 다시 보기")
async def vendor_turn_detail(turn_id: uuid.UUID, vendor: User = Vendor) -> TurnOut:
    return await service.turn_out(vendor, turn_id, "vendor")


@vendor_router.get("/feed", response_model=FeedPage, summary="업체 비서 대화 기록 한 쪽")
async def vendor_feed(
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=30, ge=2, le=60),
    vendor: User = Vendor,
) -> FeedPage:
    return await service.feed_for(vendor, "vendor", None, before, limit)


@vendor_router.get("/briefs/{visit_id}", response_model=VendorBriefData, summary="요청 브리핑")
async def vendor_brief(visit_id: uuid.UUID, vendor: User = Vendor) -> VendorBriefData:
    return await service.brief_for(vendor, visit_id)


@vendor_router.get(
    "/checklists/{visit_id}", response_model=QuoteChecklistData, summary="견적서 체크리스트"
)
async def vendor_checklist(visit_id: uuid.UUID, vendor: User = Vendor) -> QuoteChecklistData:
    return await service.checklist_for(vendor, visit_id)


@vendor_router.get("/today", response_model=VendorTodayData, summary="오늘 브리핑")
async def vendor_today(vendor: User = Vendor) -> VendorTodayData:
    return await service.vendor_today(vendor)


@vendor_router.get("/actions", response_model=list[ActionOut], summary="제안 행동 목록")
async def vendor_actions(
    status: Status | None = Query(default=None), vendor: User = Vendor
) -> list[ActionOut]:
    return await service.actions_for(vendor, "vendor", None, status)


@vendor_router.post("/actions/{action_id}/approve", response_model=ActionOut, summary="승인(실행)")
async def vendor_approve(
    action_id: uuid.UUID, body: ApproveIn | None = None, vendor: User = Vendor
) -> ActionOut:
    return await service.approve(vendor, action_id, body or ApproveIn(), "vendor")


@vendor_router.post("/actions/{action_id}/reject", response_model=ActionOut, summary="거절")
async def vendor_reject(action_id: uuid.UUID, vendor: User = Vendor) -> ActionOut:
    return await service.reject(vendor, action_id, "vendor")


@vendor_router.post(
    "/nudges/{nudge_id}/open", response_model=NudgeOut, summary="먼저 말 건 줄 열기"
)
async def vendor_nudge_open(nudge_id: uuid.UUID, vendor: User = Vendor) -> NudgeOut:
    return await service.nudge_act(vendor, nudge_id, "vendor", "opened")


@vendor_router.post(
    "/nudges/{nudge_id}/dismiss",
    response_model=NudgeOut,
    summary="먼저 말 건 줄 닫기(같은 일을 3일 쉬어요)",
)
async def vendor_nudge_dismiss(nudge_id: uuid.UUID, vendor: User = Vendor) -> NudgeOut:
    return await service.nudge_act(vendor, nudge_id, "vendor", "dismissed")

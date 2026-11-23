import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.auth.models import User
from app.db import get_session
from app.quote.schemas import QuoteDraftIn
from app.shared.clock import now_utc, today_seoul
from app.shared.errors import app_error
from app.vendor.deps import approved_vendor
from app.visit import flow, service
from app.visit.schemas import (
    BoardRowOut,
    CancelIn,
    ChangeOut,
    DeclineIn,
    PickOut,
    ProposeIn,
    QuoteBoardOut,
    ReselectIn,
    ReselectOut,
    ShortlistIn,
    ShortlistOut,
    SlotIn,
    SlotsIn,
    VendorDetailOut,
    VendorListOut,
    VendorScheduleOut,
    VendorVisitDetailOut,
    VendorVisitStateOut,
    VisitCreateIn,
    VisitCreateOut,
    VisitDraftOut,
    VisitedIn,
    VisitListOut,
    VisitOut,
    VisitPickOut,
    VisitStateOut,
    WindowAnswerOut,
    WindowIn,
)

router = APIRouter(tags=["업체 고르기 · 실측 요청"])
customer_only = require_role("customer")
Trade = Literal["dobae", "mokgong"]
Grade = Literal["economy", "basic"]
ICS = {200: {"content": {"text/calendar": {"schema": {"type": "string"}}}}}


async def visit_session(s: AsyncSession = Depends(get_session)) -> AsyncIterator[AsyncSession]:
    """요청 세션 + commit 뒤 화면 신호: service가 남긴 신호(service.LATER)를 엔드포인트가 끝나면
    응답 전에 보낸다(scope="function"). 오류로 끝나면 버린다."""
    try:
        yield s
    except Exception:
        service.drop_later(s)
        raise
    await service.flush_later(s)


Session = Depends(visit_session, scope="function")


@router.get(
    "/projects/{project_id}/vendors",
    response_model=VendorListOut,
    summary="이 집 업체 고르기 · 가견적 낮은 순 (내 프로젝트만)",
)
async def vendors(
    project_id: uuid.UUID,
    trade: Trade,
    sort: Literal["estimate"] = "estimate",
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VendorListOut:
    return await service.vendors_for(s, user, project_id, trade)


@router.get(
    "/projects/{project_id}/vendors/{vendor_id}",
    response_model=VendorDetailOut,
    summary="이 집 기준 업체 자세히 · 가견적 계산 (목록 밖 업체는 404)",
)
async def vendor_detail(
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    trade: Trade,
    grade: Annotated[Grade | None, Query(description="v3: 그 벽지로 미리 보기 (C11)")] = None,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VendorDetailOut:
    return await service.vendor_detail(
        s, user, project_id, vendor_id, trade, today_seoul(), grade=grade
    )


@router.get(
    "/projects/{project_id}/vendors/{vendor_id}/photos/{file_id}",
    summary="업체 시공 사진 보기 (이 집에서 고를 수 있는 업체만)",
)
async def vendor_photo(
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> Response:
    return await service.vendor_photo(s, user, project_id, vendor_id, file_id)


@router.post(
    "/projects/{project_id}/visits",
    status_code=201,
    response_model=VisitCreateOut,
    summary="실측 요청 보내기 · v3는 담은 업체에 희망 기간 · 사진 · 고른 벽지로 (옛 몸통은 v2 길)",
)
async def request_visits(
    project_id: uuid.UUID,
    data: VisitCreateIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitCreateOut:
    if data.wish_start is not None or data.wish_end is not None:  # v3: 담긴 업체 · 희망 기간
        # 화면 요청도 고객 직접 할 일을 '업체에 알릴 것'으로 같이 보내요(비서 길과 같게)
        return await flow.request(s, user, project_id, data, now_utc(), screen=True)
    if data.photos or data.grade is not None:
        raise app_error("invalid", "사진 · 벽지는 희망 기간을 고른 요청에만 붙여요.")
    return await service.request_visits(s, user, project_id, data, today_seoul())


@router.get(
    "/projects/{project_id}/visits",
    response_model=VisitListOut,
    summary="이 집 실측 요청 · 업체 연락처 · 보낼 문구 · 남은 칸",
)
async def visits(
    project_id: uuid.UUID,
    trade: Trade | None = None,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitListOut:
    return await service.visits_for(s, user, project_id, trade, today_seoul(), now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/cancel",
    response_model=VisitOut,
    summary="실측 요청 취소 (견적서가 오기 전까지)",
)
async def cancel_visit(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: CancelIn | None = None,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitOut:
    return await service.cancel(s, user, project_id, visit_id, today_seoul(), data, now_utc())


@router.post(
    "/projects/{project_id}/visits/reselect",
    response_model=ReselectOut,
    summary="다시 고르기 (확정 전): 이 공정의 실측 요청을 모두 닫고 칸 3개를 비운다",
)
async def reselect_visits(
    project_id: uuid.UUID,
    data: ReselectIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ReselectOut:
    return await service.reselect(s, user, project_id, data)


@router.get(
    "/vendor/visits/{visit_id}",
    response_model=VendorVisitDetailOut,
    summary="받은 실측 요청 자세히 (집은 구 · 동까지, 고객 이름 · 연락처 없음). ?start=&end=&excluded=로"
    " 보내기 전 열린 칸을 미리 센다",
)
async def vendor_visit(
    visit_id: uuid.UUID,
    start: Annotated[date | None, Query(description="미리 셀 기간 시작 (end와 같이)")] = None,
    end: Annotated[date | None, Query(description="미리 셀 기간 끝 (62일 안)")] = None,
    excluded: Annotated[list[date], Query(description="빼는 날 (기간 안, 31개까지)")] = [],  # noqa: B006
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitDetailOut:
    preview = None
    if start is not None or end is not None or excluded:
        if start is None or end is None:
            raise app_error("invalid", "미리 셀 기간의 시작과 끝을 같이 보내 주세요.")
        try:
            w = WindowIn(start=start, end=end, excluded=excluded)
        except (
            ValidationError
        ) as exc:  # 기간 답하기와 같은 규칙 (62일 · 빼는 날은 기간 안 · 겹침 없음)
            raise app_error("invalid", "기간을 다시 골라 주세요. (62일 안)") from exc
        preview = (w.start, w.end, w.excluded)
    return await service.vendor_visit(s, vendor, visit_id, today_seoul(), preview)


@router.get(
    "/vendor/visits/{visit_id}/photos/{file_id}",
    summary="요청 사진 보기 (그 요청을 받은 업체만, 위치 정보는 올릴 때 지움)",
)
async def vendor_visit_photo(
    visit_id: uuid.UUID,
    file_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> Response:
    return await service.vendor_visit_photo(s, vendor, visit_id, file_id)


@router.post(
    "/vendor/visits/{visit_id}/decline",
    response_model=VendorVisitDetailOut,
    summary="이 요청 못 받아요 (견적서를 보내기 전까지)",
)
async def decline_visit(
    visit_id: uuid.UUID,
    data: DeclineIn,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitDetailOut:
    return await service.decline(s, vendor, visit_id, data.code, today_seoul(), note=data.note)


@router.post(
    "/vendor/visits/{visit_id}/seen", status_code=204, summary="받은 요청 열어 봄 ('새 요청' 지움)"
)
async def seen_visit(
    visit_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> Response:
    await service.mark_seen(s, vendor, visit_id)
    return Response(status_code=204)


@router.get(
    "/vendor/visits/{visit_id}/quote",
    response_model=QuoteBoardOut,
    summary="실측 견적서 올리기 · 임시 저장본 · 보낸 버전 · 칸 한도",
)
async def quote_board(
    visit_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> QuoteBoardOut:
    return await service.quote_board(s, vendor, visit_id)


@router.put(
    "/vendor/visits/{visit_id}/quote",
    response_model=QuoteBoardOut,
    summary="실측 견적서 임시 저장 (통째로, 요청함 · 견적서 옴일 때만)",
)
async def save_quote(
    visit_id: uuid.UUID,
    data: QuoteDraftIn,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> QuoteBoardOut:
    return await service.save_quote(s, vendor, visit_id, data, today_seoul())


@router.post(
    "/vendor/visits/{visit_id}/quote/send",
    response_model=QuoteBoardOut,
    summary="실측 견적서 보내기 (빠진 칸은 칸별 422, 이미 보냈으면 409)",
)
async def send_quote(
    visit_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> QuoteBoardOut:
    return await service.send_quote(s, vendor, visit_id, today_seoul())


@router.get(
    "/projects/{project_id}/quotes/{quote_id}/files/{file_id}",
    summary="받은 실측 견적서 파일 보기 (그 요청의 고객 · 보낸 버전만)",
)
async def customer_quote_file(
    project_id: uuid.UUID,
    quote_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> Response:
    return await service.customer_quote_file(s, user, project_id, quote_id, file_id)


@router.get(
    "/vendor/visits/{visit_id}/quote/files/{file_id}",
    summary="내 실측 견적서 파일 보기 (임시 저장본 포함)",
)
async def vendor_quote_file(
    visit_id: uuid.UUID,
    file_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> Response:
    return await service.vendor_quote_file(s, vendor, visit_id, file_id)


# ======== v3 담기 · 실측 일정 (고객) ========
# 같은 경로 깊이에서 글자 경로(draft)를 {visit_id}보다 먼저 둔다.


@router.get(
    "/projects/{project_id}/shortlist",
    response_model=ShortlistOut,
    summary="v3 담은 업체 · 칸 (공종마다 3칸)",
)
async def shortlist(
    project_id: uuid.UUID,
    trade: Trade,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ShortlistOut:
    return await service.shortlist_for(s, user, project_id, trade)


@router.post(
    "/projects/{project_id}/shortlist",
    status_code=201,
    response_model=ShortlistOut,
    summary="v3 업체 담기 (409 already · slots_full · no_estimate · paper_unsupported ·"
    " blocked_retry · locked)",
)
async def add_shortlist(
    project_id: uuid.UUID,
    data: ShortlistIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ShortlistOut:
    return await flow.add_shortlist(s, user, project_id, data)


@router.delete(
    "/projects/{project_id}/shortlist/{vendor_id}",
    status_code=204,
    summary="v3 담기 빼기 (요청이 살아 있으면 409 locked, 요청 취소부터)",
)
async def remove_shortlist(
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    trade: Trade,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> Response:
    await flow.remove_shortlist(s, user, project_id, vendor_id, trade)
    return Response(status_code=204)


@router.get(
    "/projects/{project_id}/visits/draft",
    response_model=VisitDraftOut,
    summary="v3 요청서 · AI 초안: 희망 기간(공사 시작 희망일 − 28일 ~ − 14일) · 담은 업체",
)
async def visit_draft(
    project_id: uuid.UUID,
    trade: Trade,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitDraftOut:
    return await service.draft_for(s, user, project_id, trade, today_seoul())


@router.get(
    "/projects/{project_id}/visits/{visit_id}",
    response_model=VisitPickOut,
    summary="v3 날짜 고르기 · 확정 · 제안 · 겹침 없음 화면 (열린 반나절 · 추천은 계산 엔진)",
)
async def visit_pick_view(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitPickOut:
    return await service.pick_view(s, user, project_id, visit_id, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/pick",
    response_model=PickOut,
    summary="v3 반나절 고르기: 바로 확정이면 booked, 아니면 picked(48시간 잡아 둠)."
    " 409 slot_taken · stale · expired",
)
async def pick_visit(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> PickOut:
    return await flow.pick(s, user, project_id, visit_id, data, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/proposal/pick",
    response_model=PickOut,
    summary="v3 업체가 제안한 날 고르기 (proposed → booked, 409 slot_taken)",
)
async def pick_proposal(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> PickOut:
    return await flow.pick_proposal(s, user, project_id, visit_id, data, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/repick",
    response_model=VisitStateOut,
    summary="v3 제안 대신 업체 기간에서 다시 고르기 (proposed → offered)",
)
async def repick_visit(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitStateOut:
    return await flow.repick(s, user, project_id, visit_id, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/again",
    status_code=201,
    response_model=BoardRowOut,
    summary="v3 한 번 더 요청 (기한 지남 · 취소 뒤, 시도 2까지. 그 뒤 409 blocked_retry)",
)
async def request_again(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> BoardRowOut:
    return await flow.again(s, user, project_id, visit_id, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/visited",
    response_model=VisitStateOut,
    summary="v3 실측 받았어요 · 업체가 안 왔어요 (반나절이 끝난 뒤, L09. 그 전 409)",
)
async def visited(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: VisitedIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitStateOut:
    return await flow.visited(s, user, project_id, visit_id, data, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/changes",
    status_code=201,
    response_model=ChangeOut,
    summary="v3 확정한 실측 일정 바꾸기 요청 (열린 요청 하나, 409 already)",
)
async def request_change(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ChangeOut:
    return await flow.request_change(s, user, project_id, visit_id, data, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/changes/{change_id}/withdraw",
    response_model=ChangeOut,
    summary="v3 바꾸기 요청 거두기",
)
async def withdraw_change(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ChangeOut:
    return await flow.withdraw_change(s, user, project_id, visit_id, change_id, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/changes/{change_id}/pick",
    response_model=ChangeOut,
    summary="v3 업체가 바꾸기 요청에 낸 다른 날 고르기 (countered → accepted)",
)
async def pick_change(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    data: SlotIn,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> ChangeOut:
    return await flow.pick_change(s, user, project_id, visit_id, change_id, data, now_utc())


@router.post(
    "/projects/{project_id}/visits/{visit_id}/requote",
    response_model=VisitStateOut,
    summary="v3 유효기간 지난 견적서 다시 받기 (D20, 업체 알림)",
)
async def requote(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> VisitStateOut:
    return await flow.requote(s, user, project_id, visit_id, now_utc())


@router.get(
    "/projects/{project_id}/visits/{visit_id}/ics",
    response_class=Response,
    responses=ICS,
    summary="v3 실측 확정 캘린더 파일 (.ics, 주소 없음, 확정 전 404)",
)
async def visit_ics(
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    user: User = Depends(customer_only),
    s: AsyncSession = Session,
) -> Response:
    return await flow.visit_ics(s, user, project_id, visit_id, now_utc())


# ======== v3 실측 일정 (업체) ========


@router.post(
    "/vendor/visits/{visit_id}/window",
    response_model=WindowAnswerOut,
    summary="v3 기간 답하기 (requested → offered, 409 expired · stale)",
)
async def answer_window(
    visit_id: uuid.UUID,
    data: WindowIn,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> WindowAnswerOut:
    return await flow.answer_window(s, vendor, visit_id, data, now_utc())


@router.post(
    "/vendor/visits/{visit_id}/accept",
    response_model=VendorVisitStateOut,
    summary="v3 고객이 고른 날 수락 (picked → booked, 잡아 둔 기한 지남 409 expired)",
)
async def accept_visit(
    visit_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitStateOut:
    return await flow.accept(s, vendor, visit_id, now_utc())


@router.post(
    "/vendor/visits/{visit_id}/propose",
    response_model=VendorVisitStateOut,
    summary="v3 다른 날 제안 (picked → proposed, 반나절 1~3개 · 희망 기간 밖 422)",
)
async def propose_visit(
    visit_id: uuid.UUID,
    data: ProposeIn,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitStateOut:
    return await flow.propose(s, vendor, visit_id, data, now_utc())


@router.post(
    "/vendor/visits/{visit_id}/changes/{change_id}/accept",
    response_model=VendorVisitStateOut,
    summary="v3 일정 바꾸기 요청 받기 (그 반나절이 차 있으면 409 slot_taken)",
)
async def accept_change(
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitStateOut:
    return await flow.accept_change(s, vendor, visit_id, change_id, now_utc())


@router.post(
    "/vendor/visits/{visit_id}/changes/{change_id}/propose",
    response_model=VendorVisitStateOut,
    summary="v3 일정 바꾸기 요청에 다른 날 내기 (open → countered)",
)
async def counter_change(
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    data: SlotsIn,
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorVisitStateOut:
    return await flow.counter_change(s, vendor, visit_id, change_id, data, now_utc())


@router.get(
    "/vendor/schedule",
    response_model=VendorScheduleOut,
    summary="v3 업체 일정 탭: 반나절별 확정 · 잡아 둠 + 동네 · 면적 (from ~ to, 62일 안)",
)
async def vendor_schedule(
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    vendor: User = Depends(approved_vendor),
    s: AsyncSession = Session,
) -> VendorScheduleOut:
    return await flow.vendor_schedule(s, vendor, start, end)

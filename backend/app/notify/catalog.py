"""화면 알림 kind · link 목록 (api.md 9장, routes.md 1장 알림 링크 대상). 문자 · 메일은 보내지 않는다(D15 C).

- kind는 notifications.kind(30자)에 그대로 들어가고, 화면이 아이콘 · 묶음을 고르는 데 쓴다.
- link는 v3 화면 경로 꼴이다. `{pid}` 공사 · `{vid}` 실측 요청 · `{did}` 업체 확정 · `{tid}` 대화 · `{trade}` 공종.
- dedup_key는 `kind:대상 id[:기한]` 꼴로 같은 일은 한 번만 간다(notify.service.add가 막는다).
- 본문(body)에는 고객 이름 · 연락처 · 동 · 호수를 넣지 않는다(행정동 '동'과 헷갈리지 않게 '동 · 호수', CF-02).
"""

from dataclasses import dataclass
from typing import Literal

Who = Literal["customer", "vendor", "admin", "any"]


@dataclass(frozen=True)
class Kind:
    who: Who  # 받는 사람
    link: str  # 화면 경로 꼴
    example: str  # 본문 예 (해요체, 이름 · 연락처 없음)


KINDS: dict[str, Kind] = {
    # ---- 실측 일정 (visit) ----
    "visit_requested": Kind("vendor", "/vendor/requests/{vid}", "새 실측 요청이 왔어요 · 도배"),
    "visit_offered": Kind(
        "customer", "/projects/{pid}/visits/{vid}", "마루와벽이 기간을 보냈어요. 날짜를 골라 주세요"
    ),
    "visit_reply_expired": Kind(
        "customer", "/projects/{pid}/visits", "마루와벽이 48시간 안에 답하지 않았어요"
    ),
    "visit_pick_expired": Kind("vendor", "/vendor/requests/{vid}", "고객이 날짜를 고르지 않았어요"),
    "visit_picked": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 날짜를 골랐어요. 수락해 주세요"
    ),
    "visit_booked": Kind(
        "any", "/projects/{pid}/visits/{vid}", "실측이 12.15(화) 오전으로 정해졌어요"
    ),
    "visit_proposed": Kind(
        "customer", "/projects/{pid}/visits/{vid}", "마루와벽이 다른 날을 제안했어요"
    ),
    "visit_proposal_expired": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 제안한 날을 고르지 않았어요"
    ),
    "visit_hold_released": Kind(
        "customer", "/projects/{pid}/visits/{vid}", "업체가 수락하지 않아 날짜를 다시 골라 주세요"
    ),
    "visit_change_requested": Kind("vendor", "/chat/{tid}", "고객이 실측 일정을 바꾸고 싶어 해요"),
    "visit_change_accepted": Kind("customer", "/chat/{tid}", "업체가 바꾼 일정을 받았어요"),
    "visit_change_countered": Kind("customer", "/chat/{tid}", "업체가 다른 날을 냈어요"),
    "visit_change_expired": Kind("customer", "/chat/{tid}", "업체 답이 없어 원래 일정 그대로예요"),
    "visit_change_withdrawn": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 실측 일정 바꾸기 요청을 거뒀어요"
    ),
    "visit_repicked": Kind(
        "vendor",
        "/vendor/requests/{vid}",
        "고객이 제안한 날 대신 업체 기간에서 다시 고르기로 했어요",
    ),
    "visit_visited": Kind("vendor", "/vendor/requests/{vid}", "고객이 '실측 받았어요'를 눌렀어요"),
    "visit_cancelled": Kind("vendor", "/vendor/requests/{vid}", "고객이 실측 요청을 취소했어요"),
    # v4 반셀프: 확정 전 요청의 '업체에 알릴 것'(직접 할 일)이 바뀜(visit.flow.sync_diy)
    "visit_diy_changed": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 직접 할 일을 바꿨어요: 페인트(문틀 · 몰딩)"
    ),
    "visit_declined": Kind(
        "customer", "/projects/{pid}/visits", "마루와벽이 이번 요청은 못 받아요"
    ),
    "visit_reminder": Kind("any", "/projects/{pid}/visits/{vid}", "내일 오전 실측이에요"),
    "visit_no_show": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 '업체가 안 왔어요'를 눌렀어요"
    ),
    "visit_closed": Kind("vendor", "/vendor/requests/{vid}", "고객이 다른 업체로 정했어요"),
    "visit_vendor_stopped": Kind(
        "customer",
        "/projects/{pid}/visits",
        "마루와벽이 지금 믿집에서 일할 수 없는 업체라 요청이 닫혔어요 · 다른 업체를 담아 주세요",
    ),
    # ---- 실측 견적서 (quote) ----
    "quote_sent": Kind("customer", "/projects/{pid}/quotes", "마루와벽이 실측 견적서를 보냈어요"),
    "quote_resent": Kind(
        "customer", "/projects/{pid}/quotes", "마루와벽이 실측 견적서를 다시 보냈어요"
    ),
    "quote_late": Kind("customer", "/projects/{pid}/visits", "실측 견적서가 늦어요"),
    "quote_valid_soon": Kind(
        "customer", "/projects/{pid}/quotes", "견적서 유효기간이 3일 남았어요"
    ),
    "requote_requested": Kind(
        "vendor", "/vendor/requests/{vid}/quote", "고객이 견적서를 다시 받고 싶어 해요"
    ),
    # ---- 업체 확정 · 공사 (schedule) ----
    "deal_confirmed": Kind("vendor", "/vendor/jobs/{did}", "고객이 업체로 확정했어요"),
    "deal_reselected": Kind(
        "vendor", "/vendor/requests/{vid}", "고객이 업체를 다시 고르기로 했어요"
    ),
    "dates_proposed": Kind("customer", "/projects/{pid}/schedule", "공사 날짜가 왔어요"),
    "dates_requested": Kind("vendor", "/vendor/jobs/{did}", "고객이 다른 날짜를 요청했어요"),
    "dates_accepted": Kind("vendor", "/vendor/jobs/{did}", "고객이 공사 날짜를 수락했어요"),
    "dates_due": Kind("any", "/projects/{pid}/schedule", "공사 날짜가 아직 오지 않았어요"),
    "request_due": Kind("any", "/projects/{pid}/schedule", "다른 날짜 요청에 아직 답이 없어요"),
    "extra_added": Kind("customer", "/projects/{pid}/schedule", "마루와벽이 추가 금액을 알렸어요"),
    "extra_acked": Kind("vendor", "/vendor/jobs/{did}", "고객이 추가 금액에 답했어요"),
    "work_done": Kind("customer", "/projects/{pid}/schedule", "업체가 공사를 끝냈다고 알렸어요"),
    "done_remind": Kind("customer", "/projects/{pid}/schedule", "3일 뒤 자동으로 공사가 끝나요"),
    "work_checked": Kind("vendor", "/vendor/jobs/{did}", "고객이 공사 끝을 확인했어요"),
    "auto_done": Kind("any", "/projects/{pid}/review", "공사가 끝났어요. 리뷰를 남겨 주세요"),
    # ---- 리뷰 · 신고 · 운영 ----
    "review_written": Kind("vendor", "/vendor/reviews", "새 리뷰가 달렸어요"),
    "review_replied": Kind("customer", "/projects/{pid}/review", "업체가 리뷰에 답글을 달았어요"),
    "report_resolved": Kind("any", "/notifications", "신고를 처리했어요"),
    "vendor_warned": Kind("vendor", "/vendor", "믿집 이용 규칙 안내가 있어요"),
    "vendor_muted": Kind("vendor", "/vendor", "관리자가 채팅 쓰기를 잠시 막았어요"),
    "vendor_suspended": Kind("vendor", "/vendor", "업체 기능이 멈췄어요"),
    "link_checked": Kind("vendor", "/vendor/profile?tab=links", "외부 리뷰 링크를 확인했어요"),
    # ---- 업체 심사 (지금 그대로: vendor_{action}) ----
    "vendor_approve": Kind(
        "vendor", "/vendor", "업체 심사가 끝났어요. 이제 믿집에서 일할 수 있어요"
    ),
    "vendor_needs_info": Kind("vendor", "/vendor", "가입 신청에 보완할 것이 있어요"),
    "vendor_reject": Kind("vendor", "/vendor", "가입 신청이 거절됐어요"),
    # ---- v4 비서 먼저 말 걸기(알림 채널, 하루 고객 2 · 업체 3번까지). 업체 링크는 요청 · 공사 화면 ----
    "assistant_nudge": Kind("any", "/projects/{pid}", "결도배 실측 날짜를 아직 고르지 않았어요"),
    # ---- v4 조사 담당: 옛 알림 줄을 보이려고만 둬요. 조사 끝은 대화 줄로만 알리고 새로 만들지 않아요(11-24) ----
    "assistant_research": Kind("customer", "/projects/{pid}", "송파구 도배 업체 조사를 마쳤어요"),
}


def link(kind: str, **ids: object) -> str:
    """kind의 링크 꼴에 id를 넣는다. 꼴에 없는 이름은 무시하고, 빠진 이름은 KeyError."""
    return KINDS[kind].link.format(**ids)


TRADE_NAME = {"dobae": "도배", "mokgong": "목공"}


def work_name(sgg: str | None, emd: str | None, trade: str) -> str:
    """업체 알림 본문 끝에 붙이는 공사 이름: '노원구 상계동 도배' (구 · 동까지만, 동이 없으면 '노원구 도배').
    고객 이름 · 연락처 · 아파트 이름 · 동호수는 넣지 않는다. 실측(visit) · 공사(schedule) 알림이 같이 쓴다."""
    place = " ".join(x for x in (sgg, emd) if x)
    return f"{place} {TRADE_NAME.get(trade, trade)}".strip()

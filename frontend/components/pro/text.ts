// 업체 화면 말(B3). 9판 글 + copy-fixes를 반영했어요. 화면 말은 여기 한곳에 두고, 영어 코드 값은 화면에 보이지 않아요.
// 여러 화면이 같이 쓰는 말이 굳으면 lib/labels.ts(B4)로 옮겨 달라고 부탁해요(verification/b3.md).

/** 업체 화면 7곳 공통 위치 안내(CF-01) */
export const LOC_NOTE = "위치는 동네(구 · 동)까지만 보여요. 동 · 호수 · 연락처는 고객이 채팅으로 알려 줘요.";

/** 다른 날 제안 이유(V07, ProposeIn.reason_code) */
export const PROPOSE_REASONS = [
  { key: "other_site", label: "다른 현장이 있어요" },
  { key: "no_crew", label: "자재 · 사람이 안 돼요" },
  { key: "other", label: "그 밖" },
] as const;

/** 가입 거절 이유(A04 · V22, backend REJECT_CODES). 관리자 창은 '그 밖 · 메모로 적어요' */
export const REJECT_V3 = [
  { key: "info_mismatch", label: "사업자등록증과 신청 정보가 달라요" },
  { key: "closed", label: "휴업 · 폐업한 사업자예요" },
  { key: "wrong_business", label: "도배 업종이 아니에요" },
  { key: "other", label: "그 밖 · 메모로 적어요" },
] as const;
export function rejectLabel(code: string | null | undefined): string | null {
  if (!code || code === "other") return null;
  return REJECT_V3.find((r) => r.key === code)?.label ?? null;
}

/** 리뷰 칩(C39 · V24, VendorReviewRowOut.tags) */
export const REVIEW_TAGS: Record<string, string> = { seam: "이음매가 깔끔해요", on_time: "약속한 날에 끝냈어요", kind: "설명이 친절해요", tidy: "뒷정리가 깔끔해요" };

/** 업체 과세 유형(V15, L02: 간이과세를 더했어요) */
export const TAX_KINDS = [
  { value: "general", label: "일반과세" },
  { value: "simplified", label: "간이과세" },
  { value: "exempt", label: "면세" },
];

/** 실측 견적서 · 추가 금액 부가세 방식(CF-64: 칸 이름 '부가세' + 포함 · 빼고 · 면세) */
export const VAT_MODE_LABEL: Record<string, string> = { included: "포함", excluded: "빼고", exempt: "면세" };

/** 단가표 줄 단위(L01: 줄마다 무엇 1단위당인지 분명히 · CF-41 'M/D' 대신 '1명 하루') */
export const PRICE_UNIT: Record<string, string> = {
  putty: "공급면적 1평(3.3㎡)당",
  paper_hapji: "벽지 1평(3.3㎡)당",
  paper_silk: "벽지 1평(3.3㎡)당",
  material: "공급면적 1평(3.3㎡)당",
  material_hapji: "공급면적 1평(3.3㎡)당",
  labor: "1품(1명 하루)당",
  meal: "1품당",
  truck: "1대당",
};

/**
 * 공사 한 건 기록 줄(V23, LogItemOut.code). 서버 기록(schedule/history.py)은 실측 요청 이력(visit_events) · 견적서 ·
 * 업체 확정 이력(deal_events) · 공사 날짜 · 추가 금액을 같이 줘요. 업체가 읽는 말로 바꾸고, 모르는 코드는 영어를 보이지 않고 '기록이 남았어요'
 */
const LOG_TEXT: Record<string, string> = {
  // 실측 요청(visit_events, 옛 값 full · out_of_area · resent · other_chosen 포함)
  asked: "고객이 실측을 요청했어요",
  re_asked: "고객이 실측을 다시 요청했어요",
  answered: "갈 수 있는 기간을 답했어요",
  declined: "못 받는다고 답했어요",
  full: "못 받는다고 답했어요",
  out_of_area: "못 받는다고 답했어요",
  picked: "고객이 실측 날짜를 골랐어요",
  booked: "실측 날짜가 확정됐어요",
  hold_released: "고객이 잡아 둔 반나절이 풀렸어요",
  proposed: "다른 날을 제안했어요",
  proposal_picked: "고객이 제안한 날을 골랐어요",
  repick: "고객이 기간에서 다시 골랐어요",
  change_requested: "고객이 실측 일정 바꾸기를 요청했어요",
  change_accepted: "실측 일정이 바뀌었어요",
  change_countered: "실측 일정 바꾸기에 다른 날을 냈어요",
  change_expired: "일정 바꾸기 답이 없어 원래 일정 그대로예요",
  change_withdrawn: "고객이 실측 일정 바꾸기를 거뒀어요",
  cancelled: "실측이 취소됐어요",
  visited: "실측을 마쳤어요",
  no_show: "실측에 가지 않은 것으로 남았어요",
  expired: "답할 기한이 지났어요",
  closed: "요청이 닫혔어요",
  requote: "고객이 견적서를 다시 요청했어요",
  chosen: "고객이 이 견적서를 골랐어요",
  other_chosen: "고객이 다른 업체를 골랐어요",
  // 견적서
  quote_sent: "실측 견적서를 보냈어요",
  quote_resent: "실측 견적서를 다시 보냈어요",
  resent: "실측 견적서를 다시 보냈어요",
  // 업체 확정 · 공사 날짜 · 추가 금액 · 공사 끝(deal_events)
  confirmed: "고객이 견적서를 확정했어요",
  dates_sent: "공사 날짜를 보냈어요",
  dates_accepted: "고객이 공사 날짜를 수락했어요",
  dates_changed: "공사 날짜가 바뀌었어요",
  date_requested: "고객이 다른 날짜를 요청했어요",
  work_started: "공사 시작",
  extra_sent: "추가 금액을 보냈어요",
  extra_revised: "추가 금액을 고쳐 보냈어요",
  extra_answered: "고객이 추가 금액에 답했어요",
  extra_approved: "고객이 추가 금액을 승인했어요",
  extra_rejected: "고객이 추가 금액을 거절했어요",
  extra_asked: "고객이 추가 금액을 채팅으로 물었어요",
  done_posted: "공사 끝을 알렸어요",
  fixing: "고객이 고칠 곳을 알렸어요",
  checked: "고객이 공사 끝을 확인했어요",
  auto_done: "7일이 지나 공사가 끝났어요",
  reselected: "고객이 업체를 다시 골랐어요",
};
export const logText = (code: string) => LOG_TEXT[code] ?? "기록이 남았어요";

/** 시공 사례 공간 · 벽지(V16) */
export const SPACES = ["거실", "안방", "작은방", "복도", "주방", "현관", "드레스룸", "그 밖"];
export const PAPERS = [{ value: "basic", label: "실크" }, { value: "economy", label: "합지" }];
export const paperLabel = (v: string | null | undefined) => PAPERS.find((p) => p.value === v)?.label ?? "벽지 미정";


// 업체 화면 예시 데이터(B3). 모양은 API 계약(lib/backend/schema.d.ts · docs/v3/api.md)과 같아요.
// 금액 · 수량 · 날짜 · 기한은 '계산 엔진이 준 값'이라고 보고 적은 예시예요. 화면은 이 값을 그대로 보여요(계산하지 않아요).
// 집 · 업체 · 사람은 9판 예시(마루와벽 · 상계동 69.4㎡ …)를 따른 가상 값이에요.
import type {
  InboxRowV3, JobV3, PricesV3, ProfileV3, VendorApplicationMine, VendorInboxPage, VendorInboxSummary, VendorJobLog,
  VendorQuoteBoard, VendorReviewLinks, VendorReviews, VendorSchedule, VendorVisitV3,
} from "@/lib/api/vendor";

const id = (n: string) => `00000000-0000-4000-8000-${n.padStart(12, "0")}`;
export const VID = {
  sanggye: id("1742"), wolgye: id("2"), changdong: id("3"), gongneung: id("4"), junggye: id("5"),
  hagye: id("6"), sanggye102: id("7"), banghak: id("8"), visited: id("9"),
};
export const DID = { dates: id("d101"), working: id("d102") };
export const TID = { sanggye: id("e001"), hagye: id("e006"), working: id("e102") };

/** 화면마다 9판 '때'에 맞춘 지금 시각(예시 모드에서만) */
export const MOCK_NOW = {
  inbox: "2026-11-18T08:40:00+09:00",
  period: "2026-11-18T09:05:00+09:00",
  accept: "2026-11-18T08:45:00+09:00",
  sched: "2026-12-15T08:00:00+09:00",
  quote: "2026-12-16T10:00:00+09:00",
  dates: "2026-12-17T10:00:00+09:00",
  job: "2027-01-04T08:30:00+09:00",
  reviews: "2027-01-06T09:00:00+09:00",
} as const;

// ───── 가입 신청 ─────
const AREAS = [
  { sido: "seoul", sgg: "노원구", label: "서울 노원구" },
  { sido: "seoul", sgg: "도봉구", label: "서울 도봉구" },
  { sido: "seoul", sgg: "중랑구", label: "서울 중랑구" },
  { sido: "seoul", sgg: "성북구", label: "서울 성북구" },
];
const LICENSE = { id: id("f001"), filename: "사업자등록증.jpg", content_type: "image/jpeg", size: 1258291, created_at: "2026-11-03T10:00:00+09:00" };
const baseApp: VendorApplicationMine = {
  status: "approved", applied_at: "2026-11-03T10:00:00+09:00", approved_at: "2026-11-05T09:30:00+09:00",
  biz_name: "마루와벽", owner_name: "이○○", biz_no: "1234567890", phone: "01012345678", trades: ["dobae"], areas: AREAS,
  license: LICENSE, decision: { action: "approve", code: null, note: null, at: "2026-11-05T09:30:00+09:00" }, open_fields: [],
};
export const MOCK_APPLICATION: Record<"approved" | "pending" | "needs_info" | "rejected", VendorApplicationMine> = {
  approved: baseApp,
  pending: { ...baseApp, status: "pending", approved_at: null, decision: null },
  needs_info: {
    ...baseApp, status: "needs_info", approved_at: null,
    decision: { action: "needs_info", code: "blurry", note: "사진이 흐려서 글자가 안 보여요", at: "2026-11-04T15:20:00+09:00" },
    open_fields: [{ field: "license_file_id", required: true }],
  },
  rejected: {
    ...baseApp, status: "rejected", approved_at: null,
    decision: { action: "reject", code: "info_mismatch", note: "등록번호가 등록증과 달라요", at: "2026-11-04T15:20:00+09:00" },
  },
};

// ───── 작업함 ─────
function row(p: Partial<InboxRowV3> & Pick<InboxRowV3, "id" | "received_at" | "status" | "area_label">): InboxRowV3 {
  return {
    code: "R-" + p.id.slice(-4), trade: "dobae", grade: "basic", region: "서울 노원구", area_name: "상계동", pyeong: null,
    new: false, share_contact: false, closed_at: null, decline_code: null, close_reason: null, waiting_days: null,
    overdue: false, wish_dates: [], extras_pending: 0, work_days: [], ...p,
  };
}
const R = {
  sanggye: row({
    id: VID.sanggye, received_at: "2026-11-17T21:40:00+09:00", status: "requested", new: true, area_label: "노원구 상계동 · 공급 69.4㎡",
    home: "아파트 · 도배 전체 · 빈 집", wish_start: "2026-12-07", wish_end: "2026-12-21", work_wish_on: "2027-01-04",
    estimate_total: 3186150, budget_won: 3000000, state: { icon: "todo", label: "새 실측 요청" },
    next: { label: "기간 답하기", due_at: "2026-11-19T21:40:00+09:00", overdue: false },
  }),
  wolgye: row({
    id: VID.wolgye, received_at: "2026-11-18T08:30:00+09:00", status: "picked", area_label: "노원구 월계동 · 공급 82.6㎡", area_name: "월계동",
    home: "아파트 · 도배 전체 · 사는 중", wish_start: "2026-12-10", wish_end: "2026-12-24", work_wish_on: "2027-01-11",
    estimate_total: 3624000, budget_won: null, state: { icon: "todo", label: "날짜 수락" },
    next: { label: "12.16(수) 오후 수락", due_at: "2026-11-20T08:30:00+09:00", overdue: false },
  }),
  changdong: row({
    id: VID.changdong, received_at: "2026-11-15T20:10:00+09:00", status: "expired", area_label: "도봉구 창동 · 공급 74.4㎡", area_name: "창동", region: "서울 도봉구",
    home: "아파트 · 도배 전체 · 빈 집", wish_start: "2026-12-01", wish_end: "2026-12-12", estimate_total: 3294000, overdue: true,
    state: { icon: "late", label: "답 기한 지남" }, next: { label: "다시 요청이 오면 답하기", due_at: "2026-11-17T20:10:00+09:00", overdue: true },
  }),
  gongneung: row({
    id: VID.gongneung, received_at: "2026-11-16T19:02:00+09:00", status: "offered", area_label: "노원구 공릉동 · 공급 76.0㎡", area_name: "공릉동",
    home: "아파트 · 도배 전체 · 사는 중", wish_start: "2026-12-08", wish_end: "2026-12-20", estimate_total: 3360000,
    state: { icon: "wait", label: "고객 차례" }, next: { label: "고객 답 기다림", due_at: null, overdue: false },
  }),
  junggye: row({
    id: VID.junggye, received_at: "2026-11-02T14:40:00+09:00", status: "quoted", area_label: "노원구 중계동 · 공급 84.9㎡", area_name: "중계동",
    home: "아파트 · 도배 전체 · 빈 집", estimate_total: 3712000, state: { icon: "wait", label: "견적서 보냄" },
    next: { label: "고객 확정 기다림", due_at: null, overdue: false },
  }),
  hagye: row({
    id: VID.hagye, received_at: "2026-11-10T10:15:00+09:00", status: "booked", area_label: "노원구 하계동 · 공급 59.9㎡", area_name: "하계동",
    home: "아파트 · 도배 전체 · 빈 집", estimate_total: 2788000, state: { icon: "ok", label: "실측 확정" },
    next: { label: "12.18(금) 오전 실측", due_at: null, overdue: false },
  }),
  jobDates: row({
    id: VID.visited, received_at: "2026-11-11T09:12:00+09:00", status: "chosen", area_label: "노원구 상계동 · 공급 69.4㎡",
    home: "아파트 · 도배 전체 · 빈 집", deal_id: DID.dates, deal_status: "confirmed", dates_state: "waiting", deal_total: 3267000,
    state: { icon: "todo", label: "공사 날짜 올리기" }, next: { label: "공사 날짜 올리기", due_at: "2026-12-19T18:00:00+09:00", overdue: false },
  }),
  jobWorking: row({
    id: VID.sanggye102, received_at: "2026-10-28T09:12:00+09:00", status: "chosen", area_label: "노원구 상계동 · 공급 69.4㎡",
    home: "아파트 · 도배 전체 · 빈 집", deal_id: DID.working, deal_status: "working", dates_state: "scheduled",
    start_date: "2027-01-04", end_date: "2027-01-05", deal_total: 3267000,
    state: { icon: "ok", label: "공사 중" }, next: { label: "1.4(월) · 1.5(화) 공사", due_at: null, overdue: false },
  }),
  banghak: row({
    id: VID.banghak, received_at: "2026-10-05T11:20:00+09:00", status: "closed", area_label: "도봉구 방학동 · 공급 66.1㎡", area_name: "방학동", region: "서울 도봉구",
    home: "아파트 · 도배 전체 · 사는 중", state: { icon: "done", label: "공사 끝" }, next: null,
  }),
};
export const MOCK_INBOX: Record<"todo" | "waiting" | "sched" | "jobs" | "done", VendorInboxPage> = {
  todo: { items: [R.sanggye, R.wolgye, R.changdong], next_before: null },
  waiting: { items: [R.gongneung, R.junggye], next_before: null },
  sched: { items: [R.hagye], next_before: null },
  jobs: { items: [R.jobWorking, R.jobDates], next_before: null },
  done: { items: [R.banghak], next_before: null },
};
export const MOCK_SUMMARY: VendorInboxSummary = { todo: 3, waiting: 2, sched: 1, jobs: 2, done: 1, recent: { requested: 6, quoted: 3, chosen: 2 } };

// ───── 실측 요청 하나 ─────
function visit(r: InboxRowV3, p: Partial<VendorVisitV3>): VendorVisitV3 {
  const { id, received_at, code, trade, grade, region, area_name, pyeong, status, new: isNew, share_contact, closed_at, decline_code, close_reason, waiting_days,
    area_label, home, wish_start, wish_end, work_wish_on, estimate_total, budget_won, state, next, attempt } = r;
  return {
    id, received_at, code, trade, grade, region, area_name, pyeong, status, new: isNew, share_contact, closed_at, decline_code, close_reason, waiting_days,
    area_label, home, wish_start, wish_end, work_wish_on, estimate_total, budget_won, state, next, attempt,
    area_m2: "69.4", area_basis: "supply", occupied: false, home_text: r.home ?? "", when_text: "", message: null,
    photos: [], photo_labels: [], taken: [], other_windows: [], propose_options: [], open_count: null, capacity: 2, instant_default: true, ...p,
  };
}
const TAKEN_DEC = [
  { visit_id: VID.gongneung, day: "2026-12-15", half: "pm" as const, kind: "booked" as const, seat: 1, area_label: "노원구 공릉동 · 공급 76.0㎡", hold_until: null },
  { visit_id: VID.wolgye, day: "2026-12-16", half: "pm" as const, kind: "hold" as const, seat: 1, area_label: "노원구 월계동 · 공급 82.6㎡", hold_until: "2026-11-20T08:30:00+09:00" },
  { visit_id: VID.hagye, day: "2026-12-18", half: "am" as const, kind: "booked" as const, seat: 1, area_label: "노원구 하계동 · 공급 59.9㎡", hold_until: null },
];
export const MOCK_VISITS: Record<string, VendorVisitV3> = {
  [VID.sanggye]: visit(R.sanggye, {
    photos: [id("p001"), id("p002")], photo_labels: ["거실", "작은방"], taken: TAKEN_DEC, reply_due_at: "2026-11-19T21:40:00+09:00",
  }),
  [VID.wolgye]: visit(R.wolgye, {
    area_m2: "82.6", occupied: true, photos: [id("p003")], photo_labels: ["안방"], instant_default: false,
    window: { start: "2026-12-13", end: "2026-12-18", excluded: [], instant: false, answered_at: "2026-11-17T09:00:00+09:00", pick_due_at: "2026-11-24T09:00:00+09:00" },
    booked: { day: "2026-12-16", half: "pm", kind: "hold", hold_until: "2026-11-20T08:30:00+09:00" },
    taken: TAKEN_DEC,
    propose_options: [
      { day: "2026-12-16", half: "am" }, { day: "2026-12-17", half: "am" }, { day: "2026-12-17", half: "pm" }, { day: "2026-12-18", half: "pm" },
    ],
  }),
  [VID.changdong]: visit(R.changdong, { area_m2: "74.4" }),
  [VID.gongneung]: visit(R.gongneung, {
    area_m2: "76.0", occupied: true,
    window: { start: "2026-12-13", end: "2026-12-18", excluded: ["2026-12-16"], instant: true, answered_at: "2026-11-17T08:10:00+09:00", pick_due_at: "2026-11-24T08:10:00+09:00" },
  }),
  [VID.junggye]: visit(R.junggye, { area_m2: "84.9" }),
  [VID.hagye]: visit(R.hagye, {
    area_m2: "59.9", booked: { day: "2026-12-18", half: "am", kind: "booked", hold_until: null }, thread_id: TID.hagye,
  }),
  [VID.visited]: visit({ ...R.sanggye, id: VID.visited, status: "visited", state: { icon: "todo", label: "견적서 올리기" },
    next: { label: "실측 견적서 올리기", due_at: "2026-12-18T18:00:00+09:00", overdue: false } }, {
    booked: { day: "2026-12-15", half: "am", kind: "booked", hold_until: null }, thread_id: TID.sanggye,
  }),
};

// ───── 일정 탭 (V08, 지금 12.15(화) 08:00) ─────
export const MOCK_SCHEDULE: VendorSchedule = {
  start: "2026-12-15", end: "2026-12-21", capacity: 2,
  items: [
    { visit_id: VID.visited, day: "2026-12-15", half: "am", kind: "booked", seat: 1, area_label: "노원구 상계동 · 공급 69.4㎡", hold_until: null },
    { visit_id: VID.gongneung, day: "2026-12-15", half: "pm", kind: "booked", seat: 1, area_label: "노원구 공릉동 · 공급 76.0㎡", hold_until: null },
    { visit_id: VID.wolgye, day: "2026-12-16", half: "pm", kind: "booked", seat: 1, area_label: "노원구 월계동 · 공급 82.6㎡", hold_until: null },
    { visit_id: VID.changdong, day: "2026-12-17", half: "am", kind: "hold", seat: 1, area_label: "도봉구 창동 · 공급 84.0㎡", hold_until: "2026-12-15T18:00:00+09:00" },
    { visit_id: VID.hagye, day: "2026-12-18", half: "am", kind: "booked", seat: 1, area_label: "노원구 하계동 · 공급 59.9㎡", hold_until: null },
  ],
};

// ───── 실측 견적서 (V10) ─────
export const MOCK_QUOTE: VendorQuoteBoard = {
  visit_id: VID.visited, visit_status: "visited", tax_kind: "general", vat_modes: ["included", "excluded", "exempt"], files_max: 5, days_max: 30,
  draft: {
    id: id("q001"), code: "Q-1742", version: 1, sent_at: null, measured_on: "2026-12-15", entered_amount: 2970000, vat_mode: "excluded",
    supply: 2970000, vat: 297000, total: 3267000, days: 2, valid_until: "2026-12-31", created_at: "2026-12-16T09:00:00+09:00", updated_at: "2026-12-16T09:40:00+09:00",
    files: [{ file_id: id("f101"), filename: "마루와벽_상계동_견적서.pdf", content_type: "application/pdf", size: 421888, sort: 0 }],
    incl_removal: true, incl_waste: true, paper_spec: "LX 베스띠 · 폭 106cm", warranty_months: 12,
  },
  sent: [],
};

// ───── 공사 (V11 · V23) ─────
const quoteBrief = { id: id("q001"), code: "Q-1742", version: 1, total: 3267000, days: 2, valid_until: "2026-12-31", sent_at: "2026-12-16T11:00:00+09:00" };
const noExtras = { trade: "dobae", deal_id: DID.dates, vendor_name: "마루와벽", items: [], ok: { supply: 0, vat: 0, total: 0 }, pending: { supply: 0, vat: 0, total: 0 }, talk: { supply: 0, vat: 0, total: 0 } };
const jobBase = {
  trade: "dobae", confirmed_at: "2026-12-17T09:40:00+09:00", dates_due_at: "2026-12-19T18:00:00+09:00", overdue: false,
  quote: quoteBrief, plan_version: 1, plan_start: null, plan_end: null,
  need: { man_day: "4.0", crew: 2, days: 2, steps: [{ name: "도배", half_days: 4 }] }, others: [], weekend_work: false,
  holidays: [{ day: "2027-01-01", name: "신정" }], requests_left: 2, request_options: [], accepted_crew: null,
  work_done_on: null, contact_until: null, fixing_note: null, done_photos: [], busy_days: [] as string[],
};
export const MOCK_JOBS: Record<string, JobV3> = {
  [DID.dates]: {
    ...jobBase, deal_id: DID.dates, status: "confirmed", start_date: null, end_date: null,
    visit: { ...MOCK_VISITS[VID.visited], status: "chosen" }, dates_state: "waiting", proposal: null, request: null,
    extras: noExtras, can_finish: false, work_days: [], thread_id: TID.sanggye, grand_total: 3267000,
  },
  [DID.working]: {
    ...jobBase, deal_id: DID.working, status: "working", start_date: "2027-01-04", end_date: "2027-01-05",
    visit: { ...MOCK_VISITS[VID.visited], id: VID.sanggye102, status: "chosen" }, dates_state: "scheduled",
    proposal: { id: id("dp01"), start: "2027-01-04", end: "2027-01-05", workdays: 2, crew: 2, method: "app", call_on: null, kind: "initial", reason: null, status: "accepted", request_id: null, changed: false, created_at: "2026-12-17T10:20:00+09:00", decided_at: "2026-12-17T15:10:00+09:00", days: ["2027-01-04", "2027-01-05"] },
    request: null, extras: { ...noExtras, deal_id: DID.working }, accepted_crew: 2, can_finish: true,
    work_days: ["2027-01-04", "2027-01-05"], thread_id: TID.working, grand_total: 3267000, day_no: 1,
  },
};
export const MOCK_JOB_LOG: Record<string, VendorJobLog> = {
  [DID.dates]: [
    { at: "2026-12-17T09:40:00+09:00", actor: "customer", vendor_name: null, trade: "dobae", code: "confirmed", day: null, half: null, day_to: null, amount: 3267000, days: [] },
  ],
  [DID.working]: [
    { at: "2026-12-17T09:40:00+09:00", actor: "customer", vendor_name: null, trade: "dobae", code: "confirmed", day: null, half: null, day_to: null, amount: 3267000, days: [] },
    { at: "2026-12-17T15:10:00+09:00", actor: "customer", vendor_name: null, trade: "dobae", code: "dates_accepted", day: "2027-01-04", half: null, day_to: "2027-01-05", amount: null, days: [] },
    { at: "2027-01-04T08:30:00+09:00", actor: "mijip", vendor_name: null, trade: "dobae", code: "work_started", day: "2027-01-04", half: null, day_to: null, amount: null, days: [] },
  ],
};

// ───── 업체 정보 · 단가 · 링크 ─────
export const MOCK_PROFILE: ProfileV3 = {
  vendor_id: id("a001"), biz_name: "마루와벽", trades: ["dobae"], areas: AREAS, verified_at: "2026-11-05T09:30:00+09:00",
  contact_method: "phone", call_start: "09:00", call_end: "18:00", visit_fee: 0, visit_fee_refund: false, tax_kind: "general",
  owner_name: "이○○", biz_no: "1234567890", opened_on: "2014-03-02", address_area: "서울 노원구", interior_license: "서울 노원구 제2021-12호",
  insurance: "영업배상책임보험", faqs: [], links: [{ label: "인스타그램", url: "https://www.instagram.com/" }],
  portfolio: [
    { id: id("c001"), file_id: id("cf01"), title: "거실 · 실크", space: "거실", paper: "basic", area_m2: "79.3", taken_on: "2026-10-01" },
    { id: id("c002"), file_id: id("cf02"), title: "안방 · 실크", space: "안방", paper: "basic", area_m2: "34.1", taken_on: "2026-10-01" },
    { id: id("c003"), file_id: id("cf03"), title: "작은방 · 합지", space: "작은방", paper: "economy", area_m2: "26.4", taken_on: "2026-09-01" },
    { id: id("c004"), file_id: id("cf04"), title: "복도 · 실크", space: "복도", paper: "basic", area_m2: "12.2", taken_on: "2026-09-01" },
    { id: id("c005"), file_id: id("cf05"), title: "주방 · 합지", space: "주방", paper: "economy", area_m2: "18.7", taken_on: "2026-08-01" },
    { id: id("c006"), file_id: id("cf06"), title: "현관 · 실크", space: "현관", paper: "basic", area_m2: "6.6", taken_on: "2026-08-01" },
  ],
  updated_at: "2026-11-06T20:10:00+09:00", phone: "01012345678", address: null, site_url: null, contact_url: null,
  instant_default: true, visit_capacity: 2, suspended_at: null, intro: "도배만 12년, 이음매를 깔끔하게 해요",
};
export const MOCK_REVIEW_LINKS: VendorReviewLinks = [
  { sort: 1, label: "네이버 플레이스", url: "https://map.naver.com/", status: "shown" },
  { sort: 2, label: "블로그 후기", url: "https://blog.naver.com/", status: "checking" },
];
// 9판 D02 예시(줄 · 받는 법). '공급 69.4㎡ 집이면'과 아래 합계는 계산 엔진 값으로 보고 적었어요.
export const MOCK_PRICES: PricesV3 = {
  rows_ver: "dobae_v3", version: 1, confirmed_at: "2026-11-06T20:30:00+09:00", needs_setup: false,
  lines: [
    { code: "1201", key: "putty", name: "퍼티작업", unit: "평", mode: "price", unit_price: 15000, included_in: null, example_qty: "21.0", example_amount: 315000, warn: null, warn_high: 150000, warn_low: 1500 },
    { code: "1203", key: "paper_hapji", name: "합지", unit: "평", mode: "excluded", unit_price: null, included_in: null, example_qty: "63.0", example_amount: 0, warn: null, warn_high: 46000, warn_low: 460 },
    { code: "1204", key: "paper_silk", name: "실크", unit: "평", mode: "price", unit_price: 9000, included_in: null, example_qty: "63.0", example_amount: 567000, warn: null, warn_high: 98700, warn_low: 987 },
    { code: "1205", key: "material", name: "부자재", unit: "평", mode: "price", unit_price: 12000, included_in: null, example_qty: "21.0", example_amount: 252000, warn: null, warn_high: 120000, warn_low: 1200 },
    { code: "1206", key: "labor", name: "인건비", unit: "품", mode: "price", unit_price: 280000, included_in: null, example_qty: "5.0", example_amount: 1400000, warn: null, warn_high: 2700000, warn_low: 27000 },
    { code: "1207", key: "meal", name: "식대", unit: "품", mode: "included", unit_price: null, included_in: "labor", example_qty: "5.0", example_amount: 0, warn: null, warn_high: 100000, warn_low: 1000 },
    { code: "1208", key: "truck", name: "운송비", unit: "대", mode: "price", unit_price: 50000, included_in: null, example_qty: "1", example_amount: 50000, warn: null, warn_high: 500000, warn_low: 5000 },
  ],
  example: {
    rows_ver: "dobae_v3", set_id: id("s001"), version: 1, grade: "basic", tax_kind: "general",
    lines: [], supply: 2584000, vat: 258400, total: 2842400, vs_standard_pct: "12.0", paper_ok: true,
  },
  example_home: "공급 69.4㎡ 집",
};

// ───── 리뷰 (V24) ─────
export const MOCK_REVIEWS: VendorReviews = {
  rating: { avg: "4.8", count: 6, done_count: 6, tags: { seam: 5, on_time: 4, kind: 3, tidy: 2 } },
  waiting: 1,
  items: [
    { id: id("r001"), rating: 5, tags: ["seam", "on_time"], body: "작은방 곰팡이까지 봐 주셔서 좋았어요.", author_label: "상계동 고객", context_label: "상계동 아파트 · 실크", photos: [], created_at: "2027-01-05T19:20:00+09:00", edited: false, reply: null, deal_id: DID.working, waiting_reply: true, hidden: false },
    { id: id("r002"), rating: 4, tags: ["kind"], body: "결과는 좋았는데 첫날 시작이 1시간 늦었어요. 늦는다고 미리 채팅은 왔어요.", author_label: "도봉구 고객", context_label: "도봉구 아파트 · 합지", photos: [], created_at: "2026-10-12T20:00:00+09:00", edited: false, reply: { body: "늦어서 죄송했어요. 그 뒤로는 전날 도착 시각을 채팅으로 먼저 알려 드려요.", created_at: "2026-10-13T09:10:00+09:00", edited_at: null }, deal_id: null, waiting_reply: false, hidden: false },
  ],
};

/** 가입 · 업체 정보의 다니는 지역 고르기(예시 모드). 실제는 GET /regions */
export const MOCK_REGIONS = [
  { id: "seoul", name: "서울", full: "서울특별시", groups: [{ label: "", prefix: "서울", items: ["강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구"] }] },
  { id: "gyeonggi", name: "경기", full: "경기도", groups: [{ label: "", prefix: "경기", items: ["고양시", "구리시", "남양주시", "부천시", "성남시", "수원시", "안양시", "용인시", "의정부시", "하남시"] }] },
];

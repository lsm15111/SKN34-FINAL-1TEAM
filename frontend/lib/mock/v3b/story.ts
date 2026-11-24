// 9판 이야기 예시 데이터(B2b, 개발에서만). 모양은 lib/backend/schema.d.ts(B1a 계약) 그대로예요.
// 값은 9판 화면 글 · flow.json rules.due(48시간 · 7일 · 실측 + 3일 18:00 · 확정 + 2일 18:00 · 알린 뒤 7일)를 따라요.
// 이 파일이 '서버' 노릇을 해요: 기한 지남(overdue) · 가까움(soon) · 남은 칸 · 합계 같은 값도 여기서 정해 화면에 그대로 넘겨요.
// 공사 id는 진짜 API의 내 공사 id를 받아 그대로 써요(공사 레이아웃이 진짜 공사를 확인해서요).
import type { components } from "@/lib/backend/schema";
import { STEPS, type StepKey } from "./mode";

type S = components["schemas"];

const KEYS: readonly StepKey[] = STEPS.map((s) => s.key);
const uid = (tail: string) => `7a3e1c00-0000-4000-8000-${tail.padStart(12, "0")}`;

export const MOCK_IDS = {
  vendor: { maru: uid("a101"), gyeol: uid("a102"), han: uid("a103") },
  visit: { maru: uid("b101"), gyeol1: uid("b102"), gyeol2: uid("b103"), han: uid("b104") },
  thread: { maru: uid("c101"), gyeol: uid("c102"), wol: uid("c103"), ha: uid("c104") },
  deal: uid("d101"),
  quote: { maru: uid("e101"), gyeol: uid("e102") },
  file: { photo1: uid("f101"), photo2: uid("f102"), pdf: uid("f201"), xls: uid("f202"), extra: uid("f301") },
  change: uid("a201"),
  proposal: uid("a301"),
  dateProposal: uid("a401"),
  dateRequest: uid("a402"),
  extra: uid("a501"),
  review: uid("a601"),
} as const;
const I = MOCK_IDS;

/** 그 단계의 '지금'과 단계 비교 도움 */
export function stepCtx(step: StepKey) {
  const n = Math.max(0, KEYS.indexOf(step));
  const now = STEPS[n].at;
  return {
    step,
    now,
    past: (k: StepKey) => n >= KEYS.indexOf(k),
    within: (a: StepKey, b: StepKey) => n >= KEYS.indexOf(a) && n < KEYS.indexOf(b),
    seen: (t: string) => Date.parse(t) <= Date.parse(now),
  };
}
type Ctx = ReturnType<typeof stepCtx>;

const SEOUL_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
const dayNo = (t: string) => Date.parse(SEOUL_DAY.format(new Date(t))) / 86400000;
/** 서버처럼: 지남 · 가까움(서울 날짜로 오늘 · 내일) */
function due(at: string | null, now: string) {
  if (!at) return { overdue: false, soon: false };
  const overdue = Date.parse(at) <= Date.parse(now);
  return { overdue, soon: !overdue && dayNo(at) - dayNo(now) <= 1 };
}
const nextOf = (c: Ctx, kind: S["VisitNextOut"]["kind"], who: S["VisitNextOut"]["who"], at: string | null): S["VisitNextOut"] => ({ kind, who, due_at: at, ...due(at, c.now) });
const NONE = (c: Ctx) => nextOf(c, "none", "none", null);
const CAN = (p: Partial<S["VisitCanOut"]> = {}): S["VisitCanOut"] => ({ pick: false, cancel: false, again: false, visited: false, change: false, requote: false, ...p });

// ───── 이야기의 고정 값(9판) ─────
export const MOCK_PROJECT = {
  name: "상계동 아파트 도배",
  sido: "서울특별시",
  sgg: "노원구",
  emd: "상계동",
  area_m2: "69.4",
  area_basis: "supply" as const,
  scope: "full" as const,
  occupied: false,
  grade: "basic" as const,
  budget_won: 3000000,
  start_date: "2027-01-04",
};
const WISH = { start: "2026-12-07", end: "2026-12-21" };
const T = {
  sent: "2026-11-17T21:40:00+09:00",
  replyDue: "2026-11-19T21:40:00+09:00",
  maruAnswered: "2026-11-18T09:05:00+09:00",
  maruPickDue: "2026-11-25T09:05:00+09:00",
  maruBooked: "2026-11-18T11:00:00+09:00",
  againAt: "2026-11-19T21:50:00+09:00",
  gyeolAnswered: "2026-11-20T14:50:00+09:00",
  gyeolPickDue: "2026-11-27T14:50:00+09:00",
  gyeolPicked: "2026-11-20T15:10:00+09:00",
  holdUntil: "2026-11-22T15:10:00+09:00",
  proposed: "2026-11-21T10:12:00+09:00",
  proposalDue: "2026-11-23T10:12:00+09:00",
  gyeolBooked: "2026-11-21T10:20:00+09:00",
  changeAt: "2026-12-10T14:20:00+09:00",
  changeDue: "2026-12-12T14:20:00+09:00",
  visitedAt: "2026-12-15T14:00:00+09:00",
  quoteDue: "2026-12-18T18:00:00+09:00",
  maruQuote: "2026-12-16T15:20:00+09:00",
  gyeolQuote: "2026-12-17T09:12:00+09:00",
  confirmed: "2026-12-17T10:05:00+09:00",
  datesDue: "2026-12-19T18:00:00+09:00",
  datesSent: "2026-12-17T15:20:00+09:00",
  dateReq: "2026-12-17T15:40:00+09:00",
  dateReqDue: "2026-12-19T15:40:00+09:00",
  accepted: "2026-12-17T16:00:00+09:00",
  extraAt: "2027-01-04T11:00:00+09:00",
  extraOk: "2027-01-04T11:10:00+09:00",
  donePosted: "2027-01-05T17:00:00+09:00",
  autoDone: "2027-01-12T17:00:00+09:00",
  remindDone: "2027-01-09T17:00:00+09:00", // 올린 때 + 4일(C38 '1월 9일(토)에 한 번 알려 드려요')
  checked: "2027-01-05T17:30:00+09:00",
  reviewed: "2027-01-05T17:40:00+09:00",
};
// 요청 때 고정한 가견적 = 업체 보기 예시(v3a/vendors.ts, 판 2026.11b 줄 규칙: 퍼티 · 운송비는 '선택' 합계 밖)
const MARU = { id: I.vendor.maru, name: "마루와벽", estimate: 2691150 };
const GYEOL = { id: I.vendor.gyeol, name: "결도배", estimate: 2394700 };
const ACTIVE = new Set(["requested", "offered", "picked", "proposed", "booked", "visited", "quoted", "chosen"]);

// ───── 실측 일정 상태판 ─────
function maruRow(c: Ctx): S["BoardRowOut"] | null {
  if (!c.past("sent")) return null;
  const base = { visit_id: I.visit.maru, vendor_id: MARU.id, vendor_name: MARU.name, attempt: 1, estimate_total: MARU.estimate, cancel_code: null, expired_reason: null, proposal: null, change: null, quote: null };
  const win: S["WindowOut"] = { start: "2026-12-13", end: "2026-12-18", excluded: ["2026-12-16"], instant: true, answered_at: T.maruAnswered, pick_due_at: T.maruPickDue };
  const booked: S["BookedOut"] = { day: "2026-12-15", half: "am", kind: "booked", hold_until: null };
  if (!c.past("board1")) return { ...base, status: "requested", next: nextOf(c, "reply", "vendor", T.replyDue), window: null, booked: null, can: CAN({ cancel: true }), thread_id: null };
  if (!c.past("done")) return { ...base, status: "offered", next: nextOf(c, "pick", "customer", T.maruPickDue), window: win, booked: null, can: CAN({ pick: true, cancel: true }), thread_id: null };
  const th = I.thread.maru;
  if (!c.past("change")) return { ...base, status: "booked", next: NONE(c), window: win, booked, can: CAN({ cancel: true, change: true }), thread_id: th };
  if (!c.past("visited")) return { ...base, status: "booked", next: nextOf(c, "change", "vendor", T.changeDue), window: win, booked, change: maruChange(c), can: CAN({ cancel: true }), thread_id: th };
  // 실측 시각이 지났어요(C32). next.due_at은 받았다고 하면 업체가 견적서를 보낼 기한(실측 + 3일 18:00)이에요
  if (!c.past("waiting_quote")) return { ...base, status: "booked", next: nextOf(c, "visit", "customer", T.quoteDue), window: win, booked, can: CAN({ cancel: true, visited: true }), thread_id: th };
  if (!c.past("quotes")) return { ...base, status: "visited", next: nextOf(c, "quote", "vendor", T.quoteDue), window: win, booked, can: CAN({ cancel: true }), thread_id: th };
  const quote: S["QuoteBriefOut"] = { id: I.quote.maru, code: "Q-2612-0101", version: 1, total: 3267000, days: 2, valid_until: "2026-12-31", sent_at: T.maruQuote };
  if (!c.past("confirmed")) return { ...base, status: "quoted", next: nextOf(c, "confirm", "customer", null), window: win, booked, quote, can: CAN(), thread_id: th };
  return { ...base, status: "chosen", next: NONE(c), window: win, booked, quote, can: CAN(), thread_id: th };
}

function maruChange(c: Ctx): S["ChangeOut"] | null {
  if (!c.past("change")) return null;
  return { id: I.change, visit_id: I.visit.maru, from_day: "2026-12-15", from_half: "am", to_day: "2026-12-17", to_half: "am", status: c.past("visited") ? "expired" : "open", due_at: T.changeDue, proposal: null, created_at: T.changeAt };
}

function gyeolRow(c: Ctx): S["BoardRowOut"] | null {
  if (!c.past("sent")) return null;
  const base = { vendor_id: GYEOL.id, vendor_name: GYEOL.name, estimate_total: GYEOL.estimate, cancel_code: null, proposal: null, change: null, quote: null, booked: null, window: null, thread_id: null, expired_reason: null };
  if (!c.past("board_exp")) return { ...base, visit_id: I.visit.gyeol1, attempt: 1, status: "requested", next: nextOf(c, "reply", "vendor", T.replyDue), can: CAN({ cancel: true }) };
  // 서버처럼 끝난 요청은 다음 일이 없고(next none), 지난 기한은 expired_due_at에 와요(업체 차례 · 기다림으로 세지 않게)
  if (!c.past("pick_off")) return { ...base, visit_id: I.visit.gyeol1, attempt: 1, status: "expired", expired_reason: "reply", expired_due_at: T.replyDue, next: NONE(c), can: CAN({ again: true }) };
  const win: S["WindowOut"] = { start: "2026-12-14", end: "2026-12-18", excluded: [], instant: false, answered_at: T.gyeolAnswered, pick_due_at: T.gyeolPickDue };
  const b2 = { ...base, visit_id: I.visit.gyeol2, attempt: 2, window: win };
  if (!c.past("picked")) return { ...b2, status: "offered", next: nextOf(c, "pick", "customer", T.gyeolPickDue), can: CAN({ pick: true, cancel: true }) };
  if (!c.past("board_prop")) return { ...b2, status: "picked", booked: { day: "2026-12-16", half: "am", kind: "hold", hold_until: T.holdUntil }, next: nextOf(c, "accept", "vendor", T.holdUntil), can: CAN({ cancel: true }) };
  // 제안이 오면 고객이 고른 반나절은 풀려요. booked에는 고객이 골랐던 칸이 남아 '고른 12월 16일(수) 오전은 어렵대요'에 써요
  if (!c.past("both_booked")) return { ...b2, status: "proposed", booked: { day: "2026-12-16", half: "am", kind: "hold", hold_until: null }, proposal: gyeolProposal(), next: nextOf(c, "proposal", "customer", T.proposalDue), can: CAN({ pick: true, cancel: true }) };
  const booked: S["BookedOut"] = { day: "2026-12-16", half: "pm", kind: "booked", hold_until: null };
  const th = I.thread.gyeol;
  if (!c.past("quotes")) return { ...b2, status: "booked", booked, next: NONE(c), can: CAN({ cancel: true, change: !c.past("visited") }), thread_id: th };
  const quote: S["QuoteBriefOut"] = { id: I.quote.gyeol, code: "Q-2612-0102", version: 1, total: 2860000, days: 3, valid_until: "2026-12-31", sent_at: T.gyeolQuote };
  if (!c.past("confirmed")) return { ...b2, status: "quoted", booked, quote, next: nextOf(c, "confirm", "customer", null), can: CAN(), thread_id: th };
  return { ...b2, status: "closed", booked, quote, next: NONE(c), can: CAN(), thread_id: th };
}

function gyeolProposal(): S["VisitProposalOut"] {
  return { id: I.proposal, reason_code: "other_site", note: null, slots: [{ day: "2026-12-16", half: "pm" }, { day: "2026-12-17", half: "am" }], status: "open", due_at: T.proposalDue, change_id: null };
}

export function mockBoard(step: StepKey, projectId: string): S["VisitListOut"] {
  const c = stepCtx(step);
  const board = [maruRow(c), gyeolRow(c)].filter((r): r is S["BoardRowOut"] => r !== null);
  const active = board.filter((r) => ACTIVE.has(r.status)).length;
  return {
    project_id: projectId,
    consent_ver: "v3",
    slots_left: { dobae: c.past("sent") ? 3 - active : 1 },
    request_texts: [],
    visits: [],
    head: c.past("sent") ? { trade: "dobae", sent_at: T.sent, wish_start: WISH.start, wish_end: WISH.end, work_wish_on: MOCK_PROJECT.start_date, photos: [I.file.photo1, I.file.photo2], photo_labels: ["거실", "작은방"] } : null,
    board,
  };
}

export function mockDraft(step: StepKey): S["VisitDraftOut"] {
  void step;
  return {
    trade: "dobae",
    wish_start: WISH.start,
    wish_end: WISH.end,
    basis_start: MOCK_PROJECT.start_date,
    vendors: [
      { vendor_id: MARU.id, name: MARU.name, estimate_total: MARU.estimate, grade: "basic" },
      { vendor_id: GYEOL.id, name: GYEOL.name, estimate_total: GYEOL.estimate, grade: "basic" },
    ],
  };
}

// ───── 날짜 고르기 화면 ─────
const day = (d: string, am: boolean, pm: boolean): S["DayHalvesOut"] => ({ day: d, am, pm, am_left: am ? 2 : 0, pm_left: pm ? 2 : 0 });

export function mockPick(step: StepKey, projectId: string, visitId: string): S["VisitPickOut"] | null {
  const c = stepCtx(step);
  const common = { project_id: projectId, trade: "dobae", wish_start: WISH.start, wish_end: WISH.end, work_wish_on: MOCK_PROJECT.start_date, ways: [] as S["VisitPickOut"]["ways"], overlap: true };
  if (visitId === I.visit.han) {
    return {
      ...common, visit_id: visitId, vendor_id: I.vendor.han, vendor_name: "한결인테리어", attempt: 1, no_overlap_reason: "after_work_start", status: "offered", next: nextOf(c, "pick", "customer", "2026-11-25T18:00:00+09:00"),
      window: { start: "2027-01-05", end: "2027-01-09", excluded: [], instant: true, answered_at: "2026-11-18T18:00:00+09:00", pick_due_at: "2026-11-25T18:00:00+09:00" },
      days: ["2027-01-05", "2027-01-06", "2027-01-07", "2027-01-08", "2027-01-09"].map((d) => day(d, true, true)),
      full: [], mine: [], instant: true, recommend: null, overlap: false, ways: ["ask_other", "change_wish", "other_vendor"], booked: null, proposal: null, change: null, thread_id: null,
    };
  }
  const row = visitId === I.visit.maru ? maruRow(c) : visitId === I.visit.gyeol2 || visitId === I.visit.gyeol1 ? gyeolRow(c) : null;
  if (!row || row.visit_id !== visitId) {
    // 앞 시도(결도배 1번째)는 지난 기록으로만 보여요
    if (visitId === I.visit.gyeol1 && c.past("pick_off")) {
      return { ...common, visit_id: visitId, vendor_id: GYEOL.id, vendor_name: GYEOL.name, attempt: 1, status: "expired", next: NONE(c), window: null, days: [], full: [], mine: [], instant: false, recommend: null, booked: null, proposal: null, change: null, thread_id: null };
    }
    return null;
  }
  const maru = visitId === I.visit.maru;
  const days = !row.window ? [] : maru
    ? [day("2026-12-13", true, true), day("2026-12-14", true, true), day("2026-12-15", true, false), day("2026-12-17", true, true), day("2026-12-18", false, true)]
    : [day("2026-12-14", true, true), day("2026-12-15", true, true), day("2026-12-16", true, true), day("2026-12-17", true, true), day("2026-12-18", true, true)];
  const mine: S["MyVisitOut"][] = !maru && c.past("done") ? [{ visit_id: I.visit.maru, vendor_name: MARU.name, day: "2026-12-15", half: "am" }] : maru && c.past("both_booked") ? [{ visit_id: I.visit.gyeol2, vendor_name: GYEOL.name, day: "2026-12-16", half: "pm" }] : [];
  return {
    ...common,
    visit_id: visitId,
    vendor_id: row.vendor_id,
    vendor_name: row.vendor_name,
    attempt: row.attempt,
    status: row.status,
    next: row.next,
    window: row.window,
    days,
    full: maru ? [{ day: "2026-12-15", half: "pm" }] : [],
    mine,
    instant: row.window?.instant ?? false,
    recommend: maru ? { day: "2026-12-15", half: "am", target: MOCK_PROJECT.start_date, basis: "start_minus_20" } : { day: "2026-12-16", half: "am", target: MOCK_PROJECT.start_date, basis: "start_minus_20" },
    booked: row.booked,
    proposal: row.proposal,
    change: maru ? maruChange(c) : null,
    thread_id: row.thread_id,
  };
}

// ───── 채팅 ─────
type Msg = { at: string; from: "customer" | "vendor" | "system"; body?: string; code?: string; ref?: string; warn?: boolean };
const MARU_MSGS: Msg[] = [
  { at: T.maruBooked, from: "system", code: "visit_booked", body: "실측 12.15(화) 오전으로 정해졌어요" },
  { at: "2026-11-18T11:02:00+09:00", from: "vendor", body: "안녕하세요, 마루와벽이에요." },
  { at: "2026-11-18T11:02:00+09:00", from: "vendor", body: "15일 오전 10시쯤 가도 될까요?" },
  { at: "2026-11-18T11:03:00+09:00", from: "customer", body: "네 좋아요. 경비실에 말해 둘게요." },
  { at: "2026-11-18T11:05:00+09:00", from: "customer", body: "○○아파트 101동 1203호예요. 도착 전에 010-1234-5678로 전화 주세요." },
  { at: "2026-12-10T09:40:00+09:00", from: "vendor", body: "네, 15일에 뵐게요." },
  { at: T.changeAt, from: "system", code: "change_requested", ref: I.change },
  { at: "2026-12-15T09:58:00+09:00", from: "vendor", body: "도착했어요. 올라갈게요." },
  { at: T.maruQuote, from: "system", code: "quote_sent", body: "마루와벽이 실측 견적서를 보냈어요" },
  { at: T.maruQuote, from: "vendor", body: "견적서 보냈어요. 궁금한 점은 여기로 물어보세요." },
  { at: "2026-12-16T15:31:00+09:00", from: "customer", body: "네 확인해 볼게요." },
  { at: T.confirmed, from: "system", code: "deal_confirmed", body: "마루와벽으로 확정했어요" },
  { at: T.extraAt, from: "system", code: "extra_sent", ref: I.extra, body: "마루와벽이 추가 금액을 올렸어요" },
  { at: T.donePosted, from: "vendor", body: "공사 끝냈어요. 남은 벽지 1롤은 다용도실에 두었어요." },
];
const GYEOL_MSGS: Msg[] = [
  { at: T.gyeolBooked, from: "system", code: "visit_booked", body: "실측 12.16(수) 오후로 정해졌어요" },
  { at: "2026-11-21T10:31:00+09:00", from: "vendor", body: "네, 그날 뵐게요." },
  { at: "2026-12-16T13:05:00+09:00", from: "vendor", body: "오늘 2시쯤 도착해요." },
  { at: T.gyeolQuote, from: "system", code: "quote_sent", body: "결도배가 실측 견적서를 보냈어요" },
  { at: "2026-12-17T09:13:00+09:00", from: "vendor", body: "견적서 보냈어요. 286만 원이에요." },
  { at: "2026-12-17T09:14:00+09:00", from: "vendor", body: "현금으로 하시면 10% 빼 드려요. 계약은 따로 하시죠.", warn: true },
  { at: "2026-12-17T09:20:00+09:00", from: "customer", body: "견적서는 믿집에서 견줘 볼게요." },
  { at: T.confirmed, from: "system", code: "other_chosen", body: "다른 업체로 확정해서 이 채팅은 읽기만 돼요" },
];
// 업체(마루와벽) 화면에만 있는 다른 고객 대화(V19)
const WOL_MSGS: Msg[] = [
  { at: "2026-11-18T08:30:00+09:00", from: "system", code: "visit_booked", body: "실측 12.16(수) 오후로 정해졌어요" },
  { at: "2026-11-18T08:40:00+09:00", from: "customer", body: "네, 그날 뵐게요." },
];
const HA_MSGS: Msg[] = [
  { at: "2026-11-12T10:00:00+09:00", from: "system", code: "visit_booked", body: "실측 12.18(금) 오전으로 정해졌어요" },
  { at: "2026-11-12T10:20:00+09:00", from: "customer", body: "주차는 지하 2층에 하시면 돼요." },
];

type Role = "customer" | "vendor";
type ThreadDef = { id: string; msgs: Msg[]; opens: StepKey | null; title: Record<Role, string>; area: string; visit: string; label: (c: Ctx) => string; forRole: Role[] };
const THREADS: ThreadDef[] = [
  { id: I.thread.maru, msgs: MARU_MSGS, opens: "done", title: { customer: MARU.name, vendor: "상계동 고객" }, area: "노원구 상계동 69.4㎡", visit: I.visit.maru, forRole: ["customer", "vendor"], label: (c) => (c.past("quotes") ? "실측 끝 · 견적서 옴" : "실측 12.15(화) 오전") },
  { id: I.thread.gyeol, msgs: GYEOL_MSGS, opens: "both_booked", title: { customer: GYEOL.name, vendor: "상계동 고객" }, area: "노원구 상계동 69.4㎡", visit: I.visit.gyeol2, forRole: ["customer"], label: (c) => (c.past("quotes") ? "실측 끝 · 견적서 옴" : "실측 12.16(수) 오후") },
  { id: I.thread.wol, msgs: WOL_MSGS, opens: null, title: { customer: "", vendor: "월계동 고객" }, area: "노원구 월계동 82.6㎡", visit: uid("b201"), forRole: ["vendor"], label: () => "실측 12.16(수) 오후" },
  { id: I.thread.ha, msgs: HA_MSGS, opens: null, title: { customer: "", vendor: "하계동 고객" }, area: "노원구 하계동 59.9㎡", visit: uid("b202"), forRole: ["vendor"], label: () => "실측 12.18(금) 오전" },
];

function visibleMsgs(c: Ctx, t: ThreadDef): Msg[] { return t.msgs.filter((m) => c.seen(m.at)); }
function toOut(t: ThreadDef, m: Msg, seq: number, role: Role): S["MessageOut"] {
  const from = m.from === "system" ? "system" : m.from === role ? "me" : "them";
  return {
    seq, id: uid(`${t.id.slice(-4)}${String(seq).padStart(4, "0")}`), from, kind: m.from === "system" ? "system" : "text",
    body: m.body ?? null, file_id: null, system_code: m.code ?? null, ref_id: m.ref ?? null,
    warn: role === "customer" && m.warn ? "offsite" : null, at: m.at,
  };
}
/** 읽음: 상대 글은 지금보다 3시간 넘게 지났거나 내가 그 뒤에 답했으면 읽은 것으로 봐요 */
function readSeq(c: Ctx, msgs: S["MessageOut"][]): number {
  let read = 0;
  msgs.forEach((m, i) => {
    const later = msgs.slice(i + 1).some((x) => x.from === "me");
    if (m.from !== "them" || later || Date.parse(c.now) - Date.parse(m.at) > 3 * 3600_000) read = m.seq;
  });
  return read;
}
function openFor(c: Ctx, t: ThreadDef) { return t.opens === null || c.past(t.opens); }
function roOf(c: Ctx, t: ThreadDef): S["ThreadOut"]["ro_reason"] { return t.id === I.thread.gyeol && c.past("confirmed") ? "other_chosen" : null; }

export function mockThreads(step: StepKey, role: Role): S["ThreadRowOut"][] {
  const c = stepCtx(step);
  return THREADS.filter((t) => t.forRole.includes(role) && openFor(c, t))
    .map((t) => {
      const msgs = visibleMsgs(c, t).map((m, i) => toOut(t, m, i + 1, role));
      const last = msgs[msgs.length - 1];
      const read = readSeq(c, msgs);
      const ro = roOf(c, t);
      return {
        thread_id: t.id,
        title: t.title[role],
        visit_label: t.label(c),
        last: last ? { kind: last.kind, preview: last.body, at: last.at } : null,
        unread: msgs.filter((m) => m.seq > read && m.from === "them").length,
        status: ro ? "read_only" as const : "open" as const,
        ro_reason: ro,
      };
    })
    .sort((a, b) => Date.parse(b.last?.at ?? "0") - Date.parse(a.last?.at ?? "0"));
}

export function mockThread(step: StepKey, threadId: string, role: Role, projectId: string): S["ThreadOut"] | null {
  const c = stepCtx(step);
  const t = THREADS.find((x) => x.id === threadId && x.forRole.includes(role));
  if (!t || !openFor(c, t)) return null;
  const msgs = visibleMsgs(c, t).map((m, i) => toOut(t, m, i + 1, role));
  const ro = roOf(c, t);
  const isMaru = t.id === I.thread.maru;
  const booked = isMaru ? c.within("done", "visited") : c.within("both_booked", "quotes");
  return {
    thread_id: t.id,
    title: t.title[role],
    area_label: t.area,
    visit_id: t.visit,
    deal_id: isMaru && c.past("confirmed") ? I.deal : null,
    project_id: role === "customer" ? projectId : null,
    status: ro ? "read_only" : "open",
    ro_reason: ro,
    blocked: false,
    last_seq: msgs.length,
    read_seq: readSeq(c, msgs),
    can: {
      write: !ro,
      change_request: role === "customer" && booked && !(isMaru && c.within("change", "visited")),
      cancel: role === "customer" && !ro && (isMaru ? c.within("done", "quotes") : c.within("both_booked", "quotes")),
      report: true,
    },
    links: role === "customer"
      ? { quote: c.past("quotes") ? `/projects/${projectId}/quotes` : null, project: `/projects/${projectId}` }
      : { quote: c.past("waiting_quote") && isMaru ? `/vendor/requests/${t.visit}/quote` : null, project: isMaru && c.past("confirmed") ? `/vendor/jobs/${I.deal}` : null },
  };
}

export function mockMessages(step: StepKey, threadId: string, role: Role, after?: number): S["MessageOut"][] {
  const c = stepCtx(step);
  const t = THREADS.find((x) => x.id === threadId && x.forRole.includes(role));
  if (!t || !openFor(c, t)) return [];
  return visibleMsgs(c, t).map((m, i) => toOut(t, m, i + 1, role)).filter((m) => after === undefined || m.seq > after);
}

// ───── 실측 견적서 비교 · 확정 ─────
const RATING = { maru: { avg: "4.8", count: 5, done_count: 12, tags: {} }, gyeol: { avg: "4.7", count: 3, done_count: 7, tags: {} } };
function maruQuote(): S["VendorQuoteOut"] {
  return {
    id: I.quote.maru, code: "Q-2612-0101", version: 1, sent_at: T.maruQuote, measured_on: "2026-12-15", entered_amount: 2970000, vat_mode: "excluded",
    supply: 2970000, vat: 297000, total: 3267000, days: 2, valid_until: "2026-12-31", created_at: T.maruQuote, updated_at: T.maruQuote,
    files: [{ file_id: I.file.pdf, filename: "마루와벽_상계동_견적서.pdf", content_type: "application/pdf", size: 421888, sort: 0 }],
    incl_removal: true, incl_waste: true, paper_spec: "LX 베스띠", warranty_months: 12,
  };
}
function gyeolQuote(): S["VendorQuoteOut"] {
  return {
    id: I.quote.gyeol, code: "Q-2612-0102", version: 1, sent_at: T.gyeolQuote, measured_on: "2026-12-16", entered_amount: 2860000, vat_mode: "included",
    supply: 2600000, vat: 260000, total: 2860000, days: 3, valid_until: "2026-12-31", created_at: T.gyeolQuote, updated_at: T.gyeolQuote,
    files: [{ file_id: I.file.xls, filename: "결도배 견적서.xlsx", content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", size: 38912, sort: 0 }],
    incl_removal: true, incl_waste: false, paper_spec: null, warranty_months: 6,
  };
}
function mockDeal(c: Ctx): S["DealOut"] | null {
  if (!c.past("confirmed")) return null;
  const scheduled = c.past("scheduled");
  const status = c.past("review") ? "done" : c.past("done_ok") ? "checking" : scheduled ? "scheduled" : "confirmed";
  return {
    id: I.deal, trade: "dobae", status, vendor_id: MARU.id, vendor_name: MARU.name, owner_name: null, visit_id: I.visit.maru,
    quote: { id: I.quote.maru, code: "Q-2612-0101", version: 1, total: 3267000, days: 2, valid_until: "2026-12-31", sent_at: T.maruQuote },
    confirmed_at: T.confirmed, dates_due_at: T.datesDue, ...due(scheduled ? null : T.datesDue, c.now),
    start_date: scheduled ? "2027-01-04" : null, end_date: scheduled ? "2027-01-05" : null,
    work_done_on: c.past("done_ok") ? "2027-01-05" : null, contact_until: null, fixing_note: null,
    work_days: scheduled ? ["2027-01-04", "2027-01-05"] : [],
    done_note: c.past("done_ok") ? "남은 벽지 1롤은 다용도실에 두었어요" : null,
    done_posted_at: c.past("done_ok") ? T.donePosted : null,
    auto_done_at: c.past("done_ok") ? T.autoDone : null,
    done_remind_at: c.past("done_ok") ? T.remindDone : null,
    review_open: c.past("review") && !c.past("reviewed"),
    review_id: c.past("reviewed") ? I.review : null,
    thread_id: I.thread.maru,
    done_photos: [],
    grand_total: c.past("extra_ok") ? 3322000 : 3267000,
  };
}

export function mockCompare(step: StepKey, projectId: string): S["CompareDealOut"] {
  const c = stepCtx(step);
  const rows: S["CompareRowOut"][] = [];
  const g = gyeolRow(c);
  const m = maruRow(c);
  const quoted = (st?: string) => st === "quoted" || st === "chosen" || st === "closed";
  if (g && c.past("both_booked")) rows.push({
    visit_id: g.visit_id, vendor_id: GYEOL.id, vendor_name: GYEOL.name, status: g.status, requested_at: T.againAt, seen_ver: quoted(g.status) ? 1 : null,
    latest: quoted(g.status) ? gyeolQuote() : null, history: [], changed: [], estimate_total: GYEOL.estimate, vs_standard: null, vs_direction: null,
    expired: false, diff_vs_estimate: quoted(g.status) ? 465300 : null, visit_day: "2026-12-16", valid_soon: false, valid_soon_at: quoted(g.status) ? ["2026-12-28T18:00:00+09:00", "2026-12-30T18:00:00+09:00"] : [], requote_at: null, rating: RATING.gyeol,
  });
  if (m && c.past("done")) rows.push({
    visit_id: m.visit_id, vendor_id: MARU.id, vendor_name: MARU.name, status: m.status, requested_at: T.sent, seen_ver: quoted(m.status) ? 1 : null,
    latest: quoted(m.status) ? maruQuote() : null, history: [], changed: [], estimate_total: MARU.estimate, vs_standard: null, vs_direction: null,
    expired: false, diff_vs_estimate: quoted(m.status) ? 575850 : null, visit_day: "2026-12-15", valid_soon: false, valid_soon_at: quoted(m.status) ? ["2026-12-28T18:00:00+09:00", "2026-12-30T18:00:00+09:00"] : [], requote_at: null, rating: RATING.maru,
  });
  return {
    project_id: projectId, trade: "dobae", standard_total: 1974069, formula_ver: "dobae-v3.1", price_ver: "2026H2", computed_at: c.now,
    sent_counts: { dobae: rows.filter((r) => r.latest).length }, vendors: rows, deal: mockDeal(c),
    // 두 곳 이상 받았을 때 가장 큰 합계 − 가장 작은 합계(서버 계산 엔진 값을 흉내)
    gap_total: rows.filter((r) => r.latest).length >= 2 ? 407000 : null,
  };
}

// ───── 공사 날짜 · 추가 금액 · 공사 끝 ─────
export function mockSchedule(step: StepKey, projectId: string): S["ScheduleOut"] {
  const c = stepCtx(step);
  const deal = mockDeal(c);
  const trades: S["TradeDatesOut"][] = [];
  if (deal) {
    const proposal: S["ProposalOut"] | null = c.past("dates") ? {
      id: I.dateProposal, start: "2027-01-04", end: "2027-01-05", workdays: 2, crew: 2, method: "app", call_on: null, kind: "first", reason: null,
      status: c.past("scheduled") ? "accepted" : "pending", request_id: null, changed: false, created_at: T.datesSent, decided_at: c.past("scheduled") ? T.accepted : null,
      days: ["2027-01-04", "2027-01-05"],
    } : null;
    const requested = c.within("date_req", "scheduled");
    const extraOn = c.past("extra");
    const approved = c.past("extra_ok");
    const extra: S["ExtraOut"] = {
      id: I.extra, title: "곰팡이 방지 처리", reason: "작은방 벽 1면에 곰팡이가 있어요", vat_mode: "excluded", entered_amount: 50000, supply: 50000, vat: 5000, total: 55000,
      ack: approved ? "ok" : "pending", acked_at: approved ? T.extraOk : null, created_at: T.extraAt,
      photos: [{ file_id: I.file.extra, filename: "작은방.jpg", content_type: "image/jpeg", size: 182000 }],
      answer: approved ? "approved" : "pending", group_id: null, version: 1, superseded: false,
      // 승인하면 공사 금액(확정 + 이 금액). 답을 기다리는 판만 줘요
      after_total: approved ? null : 3322000,
    };
    const money = (n: number): S["MoneyOut"] => ({ supply: Math.round(n / 1.1), vat: n - Math.round(n / 1.1), total: n });
    trades.push({
      deal,
      dates_state: c.past("scheduled") ? "scheduled" : requested ? "requested" : c.past("dates") ? "proposed" : "waiting",
      proposal,
      request: requested ? { id: I.dateRequest, wish_dates: ["2027-01-11", "2027-01-18"], reason: "이사 날짜가 바뀌었어요", due_at: T.dateReqDue, ...due(T.dateReqDue, c.now), status: "open", created_at: T.dateReq } : null,
      requests_left: requested ? 1 : 2,
      fit: null,
      start_options: [{ start: "2027-01-11", end: "2027-01-12" }, { start: "2027-01-18", end: "2027-01-19" }, { start: "2027-01-25", end: "2027-01-26" }],
      extras: {
        trade: "dobae", deal_id: I.deal, vendor_name: MARU.name, items: extraOn ? [extra] : [],
        ok: money(approved ? 55000 : 0), pending: money(extraOn && !approved ? 55000 : 0), talk: money(0),
        grand_total: approved ? 3322000 : 3267000,
      },
    });
  }
  // 지금 다른 날짜를 요청하면 업체 기한(요청 + 48시간, 서버 계산). 날짜가 올라와 고를 수 있을 때만
  const canAsk = c.past("dates") && !c.past("date_req") && !c.past("scheduled");
  return { project_id: projectId, weekend_work: false, holidays: [{ day: "2027-01-01", name: "신정" }], final_version: c.past("scheduled") ? 1 : 0, trades, request_due_preview: canAsk ? "2026-12-19T15:40:00+09:00" : null };
}

// ───── 한 공사 화면 · 기록 · 내 공사 ─────
function projectSteps(c: Ctx): { current: number; phase: S["OverviewOut"]["phase"] } {
  if (c.past("review")) return { current: 5, phase: "done" };
  if (c.past("scheduled")) return { current: 5, phase: "work" };
  if (c.past("quotes")) return { current: 5, phase: "progress" };
  if (c.past("visited")) return { current: 4, phase: "progress" };
  return { current: 3, phase: "progress" };
}
const STEP_KEYS6: S["StepOut"]["key"][] = ["house", "standard", "pick", "visit", "deal", "dates"];
const STEP_LABEL6 = ["기본 정보", "표준견적서", "업체 담기", "실측 일정", "실측", "실측 뒤"];
const stepList = (current: number): S["StepOut"][] => STEP_KEYS6.map((key, i) => ({ key, label: STEP_LABEL6[i], state: i < current ? "done" : i === current ? "now" : "todo", on: null, count: null }));

/** 지금 할 일(서버가 정해 줘요) */
function todoOf(c: Ctx, pid: string): S["TodoOut"] | null {
  const v = (x: string) => `/projects/${pid}/visits/${x}`;
  if (!c.past("sent")) return { code: "request", trade: "dobae", text: "담은 2곳에 실측 일정을 요청할 차례예요", action: "실측 일정 요청", link: `/projects/${pid}/visits/new`, days: [] };
  if (!c.past("board1")) return { code: "wait_reply", trade: "dobae", text: "두 곳이 기간을 답할 때까지 기다려요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("done")) return { code: "pick", trade: "dobae", text: "마루와벽이 기간을 보냈어요", action: "마루와벽 날짜 고르기", link: v(I.visit.maru), days: [] };
  if (!c.past("board_exp")) return { code: "wait_reply", trade: "dobae", text: "결도배가 답할 때까지 기다려요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("pick_off")) return { code: "again", trade: "dobae", text: "결도배가 답하지 않았어요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("picked")) return { code: "pick", trade: "dobae", text: "결도배가 기간을 보냈어요", action: "결도배 날짜 고르기", link: v(I.visit.gyeol2), days: [] };
  if (!c.past("board_prop")) return { code: "wait_accept", trade: "dobae", text: "결도배가 수락할 때까지 기다려요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("both_booked")) return { code: "proposal", trade: "dobae", text: "결도배가 다른 날을 제안했어요", action: "결도배가 제안한 날 보기", link: v(I.visit.gyeol2), days: [] };
  if (!c.past("visited")) return { code: "visit", trade: "dobae", text: "실측 날짜가 모두 정해졌어요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("waiting_quote")) return { code: "visited", trade: "dobae", text: "마루와벽 실측을 받으셨어요?", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("quotes")) return { code: "wait_quote", trade: "dobae", text: "실측 견적서를 기다려요", action: "실측 일정 보기", link: `/projects/${pid}/visits`, days: [] };
  if (!c.past("confirmed")) return { code: "confirm", trade: "dobae", text: "실측 견적서 2곳이 모두 왔어요", action: "견적서 비교", link: `/projects/${pid}/quotes`, days: [] };
  if (!c.past("dates")) return { code: "wait_dates", trade: "dobae", text: "마루와벽이 공사 날짜를 올릴 때까지 기다려요", action: "공사 날짜 보기", link: `/projects/${pid}/schedule`, days: [] };
  if (!c.past("date_req")) return { code: "dates", trade: "dobae", text: "마루와벽이 공사 날짜를 올렸어요", action: "공사 날짜 보기", link: `/projects/${pid}/schedule`, days: ["2027-01-04", "2027-01-05"] };
  if (!c.past("scheduled")) return { code: "wait_dates", trade: "dobae", text: "마루와벽이 새 날짜를 올릴 때까지 기다려요", action: "공사 날짜 보기", link: `/projects/${pid}/schedule`, days: [] };
  if (!c.past("extra")) return { code: "plan", trade: "dobae", text: "확정 공정표가 생겼어요", action: "확정 공정표 보기", link: `/projects/${pid}/plan`, days: [] };
  if (!c.past("extra_ok")) return { code: "extra", trade: "dobae", text: "마루와벽이 추가 금액을 올렸어요", action: "추가 금액 보기", link: `/projects/${pid}/schedule?view=extra`, days: [] };
  if (!c.past("done_ok")) return { code: "work", trade: "dobae", text: "공사 중이에요", action: "공사 날짜 보기", link: `/projects/${pid}/schedule`, days: [] };
  if (!c.past("review")) return { code: "check", trade: "dobae", text: "마루와벽이 공사를 끝냈대요", action: "공사 끝 확인", link: `/projects/${pid}/schedule?view=done`, days: [] };
  if (!c.past("reviewed")) return { code: "review", trade: "dobae", text: "공사가 끝났어요", action: "리뷰 쓰기", link: `/projects/${pid}/review`, days: [] };
  return null;
}

function vendorSteps(c: Ctx): S["VendorStepOut"][] {
  return [maruRow(c), gyeolRow(c)].filter((r): r is S["BoardRowOut"] => r !== null)
    .map((r) => ({ visit_id: r.visit_id, vendor_id: r.vendor_id, vendor_name: r.vendor_name, trade: "dobae", status: r.status, next: r.next }));
}

function afterSteps(c: Ctx): S["AfterStepOut"][] {
  const keys: S["AfterStepOut"]["key"][] = ["quote", "confirm", "dates", "work", "check"];
  const labels = ["견적서 비교", "업체 확정", "공사 날짜", "공사", "끝 확인"];
  const now = c.past("review") ? 5 : c.past("done_ok") ? 4 : c.past("scheduled") ? 3 : c.past("confirmed") ? 2 : 0;
  return keys.map((key, i) => ({ key, label: labels[i], state: i < now ? "done" : i === now ? "now" : "todo" }));
}

export function mockOverview(step: StepKey, projectId: string): S["OverviewOut"] {
  const c = stepCtx(step);
  const { current, phase } = projectSteps(c);
  const deal = mockDeal(c);
  const todo = todoOf(c, projectId);
  return {
    project_id: projectId, code: "MJ-2611-2692", region: "서울 노원구", sgg: "노원구", pyeong: null, phase, todo,
    next: deal?.start_date ? { kind: "start", trade: "dobae", day: deal.start_date, at: null } : null,
    trades: [{
      trade: "dobae", vendor_name: deal?.vendor_name ?? null, deal_id: deal?.id ?? null, deal_status: deal?.status ?? null, phase, current,
      steps: stepList(current), todo: todo ?? { code: "none", trade: "dobae", text: "", action: "", link: `/projects/${projectId}`, days: [] }, overdue: false,
      start_date: deal?.start_date ?? null, end_date: deal?.end_date ?? null, proposed_start: null, proposed_end: null, next: null,
    }],
    money: { total: deal ? 3267000 : 1974069, by_trade: [{ trade: "dobae", total: deal ? 3267000 : 1974069, source: deal ? "deal" : "standard" }], all_confirmed: Boolean(deal), budget: null },
    period: { kind: c.past("scheduled") ? "final" : "expected", start: "2027-01-04", end: "2027-01-05", work_days: 2 },
    contacts: [], checks: [{ key: "office", label: "관리사무소에 공사 신고하기", done: false, done_at: null }],
    after_steps: afterSteps(c),
    vendors: vendorSteps(c),
  };
}

type Log = { at: string; actor: S["LogItemOut"]["actor"]; vendor?: string; code: string; day?: string; half?: "am" | "pm"; day_to?: string; half_to?: "am" | "pm"; days?: string[]; amount?: number };
const LOG: Log[] = [
  { at: T.sent, actor: "customer", vendor: MARU.name, code: "asked" },
  { at: T.sent, actor: "customer", vendor: GYEOL.name, code: "asked" },
  { at: T.maruAnswered, actor: "vendor", vendor: MARU.name, code: "answered", day: "2026-12-13", day_to: "2026-12-18" },
  { at: T.maruBooked, actor: "customer", vendor: MARU.name, code: "booked", day: "2026-12-15", half: "am" },
  { at: T.replyDue, actor: "mijip", vendor: GYEOL.name, code: "expired" },
  { at: T.againAt, actor: "customer", vendor: GYEOL.name, code: "re_asked" },
  { at: T.gyeolAnswered, actor: "vendor", vendor: GYEOL.name, code: "answered", day: "2026-12-14", day_to: "2026-12-18" },
  { at: T.gyeolPicked, actor: "customer", vendor: GYEOL.name, code: "picked", day: "2026-12-16", half: "am" },
  { at: T.proposed, actor: "vendor", vendor: GYEOL.name, code: "proposed", day: "2026-12-16", half: "pm", day_to: "2026-12-17", half_to: "am" },
  { at: T.gyeolBooked, actor: "customer", vendor: GYEOL.name, code: "proposal_picked", day: "2026-12-16", half: "pm" },
  { at: T.changeAt, actor: "customer", vendor: MARU.name, code: "change_requested", day: "2026-12-17", half: "am" },
  { at: T.changeDue, actor: "mijip", vendor: MARU.name, code: "change_expired" },
  { at: T.visitedAt, actor: "customer", vendor: MARU.name, code: "visited" },
  { at: T.maruQuote, actor: "vendor", vendor: MARU.name, code: "quote_sent", amount: 3267000 },
  { at: T.gyeolQuote, actor: "vendor", vendor: GYEOL.name, code: "quote_sent", amount: 2860000 },
  { at: T.confirmed, actor: "customer", vendor: MARU.name, code: "chosen" },
  { at: T.datesSent, actor: "vendor", vendor: MARU.name, code: "dates_sent", day: "2027-01-04", day_to: "2027-01-05", days: ["2027-01-04", "2027-01-05"] },
  { at: T.dateReq, actor: "customer", vendor: MARU.name, code: "date_requested" },
  { at: T.accepted, actor: "customer", vendor: MARU.name, code: "dates_accepted" },
  { at: T.extraAt, actor: "vendor", vendor: MARU.name, code: "extra_sent", amount: 55000 },
  { at: T.extraOk, actor: "customer", vendor: MARU.name, code: "extra_approved", amount: 55000 },
  { at: T.donePosted, actor: "vendor", vendor: MARU.name, code: "work_done" },
  { at: T.checked, actor: "customer", vendor: MARU.name, code: "done" },
];

export function mockLog(step: StepKey): S["LogItemOut"][] {
  const c = stepCtx(step);
  // 다른 날짜 요청은 곁가지 단계(date_req)에서만 보여요(수락한 이야기에는 없어요)
  return LOG.filter((l) => c.seen(l.at) && (l.code !== "date_requested" || c.within("date_req", "scheduled")))
    .map((l) => ({ at: l.at, actor: l.actor, vendor_name: l.vendor ?? null, trade: "dobae", code: l.code, day: l.day ?? null, half: l.half ?? null, day_to: l.day_to ?? null, half_to: l.half_to ?? null, days: l.days ?? [], amount: l.amount ?? null }));
}

// 내 공사 목록의 current는 API처럼 1부터(1~6, MyProjectOut). 화면이 stepIndex로 띠 칸(0부터)으로 바꿔요
// 업체는 API처럼 살아 있는 요청만(답 없음 · 닫힘은 빼요, schedule.service _vendor_steps live_only)
export function mockMyProjects(step: StepKey, ids: string[]): S["MyProjectOut"][] {
  const c = stepCtx(step);
  const out: S["MyProjectOut"][] = [];
  if (ids[0]) {
    const { current, phase } = projectSteps(c);
    out.push({
      id: ids[0], code: "MJ-2611-2692", region: "서울 노원구", size: { band: null, basis: "supply", m2: "69.4" }, trades: ["dobae"], created_at: "2026-11-17T21:00:00+09:00",
      phase, current: current + 1, todo: todoOf(c, ids[0]), next: null, updated_at: c.now, grades: { dobae: "basic" }, emd: "상계동", vendors: vendorSteps(c).filter((v) => ACTIVE.has(v.status)),
    });
  }
  if (ids[1]) {
    out.push({
      id: ids[1], code: "MJ-2611-1810", region: "서울 노원구", size: { band: null, basis: "supply", m2: "79.3" }, trades: ["dobae"], created_at: "2026-11-10T20:00:00+09:00",
      phase: "estimate", current: 3, todo: { code: "shortlist", trade: "dobae", text: "업체를 담을 차례예요", action: "업체 보기", link: `/projects/${ids[1]}/vendors`, days: [] },
      next: null, updated_at: "2026-11-10T20:30:00+09:00", grades: { dobae: "basic" }, emd: "중계동", vendors: [],
    });
  }
  return out;
}

// ───── 알림 ─────
type Note = { at: string; kind: string; body: string; link: (pid: string) => string; role: Role };
const NOTES: Note[] = [
  { at: "2026-11-18T09:12:00+09:00", kind: "visit_offered", body: "마루와벽이 기간을 보냈어요 · 날짜를 골라 주세요", link: (p) => `/projects/${p}/visits/${I.visit.maru}`, role: "customer" },
  { at: T.maruBooked, kind: "visit_booked", body: "실측이 12.15(화) 오전으로 정해졌어요", link: (p) => `/projects/${p}/visits/${I.visit.maru}`, role: "customer" },
  { at: T.replyDue, kind: "visit_expired", body: "결도배가 답하지 않았어요", link: (p) => `/projects/${p}/visits`, role: "customer" },
  { at: T.gyeolAnswered, kind: "visit_offered", body: "결도배가 기간을 보냈어요 · 날짜를 골라 주세요", link: (p) => `/projects/${p}/visits/${I.visit.gyeol2}`, role: "customer" },
  { at: T.proposed, kind: "visit_proposed", body: "결도배가 다른 날을 제안했어요", link: (p) => `/projects/${p}/visits`, role: "customer" },
  { at: "2026-12-14T18:00:00+09:00", kind: "visit_reminder", body: "내일 오전 실측이에요 · 마루와벽 · 동 · 호수 보냄", link: (p) => `/projects/${p}/visits`, role: "customer" },
  { at: "2026-12-15T18:00:00+09:00", kind: "visit_reminder", body: "내일 오후 실측이에요 · 결도배 동 · 호수를 아직 보내지 않았어요 · 채팅에서 보내요", link: () => `/chat/${I.thread.gyeol}`, role: "customer" },
  { at: T.maruQuote, kind: "quote_sent", body: "마루와벽이 실측 견적서를 보냈어요", link: (p) => `/projects/${p}/quotes`, role: "customer" },
  { at: T.gyeolQuote, kind: "quote_sent", body: "결도배가 실측 견적서를 보냈어요", link: (p) => `/projects/${p}/quotes`, role: "customer" },
  { at: T.datesSent, kind: "dates_sent", body: "마루와벽이 공사 날짜를 올렸어요", link: (p) => `/projects/${p}/schedule`, role: "customer" },
  { at: T.extraAt, kind: "extra_sent", body: "마루와벽이 추가 금액을 올렸어요", link: (p) => `/projects/${p}/schedule?view=extra`, role: "customer" },
  { at: T.donePosted, kind: "work_done", body: "마루와벽이 공사를 끝냈대요 · 확인해 주세요", link: (p) => `/projects/${p}/schedule?view=done`, role: "customer" },
  // 업체(마루와벽) 알림(V21)
  { at: T.sent, kind: "visit_requested", body: "새 실측 요청 · 상계동 69.4㎡", link: () => `/vendor/requests/${I.visit.maru}`, role: "vendor" },
  { at: T.maruBooked, kind: "visit_booked", body: "실측이 12.15(화) 오전으로 정해졌어요 · 상계동", link: () => `/chat/${I.thread.maru}`, role: "vendor" },
  { at: T.changeAt, kind: "change_requested", body: "일정 바꾸기 요청이 왔어요 · 상계동", link: () => `/chat/${I.thread.maru}`, role: "vendor" },
  { at: "2026-12-14T18:00:00+09:00", kind: "visit_reminder", body: "내일 오전 실측이에요 · 상계동", link: () => `/vendor?tab=sched`, role: "vendor" },
  { at: T.confirmed, kind: "deal_confirmed", body: "견적서가 확정됐어요 · 상계동 69.4㎡ 326만 7,000원 · 공사 날짜를 올려 주세요", link: () => `/vendor/jobs/${I.deal}`, role: "vendor" },
];

export function mockNotifications(step: StepKey, role: Role, projectId: string): S["NotificationPage"] {
  const c = stepCtx(step);
  const list = NOTES.filter((n) => n.role === role && c.seen(n.at)).sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  // 가장 최근 알림 하나만 안 읽은 것으로 둬요(9판 C44 · V21)
  const items: S["NotificationOut"][] = list.map((n, i) => ({ id: uid(`9${String(NOTES.indexOf(n)).padStart(3, "0")}`), kind: n.kind, project_id: role === "customer" ? projectId : null, body: n.body, link: n.link(projectId), created_at: n.at, read: i > 0 }));
  return { items, unread: items.filter((n) => !n.read).length };
}

// 실측 상태 이름표(lib/labels visitState · components/visit/text boardState · nextText). 화면마다 상태를 확실히 가르게:
// 상태마다 말이 서로 다르고, 끝난 요청은 끝남(–)이며, 취소한 요청이 답 기다림처럼 보이지 않아요(QA r9 U).
import { expect, test } from "@playwright/test";
import { extraAnswerText } from "@/components/docs/text";
import { boardState, expiredDue, nextText } from "@/components/visit/text";
import type { BoardRow } from "@/lib/api/visit";
import { ENDED_VISIT, VISIT_STATE_CUSTOMER, VISIT_STATE_VENDOR, visitState, type VisitStatus } from "@/lib/labels";

const ALL = Object.keys(VISIT_STATE_CUSTOMER) as VisitStatus[];
const LIVE = ALL.filter((st) => !ENDED_VISIT.has(st));
const SIDES = ["customer", "vendor"] as const;

test("두 쪽 모두 서버 상태 13개에 이름표가 있고 상태마다 말이 달라요", () => {
  expect(ALL).toHaveLength(13);
  expect(Object.keys(VISIT_STATE_VENDOR).sort()).toEqual([...ALL].sort());
  for (const side of SIDES) {
    const labels = ALL.map((st) => visitState(st, side).label);
    expect(new Set(labels).size, side).toBe(ALL.length);
  }
});

test("끝난 요청은 끝남(–)이고, 살아 있는 요청은 끝남이 아니에요", () => {
  expect([...ENDED_VISIT].sort()).toEqual(["cancelled", "closed", "declined", "expired", "no_show"]);
  for (const side of SIDES) {
    for (const st of ENDED_VISIT) expect(visitState(st, side).tone, `${side} ${st}`).toBe("done");
    for (const st of LIVE) expect(visitState(st, side).tone, `${side} ${st}`).not.toBe("done");
  }
});

test("고객: 취소한 요청과 업체 답 기다림은 말도 모양도 달라요", () => {
  const cancelled = visitState("cancelled", "customer");
  const waiting = visitState("requested", "customer");
  expect(cancelled).toEqual({ label: "취소함", tone: "done" });
  expect(waiting).toEqual({ label: "업체 답 기다림", tone: "wait" });
});

test("고객: 내 차례는 할 일(●), 업체 차례는 기다림(○)이고 업체 차례 말에는 '업체'가 붙어요", () => {
  for (const st of ["offered", "proposed", "quoted"] as const) expect(visitState(st, "customer").tone, st).toBe("todo");
  for (const st of ["requested", "picked", "visited"] as const) expect(visitState(st, "customer").tone, st).toBe("wait");
  expect(visitState("requested", "customer").label).toContain("업체");
  expect(visitState("picked", "customer").label).toContain("업체");
});

test("고객: 실측 확정과 업체 확정은 다른 말이에요", () => {
  expect(visitState("booked", "customer").label).toBe("실측 확정");
  expect(visitState("chosen", "customer").label).toBe("업체 확정");
});

test("기한 지남은 누가 안 했는지로 갈라요(모르면 기한 지남)", () => {
  expect(visitState("expired", "customer", { expired_reason: "reply" }).label).toBe("업체 답 없음");
  expect(visitState("expired", "customer", { expired_reason: "pick" }).label).toBe("고르기 기한 지남");
  expect(visitState("expired", "customer").label).toBe("기한 지남");
  expect(visitState("expired", "vendor", { expired_reason: "reply" }).label).toBe("답 기한 지남");
  expect(visitState("expired", "vendor", { expired_reason: "pick" }).label).toBe("고르기 기한 지남");
  for (const why of ["reply", "pick", null]) expect(visitState("expired", "customer", { expired_reason: why }).tone).toBe("done");
});

test("업체: 닫힌 까닭마다 작업함 줄과 같은 말이고, 모르는 까닭은 닫힘이에요", () => {
  expect(visitState("closed", "vendor", { close_reason: "other_chosen" }).label).toBe("다른 업체로 정함");
  expect(visitState("closed", "vendor", { close_reason: "reselected" }).label).toBe("다시 고르기로 닫힘");
  expect(visitState("closed", "vendor", { close_reason: "vendor_stopped" }).label).toBe("업체 기능 멈춤으로 닫힘");
  expect(visitState("closed", "vendor", { close_reason: "unknown" }).label).toBe("닫힘");
  expect(visitState("closed", "customer", { close_reason: "other_chosen" }).label).toBe("닫힘");
});

test("모르는 상태는 영어를 보이지 않고 '확인 중'이에요", () => {
  for (const side of SIDES) expect(visitState("weird", side)).toEqual({ label: "확인 중", tone: "wait" });
});

// ── 실측 일정 상태판 줄(서버 BoardRowOut 모양)
const NONE = { kind: "none", who: "none", due_at: null, overdue: false, soon: false } as BoardRow["next"];
const CAN = { pick: false, cancel: false, again: false, visited: false, change: false, requote: false };
function row(p: Partial<BoardRow>): BoardRow {
  return {
    visit_id: "v1", vendor_id: "u1", vendor_name: "결도배", attempt: 1, status: "requested", next: NONE, window: null, booked: null,
    proposal: null, change: null, can: CAN, estimate_total: null, thread_id: null, quote: null, cancel_code: null, expired_reason: null, ...p,
  };
}

test("상태판 칩: 실측 시각이 지난 확정은 할 일, 기한 지남은 까닭대로", () => {
  expect(boardState(row({ status: "booked", can: { ...CAN, visited: true } }))).toEqual({ label: "실측 시각 지남", tone: "todo" });
  expect(boardState(row({ status: "booked" }))).toEqual({ label: "실측 확정", tone: "ok" });
  expect(boardState(row({ status: "expired", expired_reason: "reply" }))).toEqual({ label: "업체 답 없음", tone: "done" });
  expect(boardState(row({ status: "cancelled" }))).toEqual({ label: "취소함", tone: "done" });
});

test("상태판 '다음 할 일': 끝난 요청도 다음 길을 말하고 닫힘만 비워요", () => {
  expect(nextText(row({ status: "requested" }))).toBe("결도배가 기간을 답해요");
  expect(nextText(row({ status: "cancelled" }))).toBe("다른 업체 담기");
  expect(nextText(row({ status: "cancelled", can: { ...CAN, again: true } }))).toBe("한 번 더 요청 · 다른 업체 담기");
  expect(nextText(row({ status: "expired", can: { ...CAN, again: true } }))).toBe("한 번 더 요청 · 다른 업체 담기");
  expect(nextText(row({ status: "declined" }))).toBe("다른 업체 담기");
  expect(nextText(row({ status: "no_show" }))).toBe("다른 업체 담기");
  expect(nextText(row({ status: "closed" }))).toBe("—");
});

test("상태판 '다음 할 일': 업체가 일정 바꾸기에 다른 날을 냈으면 내 차례예요", () => {
  const change = { id: "c1", visit_id: "v1", from_day: "2026-12-15", from_half: "am", to_day: "2026-12-17", to_half: "am", due_at: "2026-12-12T14:20:00+09:00", proposal: null, created_at: "2026-12-10T14:20:00+09:00" } as const;
  expect(nextText(row({ status: "booked", change: { ...change, status: "open" } }))).toBe("결도배가 일정 바꾸기에 답해요");
  expect(nextText(row({ status: "booked", change: { ...change, status: "countered" } }))).toBe("업체가 낸 다른 날 고르기");
  expect(nextText(row({ status: "booked" }))).toBe("실측 날 기다리기");
});

test("서류 모음 추가 금액: 거절과 채팅으로 물음이 같은 말이 아니고, 지난 판은 답할 차례가 아니에요", () => {
  const texts = (["pending", "approved", "rejected", "asked"] as const).map((answer) => extraAnswerText({ answer, superseded: false }));
  expect(new Set(texts).size).toBe(4);
  expect(extraAnswerText({ answer: "rejected", superseded: false })).toBe("거절했어요");
  expect(extraAnswerText({ answer: "asked", superseded: false })).toBe("채팅으로 물었어요");
  expect(extraAnswerText({ answer: "pending", superseded: true })).toBe("새 판으로 바뀌었어요");
});

test("기한이 지나 끝난 요청의 기한은 서버 expired_due_at을 먼저 써요", () => {
  expect(expiredDue(row({ status: "expired", expired_due_at: "2026-11-19T21:40:00+09:00" }))).toBe("2026-11-19T21:40:00+09:00");
  expect(expiredDue(row({ status: "expired" }))).toBeNull();
});

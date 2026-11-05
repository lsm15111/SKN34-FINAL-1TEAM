// 한 공사 화면(시안 WProjectB)에만 쓰는 화면 말. 할 일 문구 · 금액 · 날짜는 API 값이고 여기서는 고르고 형식만 바꾼다.
import type { ApiOverview } from "@/lib/api/schedule";

export type Overview = ApiOverview;
export type TradeRow = Overview["trades"][number];
export type Tone = "ok" | "wait" | "now" | "bad" | "off";

/** 공정 한 줄의 지금 상태: 그 공정의 할 일 코드(calc/progress.py TODO_RANK) → 판 말 */
const TRADE_STATE: Record<string, { text: string; tone: Tone }> = {
  check: { text: "공사 끝냄 · 확인할 차례", tone: "now" },
  dates_received: { text: "날짜 옴 · 확인할 차례", tone: "now" },
  dates_change: { text: "바꿀 날짜 옴 · 확인할 차례", tone: "now" },
  extra: { text: "추가 금액 · 확인할 차례", tone: "now" },
  quotes_arrived: { text: "견적서 옴 · 비교할 차례", tone: "now" },
  quotes_partial: { text: "견적서 일부 옴", tone: "now" },
  dates_overdue: { text: "공사 날짜 기한 지남", tone: "bad" },
  pick: { text: "업체 고를 차례", tone: "now" },
  visit_requested: { text: "실측 요청함", tone: "wait" },
  before_work: { text: "날짜 수락함", tone: "ok" },
  dates_waiting: { text: "업체 확정 · 날짜 기다림", tone: "wait" },
  dates_requested: { text: "다른 날짜 요청함", tone: "wait" },
  working: { text: "공사 중", tone: "now" },
  fixing: { text: "남은 일 기다림", tone: "wait" },
  done: { text: "공사 끝남", tone: "ok" },
};

export function tradeState(t: TradeRow): { text: string; tone: Tone } {
  if (t.overdue) return TRADE_STATE.dates_overdue;
  return TRADE_STATE[t.todo.code] ?? { text: "확인 중", tone: "off" };
}

/** 공정 카드의 날짜: 수락한 날짜, 없으면 수락 기다리는 날짜 */
export function tradeDates(t: TradeRow): { start: string; end: string; accepted: boolean } | null {
  if (t.start_date && t.end_date) return { start: t.start_date, end: t.end_date, accepted: true };
  if (t.proposed_start && t.proposed_end) return { start: t.proposed_start, end: t.proposed_end, accepted: false };
  return null;
}

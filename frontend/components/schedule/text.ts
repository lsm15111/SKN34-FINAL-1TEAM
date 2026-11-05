// 공사 날짜(시안 WSchedule)에만 쓰는 화면 말 · 표시 함수. 날짜 · 일하는 날 · 기한은 API(계산 엔진) 값의 형식만 바꾼다.
// 서버 · 브라우저 양쪽에서 쓴다.
import { DEAL_LABEL, day } from "@/components/confirm/text";
import type { Schemas } from "@/lib/backend/client";
import { dayParts, dotDate } from "@/lib/format";

export type Schedule = Schemas["ScheduleOut"];
export type TradeDates = Schemas["TradeDatesOut"];
export type Proposal = Schemas["ProposalOut"];
export type DateReq = Schemas["DateRequestOut"];
export type StartOption = Schemas["StartOptionOut"];
export type Holiday = Schemas["HolidayOut"];

/** "11.19(목) ~ 11.23(월)" (하루면 그날만) */
export const span = (start: string, end: string) => (start === end ? day(start) : `${day(start)} ~ ${day(end)}`);

/** 공사 날짜를 수락했거나 그 뒤 공사 상태인지 (확정 상태로 본다. 수락 뒤 날짜 바꾸기는 확정 공정표에서 다룬다) */
export const isAccepted = (t: TradeDates) => t.deal.status !== "confirmed";

/** 업체가 '공사 끝냈어요'를 올린 뒤(내 확인 기다림 · 남은 일 · 끝남): 날짜를 더 바꾸지 않는다 */
export const isFinished = (status: string) => status === "checking" || status === "fixing" || status === "done";

/** 공사 끝냄 상태 말 (고객 쪽) */
export const WORK_TEXT: Record<string, string> = { checking: "공사 끝냄 · 내 확인 기다림", fixing: "남은 일 기다림", done: "공사 끝남" };

/** 연락처 기한 "2027.11.23(화)" (API 값 그대로, 형식만) */
export const untilDay = (iso: string) => `${dotDate(iso)}(${dayParts(iso).w})`;

/** 쉬는 날 말 (주말에도 공사하면 공휴일만 쉰다) */
export const offText = (weekendWork: boolean) => (weekendWork ? "공휴일만 쉬어요" : "주말 · 공휴일은 쉬어요");

/** 낸 날짜 안의 공휴일 (API가 준 공휴일 목록에서 고른다) */
export const holidaysIn = (hs: Holiday[], start: string, end: string) => hs.filter((h) => h.day >= start && h.day <= end);

export type Tone = "ok" | "wait" | "now" | "bad" | "off";

/** 공정 탭 · 얹어 보기 표의 상태 (확정이 없으면 '확정 전') */
export function stateOf(t: TradeDates | undefined): { text: string; tone: Tone } {
  if (!t) return { text: "확정 전", tone: "off" };
  if (isAccepted(t)) {
    // 수락한 뒤 날짜 바꾸기(확정 공정표에서 다룬다)
    if (t.dates_state === "change_requested") return { text: "날짜 바꾸기 요청함", tone: "wait" };
    if (t.dates_state === "change_proposed") return { text: "바꿀 날짜 옴 · 확인할 차례", tone: "now" };
    if (t.deal.status === "checking") return { text: WORK_TEXT.checking, tone: "now" };
    if (t.deal.status === "fixing") return { text: WORK_TEXT.fixing, tone: "wait" };
    return { text: t.deal.status === "scheduled" ? "날짜 수락함" : (WORK_TEXT[t.deal.status] ?? DEAL_LABEL[t.deal.status] ?? "날짜 수락함"), tone: "ok" };
  }
  switch (t.dates_state) {
    case "waiting":
      return t.deal.overdue ? { text: "기한 지남", tone: "bad" } : { text: "업체 확정 · 날짜 기다림", tone: "wait" };
    case "proposed":
      return { text: t.proposal?.changed ? "새 날짜 옴 · 확인할 차례" : "날짜 옴 · 확인할 차례", tone: "now" };
    case "requested":
      return t.request?.overdue ? { text: "요청 답 기한 지남", tone: "bad" } : { text: "다른 날짜 요청함", tone: "wait" };
    default:
      return { text: "업체 확정 · 날짜 기다림", tone: "wait" };
  }
}

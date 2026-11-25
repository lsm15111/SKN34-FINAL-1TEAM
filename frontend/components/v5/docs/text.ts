// 서류 모음(시안 WDocs)에만 쓰는 화면 말.
import type { ApiDeal, ApiDocs } from "@/lib/api/schedule";
import { tradeLabel } from "@/lib/v5/labels";

type Extra = ApiDocs["extras"][number]["items"][number];

export const PLAN_NAME: Record<"expected" | "final", string> = { expected: "예상 공정표", final: "확정 공정표" };

/** 추가 금액 답 상태(고객 쪽 말, 공사 화면 추가 금액과 같게). 옛 ack 값은 거절도 '이야기 중'이라 v3 answer로 갈라요.
 *  새 판이 나와 지난 판은 답할 일이 아니에요 */
const ANSWER_TEXT: Record<Extra["answer"], string> = { pending: "답할 차례예요", approved: "승인했어요", rejected: "거절했어요", asked: "채팅으로 물었어요" };
export const extraAnswerText = (x: Pick<Extra, "answer" | "superseded">) => (x.superseded ? "새 판으로 바뀌었어요" : ANSWER_TEXT[x.answer] ?? "확인 중");

/** 실측 견적서 줄 아래 말: "도배 · 확정", "도배 · 닫힘 · 기록" */
export function quoteSub(trade: string, closed: boolean, confirmed: boolean) {
  const tail = closed ? "닫힘 · 기록" : confirmed ? "확정" : null;
  return [tradeLabel(trade), tail].filter(Boolean).join(" · ");
}

/** 확정 공정표 줄 아래 말: "목공 확정 · 도배 날짜 수락 전" (공사 순서 목공 → 도배, 수락한 날짜가 있으면 확정) */
export function finalPlanSub(trades: string[], deals: ApiDeal[]) {
  return ["mokgong", "dobae"]
    .filter((t) => trades.includes(t))
    .map((t) => (deals.some((d) => d.trade === t && d.start_date) ? `${tradeLabel(t)} 확정` : `${tradeLabel(t)} 날짜 수락 전`))
    .join(" · ");
}

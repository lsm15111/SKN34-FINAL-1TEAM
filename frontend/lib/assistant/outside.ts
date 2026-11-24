// 받은 견적서 점검 카드(components/assistant/cards/OutsideQuoteCard)의 화면 말. 금액 · 차이 · 판정은 서버(계산 엔진) 값이고 여기서는
// 이름표와 모양만 정해요. 표준 대비 %는 없어요.
import type { BadgeTone } from "@/components/ui/Badge";
import type { OutsideQuoteData, OutsideRow, OutsideRowState } from "@/lib/api/assistant";

/** 줄 판정 칩: 빠짐(빨강) · 많음(주황) · 비슷(초록) · 적음(파랑) · 나머지(회색). 글자가 늘 같이 있어 색만으로 알리지 않아요 */
export const ROW_CHIP: Record<OutsideRowState, { label: string; tone: BadgeTone }> = {
  missing: { label: "빠짐", tone: "bad" },
  more: { label: "많음", tone: "wait" },
  same: { label: "비슷", tone: "ok" },
  less: { label: "적음", tone: "now" },
  extra: { label: "표준에 없음", tone: "mute" },
  discount: { label: "할인", tone: "mute" },
  noprice: { label: "금액 없음", tone: "mute" },
};

/** 합계 판정 말(같은 범위로 견준 합계) */
export const TOTAL_WORD: Record<OutsideQuoteData["state"], string> = { more: "표준보다 많아요", same: "표준과 비슷해요", less: "표준보다 적어요" };

export const PUTTY_TONE: Record<OutsideQuoteData["putty"]["need"], BadgeTone> = { need: "wait", check: "now", no: "ok" };

export const SOURCE_WORD: Record<OutsideQuoteData["source"], string> = { text: "붙인 글", photo: "올린 사진", both: "글 · 사진" };

/** 줄 아래 금액 말 조각: 받은 · 표준 금액이 있는 것만(빠짐이면 '견적서에 없어요'). won은 표시 함수(lib/format)를 받아요 */
export function rowParts(r: OutsideRow, won: (n: number) => string): string[] {
  const out: string[] = [];
  if (r.outside_won != null) out.push(`견적서 ${won(r.outside_won)}`);
  else if (r.state === "missing") out.push("견적서에 없어요");
  if (r.standard_won != null) out.push(`표준 ${won(r.standard_won)}`);
  return out;
}

/** 차이 말: 서버 차이 그대로 +/− 붙여요(0이면 '차이 없음') */
export function diffText(n: number, won: (n: number) => string): string {
  return n > 0 ? `+${won(n)}` : n < 0 ? won(n) : "차이 없음";
}

/** 희망 예산 줄: 예산 범위 글 + 안 · 넘음 · 남음(넘거나 남는 돈은 서버 값) */
export function budgetText(b: NonNullable<OutsideQuoteData["budget"]>, won: (n: number) => string): string {
  if (b.state === "over" && b.gap_won != null) return `${b.label} · ${won(b.gap_won)} 넘어요`;
  if (b.state === "under" && b.gap_won != null) return `${b.label} · ${won(b.gap_won)} 남아요`;
  return `${b.label} · 예산 안이에요`;
}

/** 판정이 눈에 띄어야 하는 줄(빠짐 · 많음)을 앞으로, 나머지는 서버 차례 그대로 */
export function sortRows(rows: OutsideRow[]): OutsideRow[] {
  const first = (r: OutsideRow) => (r.state === "missing" || r.state === "more" ? 0 : 1);
  return rows.map((r, i) => ({ r, i })).sort((a, b) => first(a.r) - first(b.r) || a.i - b.i).map((x) => x.r);
}

// 표준견적서 줄 → 화면 줄(QuoteLines). 손님 계산(POST /guest/standard) · 내 공사(GET /projects/{id}/standard)가 같이 써요.
// 금액 · 수량 · 단가는 계산 엔진 값을 그대로 넘겨요. 여기서는 줄 이름을 화면 말로 다듬고, 줄 아래 설명 앞부분만 붙여요.
import type { LineState, QuoteLine } from "@/components/ui/QuoteLines";
import { decText, won } from "@/lib/format";

export type StdLineIn = {
  key: string;
  name: string;
  qty: string | null;
  unit: string;
  unit_price: number | null;
  amount: number | null;
  state: string;
  source?: string | null;
  basis?: string | null;
};

const STATES: LineState[] = ["included", "bundled", "separate", "optional", "after_visit", "excluded"];
// 두 기준 줄(ADR 0004)은 이름 끝 괄호가 줄 아래 짧은 뜻이에요: '부자재 (풀 · 부직포 · 네바리 · 실리콘 등)' · '벽 도배 시공 (인건비)'
const NOTE_KEYS = new Set(["wall", "ceiling", "material", "putty", "meal", "truck"]);

/** 단위 글: 두 낱말 단위('벽지 평' = 도배지 3.3058㎡)는 수량과 띄워요('63 벽지 평'). ㎡ · 평 · 품은 붙여요 */
export const unitText = (unit: string | null | undefined): string => (unit && unit.includes(" ") ? ` ${unit}` : unit ?? "");

/** v2 이름 '벽 도배 시공 (풀 포함)' · '도배지 (실크)'도 v3 화면 말로 */
function nameOf(l: StdLineIn): { name: string; note?: string } {
  const glue = /\s*\(풀 포함\)\s*$/.exec(l.name);
  if (glue) return { name: l.name.slice(0, glue.index), note: "풀 포함" };
  const paper = /^도배지 \((합지|실크)\)$/.exec(l.name);
  if (paper) return { name: `${paper[1]}벽지` };
  // v3 API 줄 이름 '실크벽지 시장 평균 가격' → 이름 '실크벽지' + 설명 '시장 평균 가격'(9판 C07)
  const market = /^(\S+벽지) 시장 평균 가격$/.exec(l.name);
  if (market) return { name: market[1], note: "시장 평균 가격" };
  const tail = NOTE_KEYS.has(l.key) ? /^(.+?)\s*\(([^()]+)\)$/.exec(l.name) : null;
  if (tail) return { name: tail[1], note: tail[2] };
  if (l.key === "wall" || l.key === "ceiling") return { name: l.name, note: "풀 포함" };
  return { name: l.name };
}

/** 벽지 직접 구매(API own_paper): 도배지 줄은 '고객 구매'(합계 밖, 계산 엔진). rolls는 롤 수 글(API rolls.text) */
export type OwnPaper = { rolls: string | null };

export function toQuoteLines(lines: StdLineIn[], scope: "full" | "partial" | null | undefined, own?: OwnPaper): QuoteLine[] {
  return lines.map((l) => {
    const { name, note: base } = nameOf(l);
    const state = (STATES as string[]).includes(l.state) ? (l.state as LineState) : undefined;
    let note = base;
    if (l.key === "paper" && (l.basis === "market" || l.basis === "assumed" || (l.source ?? "").includes("시장"))) note = "시장 평균 가격";
    // 고객 구매 줄: 사야 할 양(수량 · 롤 수)만 보이고 단가 · 금액은 '—'(합계 밖이라 '안 함' 말은 붙이지 않아요)
    if (own && l.key === "paper" && state === "excluded") {
      return { key: l.key, name, note: ["고객 구매", own.rolls].filter(Boolean).join(" · "), qty: l.qty, unit: unitText(l.unit), amount: null };
    }
    if (state === "excluded" && scope === "partial") note = "고르지 않았어요";
    if (state === "excluded" && scope === "partial") return { key: l.key, name, note, amount: null, state };
    return { key: l.key, name, note, qty: l.qty, unit: unitText(l.unit), unitPrice: l.unit_price, amount: l.amount, state };
  });
}

/** '부가세 포함 · 공사 2일 예상'(CF-16). 일수가 없으면 '부가세 포함'만 */
export function daysCaption(days: string | number | null | undefined): string {
  if (days == null || days === "") return "";
  return `공사 ${typeof days === "number" ? days : decText(days)}일 예상`;
}

/** '예산 300만 원 안이에요' · '예산 300만 원을 넘어요'. 예산이 없거나 견줄 수 없으면 null */
export function budgetText(fit: string | null | undefined, budgetWon: number | null | undefined): string | null {
  if (!budgetWon || (fit !== "within" && fit !== "over")) return null;
  return fit === "within" ? `예산 ${won(budgetWon)} 안이에요` : `예산 ${won(budgetWon)}을 넘어요`;
}

/** 화면 한 장에 필요한 값(가입 전 · 내 공사 같은 모양) */
export type StdView = {
  scope: "full" | "partial";
  lines: QuoteLine[];
  supply: number;
  vat: number;
  total: number;
  days: string | null;
  budget: string | null;
  /** '도배 전체 · 아파트 공급 69.4㎡ · 실크 · 빈 집' */
  condition: string;
  /** 벽지 직접 구매일 때 안내 한 줄(API paper_note, 틀): 업체 가견적은 벽지 값이 든 값이에요 */
  paperNote?: string | null;
};

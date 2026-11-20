// 업체 보기 · 자세히(v3)의 화면 말. 값은 계산 엔진이 준 것만 모양을 바꿔요.
import type { QuoteLine } from "@/components/ui/QuoteLines";
import { decText, won } from "@/lib/format";
import { unitText } from "@/lib/guest/standard";

/** '표준견적서보다 41% 많아요'(CF-08). vs_standard_pct는 엔진이 낸 % 글(음수면 적어요) */
export function compareText(pct: string | null | undefined): string | undefined {
  if (pct == null || pct === "") return undefined;
  const n = Number(pct);
  if (!Number.isFinite(n)) return undefined;
  if (n === 0) return "표준견적서와 같아요";
  return `표준견적서보다 ${decText(String(Math.abs(n)))}% ${n > 0 ? "많아요" : "적어요"}`;
}

/** '실측 무료' · '실측 출장비 3만 원'(부가세 포함). 모르면 없음 */
export function feeText(fee: number | null | undefined): string | undefined {
  if (fee == null) return undefined;
  return fee === 0 ? "실측 무료" : `실측 출장비 ${won(fee)}`;
}

/** 활동 지역 '노원구 · 도봉구 외 2곳' */
export function areasText(labels: string[]): string {
  if (!labels.length) return "";
  const head = labels.slice(0, 2).join(" · ");
  return labels.length > 2 ? `${head} 외 ${labels.length - 2}곳` : head;
}

/** 시공 사례 이름 '거실 · 실크' · 크게 보기 '거실 · 실크벽지' */
const SPACE: Record<string, string> = { living: "거실", kitchen: "주방", master: "안방", room1: "작은방", room2: "작은방", hall: "복도", entry: "현관", dress: "드레스룸" };
export function caseLabel(p: { title: string; space?: string | null; paper?: string | null }, long = false): string {
  const space = (p.space && SPACE[p.space]) || p.title;
  const paper = p.paper === "basic" ? "실크" : p.paper === "economy" ? "합지" : "";
  return paper ? `${space} · ${paper}${long ? "벽지" : ""}` : space;
}

/** '2026-10-12' · '2026-10' → '2026년 10월' */
export function monthText(v: string | null | undefined): string {
  const m = v ? /^(\d{4})-(\d{2})/.exec(v) : null;
  return m ? `${m[1]}년 ${Number(m[2])}월` : "";
}

/** 가견적 줄(엔진 값) → 화면 줄(QuoteLines). 줄 번호(1201~)는 고객에게 보이지 않아요(CF-42).
 *  보이는 벽지가 아닌 벽지 줄은 빼고, '다른 줄에 포함'은 금액 '—' + 어디에 들었는지, '빼기'는 '안 함'으로 둬요. 더하지 않아요 */
/** 줄 이름 · 짧은 뜻은 API(계산 엔진 줄 정의의 label · note)에서 받아요. AI 답도 같은 말을 써요 */
type EstLine = { code: string; key: string; name: string; label?: string; note?: string; qty: string; unit: string; unit_price: number | null; amount: number; mode: "price" | "included" | "excluded"; included_in: string | null; in_standard: boolean };
/** inside: 표준견적서에 같은 일이 있는 줄 · outside: 없는 줄(퍼티 · 식대 · 운송비, API in_standard false) */
export function estimateLines(lines: EstLine[], grade: "basic" | "economy"): { inside: QuoteLine[]; outside: QuoteLine[] } {
  const other = grade === "basic" ? "paper_hapji" : "paper_silk";
  const byCode = new Map(lines.map((l) => [l.code, l]));
  const nameOf = (l: EstLine) => l.label || l.name;
  const shown = lines.filter((l) => l.key !== other);
  const toLine = (l: EstLine): QuoteLine => {
    const key = `${l.code}-${l.key}`;
    if (l.mode === "included") {
      const host = l.included_in ? byCode.get(l.included_in) : undefined;
      return { key, name: nameOf(l), note: host ? `${nameOf(host)}에 포함` : "다른 줄에 포함", qty: l.qty, unit: unitText(l.unit), unitPrice: null, amount: null };
    }
    if (l.mode === "excluded") return { key, name: nameOf(l), amount: null, state: "excluded" };
    return { key, name: nameOf(l), note: l.note || undefined, qty: l.qty, unit: unitText(l.unit), unitPrice: l.unit_price, amount: l.amount };
  };
  return { inside: shown.filter((l) => l.in_standard).map(toLine), outside: shown.filter((l) => !l.in_standard).map(toLine) };
}

/** 업체 답 시간(API reply_hours: 최근 요청에 기간을 답하기까지 걸린 시간의 가운데 값, 올림) → '보통 1일 안에 답'(C11) */
export function replyText(hours: number | null | undefined): string | undefined {
  if (hours == null || hours <= 0) return undefined;
  return `보통 ${Math.max(1, Math.ceil(hours / 24))}일 안에 답`;
}

/** 업체가 연결한 외부 리뷰: 관리자가 확인한(shown) https 주소만 보여요(security.md E) */
export function safeLinks<T extends { url: string; status: string }>(links: T[] | null | undefined): T[] {
  return (links ?? []).filter((l) => {
    if (l.status !== "shown") return false;
    try { return new URL(l.url).protocol === "https:"; } catch { return false; }
  });
}

// 서버 쪽 읽기: 표준견적서 · 업체 실측 견적서 · 실측 견적서 비교.
// v3 표준견적서 화면(C07 · C60 · D01)은 getStandardView로 읽어요. 예시(lib/mock/v3a)는 개발 예시 공사 id일 때만이에요.
import { serverGet } from "@/lib/backend/server";
import type { Schemas } from "@/lib/v5/types";
import { conditionText } from "@/lib/v5/guest/info";
import { budgetText, toQuoteLines, type StdView } from "@/lib/v5/guest/standard";
import { mockKeyOf } from "@/lib/mock/v3a/mode";
import { PART_STANDARD, SAMPLE_STANDARD } from "@/lib/v5/mock/v3a/standard";
import { getPlanView, isUuid, type ProjectShell } from "./project";

const seg = (id: string) => encodeURIComponent(id);

export type ApiStandard = Schemas["StandardOut"];
/** 표준견적서 (믿집 계산). 없거나 남의 것이면 null */
export async function getStandard(projectId: string) {
  return isUuid(projectId) ? serverGet<ApiStandard>(`/projects/${seg(projectId)}/standard`) : null;
}

export type VendorQuoteBoard = Schemas["QuoteBoardOut"];
/** 업체: 이 요청의 실측 견적서(임시 저장본 · 보낸 버전 · 칸 한도). 내 요청이 아니면 null */
export async function getMyQuoteBoard(visitId: string) {
  return isUuid(visitId) ? serverGet<VendorQuoteBoard>(`/vendor/visits/${seg(visitId)}/quote`) : null;
}

export type QuoteCompare = Schemas["CompareDealOut"];
/** 고객: 한 공정의 실측 견적서 비교(표준견적서 · 업체마다 최신 버전 · 이전 버전). 남의 공사 · 고르지 않은 공정이면 null */
export async function getQuoteCompare(projectId: string, trade: "dobae" | "mokgong") {
  return isUuid(projectId) ? serverGet<QuoteCompare>(`/projects/${seg(projectId)}/quotes?trade=${trade}`) : null;
}

/**
 * 내 공사 표준견적서 한 장(도배). 금액 · 수량 · 일수는 API 값 그대로예요.
 * 공사 일수는 StandardOut.days(계산 엔진), 비어 있으면 예상 공정표의 일하는 날 수예요.
 */
export async function getStandardView(shell: ProjectShell): Promise<StdView | null> {
  const k = mockKeyOf(shell.id);
  const cond = shell.cond ? conditionText(shell.cond) : "";
  if (k) {
    const g = k === "part" ? PART_STANDARD : SAMPLE_STANDARD;
    return { scope: g.scope, lines: toQuoteLines(g.lines, g.scope), supply: g.supply, vat: g.vat, total: g.total, days: g.days, budget: budgetText(g.budget_fit, shell.budgetWon), condition: cond };
  }
  const q = await getStandard(shell.id);
  if (!q) return null;
  const t = q.trades.find((x) => x.trade === "dobae") ?? q.trades[0];
  if (!t) return null;
  const scope = q.scope ?? shell.cond?.scope ?? "full";
  // 예상 일수는 계산 엔진 값(StandardOut.days). v2로 만든 옛 공사처럼 비어 있으면 예상 공정표의 일하는 날 수를 써요
  const days = q.days ?? (await getPlanView(shell.id).then((p) => (p ? String(p.work_days) : null)).catch(() => null));
  const fit = q.budget_fit ?? (q.budget && q.budget.status !== "open" ? q.budget.status : null);
  // 벽지 직접 구매면 도배지 줄은 '고객 구매'(합계 밖, 계산 엔진)이고 롤 수(계산 엔진)를 같이 보여요
  const own = t.own_paper ? { rolls: t.rolls?.text ?? null } : undefined;
  return {
    scope, lines: toQuoteLines(t.lines, scope, own), supply: t.supply, vat: t.vat, total: t.total, days,
    budget: budgetText(fit, shell.budgetWon), condition: cond, paperNote: t.paper_note ?? null,
  };
}

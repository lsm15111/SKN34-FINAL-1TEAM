// 공정별 진행 상태 → 내 프로젝트 카드 한 줄.
// 상태는 데이터를 주는 쪽(lib/api.ts)이 정하고, 여기서는 화면 말과 갈 곳만 붙인다.
import type { TradeKey } from "./types";

export type TradeStage = "choosing" | "estimate_wait" | "comparing" | "visit_wait" | "final_arrived" | "confirmed" | "scheduled";
export type Turn = "me" | "vendor" | "done";

export interface TradeLine {
  trade: TradeKey;
  stage: TradeStage;
  text: string; // 예: "3곳 중 2곳 도착"
}

export const TURN_LABEL: Record<Turn, string> = { me: "내 차례", vendor: "업체 차례", done: "일정 확정" };

// step: 카드 단계 띠의 칸 (0 예상 공정표 · 1 표준견적서 · 2 업체 고르기 · 3 가견적 비교 · 4 실측 견적 · 5 확정 공정표)
const STAGE: Record<TradeStage, { turn: Turn; seg: string; step: number }> = {
  choosing: { turn: "me", seg: "vendors", step: 2 },
  estimate_wait: { turn: "vendor", seg: "quotes", step: 3 },
  comparing: { turn: "me", seg: "quotes", step: 3 },
  visit_wait: { turn: "vendor", seg: "measure", step: 4 },
  final_arrived: { turn: "me", seg: "measure", step: 4 },
  confirmed: { turn: "vendor", seg: "measure", step: 4 },
  scheduled: { turn: "done", seg: "schedule", step: 5 },
};

export const turnOf = (l: TradeLine) => STAGE[l.stage].turn;

/** 프로젝트의 지금 단계: 가장 늦은 공정의 칸. 예상 공정표 · 표준견적서는 만들 때 바로 나와서 늘 끝난 칸이다. 모두 확정이면 6(전부 끝남). */
export function projectStep(lines: TradeLine[]): number {
  if (!lines.length) return 2;
  if (lines.every((l) => l.stage === "scheduled")) return 6;
  return Math.min(...lines.map((l) => STAGE[l.stage].step));
}
export const hrefOf = (projectId: string, l: TradeLine) => `/projects/${projectId}/${STAGE[l.stage].seg}?trade=${l.trade}`;


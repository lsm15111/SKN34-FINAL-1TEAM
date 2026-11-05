// 내 공사 목록(시안 WMy)에만 쓰는 화면 말. 단계 · 할 일은 서버 값을 그대로 쓰고 이름만 붙인다.
import type { ApiProjectItem } from "@/lib/api/project";
import { tradeLabel } from "@/lib/labels";

/** 6단계 이름 (backend/app/calc/progress.py STEPS 순서) */
export const STEP_NAMES = ["집 정보", "기준 금액", "업체 고르기", "실측", "업체 확정", "공사 날짜"];

/** 지금 단계에 붙는 기본 말 (번호 1부터) */
const STEP_NOW: Record<number, string> = {
  1: "집 정보를 넣을 차례",
  2: "기준 금액을 볼 차례",
  3: "업체를 고를 차례",
  4: "실측 견적서를 받는 중",
  5: "업체를 확정할 차례",
  6: "공사 날짜를 정하는 중",
};

/** 할 일(서버 todo.code)마다 짧은 말과 그 일이 속한 단계. 단계가 없으면 공사 날짜를 정한 뒤의 일이다 */
const TODO_NOTE: Record<string, { step?: number; text: string }> = {
  pick: { step: 3, text: "업체를 고를 차례" },
  visit_requested: { step: 4, text: "업체에 연락할 차례" },
  quotes_partial: { step: 4, text: "견적서가 오는 중" },
  quotes_arrived: { step: 4, text: "견적서 옴 · 비교할 차례" },
  dates_received: { step: 6, text: "날짜 옴 · 확인할 차례" },
  dates_overdue: { step: 6, text: "날짜를 낼 기한이 지났어요" },
  dates_waiting: { step: 6, text: "업체가 날짜를 정하는 중" },
  dates_requested: { step: 6, text: "업체 답을 기다리는 중" },
  check: { text: "끝냄을 확인할 차례" },
  dates_change: { text: "바뀐 날짜를 확인할 차례" },
  extra: { text: "추가 금액을 확인할 차례" },
  before_work: { text: "공사를 기다리는 중" },
  working: { text: "공사 중" },
  fixing: { text: "남은 일을 하는 중" },
  done: { text: "공사가 끝났어요" },
};

/** 진행 표시에 붙는 한 줄. 할 일이 지금 단계 것이면 그 말을(공정이 둘이면 공정 이름을 앞에), 아니면 단계 기본 말 */
export function stepNote(p: ApiProjectItem, allDone: boolean): string | null {
  const todo = p.todo ? TODO_NOTE[p.todo.code] : undefined;
  const who = p.todo?.trade && p.trades.length > 1 ? `${tradeLabel(p.todo.trade)} ` : "";
  if (allDone) return todo && !todo.step ? who + todo.text : null;
  if (todo && todo.step === p.current) return who + todo.text;
  return STEP_NOW[p.current] ?? null;
}

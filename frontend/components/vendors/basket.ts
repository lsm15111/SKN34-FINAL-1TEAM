// 견적 요청함 (브라우저 저장). 백엔드가 붙으면 프로젝트의 '요청 준비' 목록으로 바뀐다.
import type { Trade } from "@/lib/types";

export type Basket = Record<Trade, string[]>;
export const emptyBasket = (): Basket => ({ dobae: [], mokgong: [] });
const key = (projectId: string) => `mj_basket_${projectId}`;

export function readBasket(projectId: string): Basket {
  try {
    const raw = localStorage.getItem(key(projectId));
    if (!raw) return emptyBasket();
    const b = JSON.parse(raw);
    return { dobae: Array.isArray(b.dobae) ? b.dobae : [], mokgong: Array.isArray(b.mokgong) ? b.mokgong : [] };
  } catch {
    return emptyBasket();
  }
}
export function writeBasket(projectId: string, b: Basket) {
  try { localStorage.setItem(key(projectId), JSON.stringify(b)); } catch { /* 저장 못 해도 화면은 그대로 */ }
}

// 업체 추천 카드 ↔ 희망 기간 카드: 실측 요청 choice(visit_request:v…[,r…])는 두 카드에서 고른 것을 합쳐 만들어요.
// 고른 업체는 화면에서 고른 것 → 열린 실측 요청 승인 카드의 업체 → 서버가 담아 둔 업체(picked) 순서로 봐요.
import type { ActionOut, CardOut, VendorPick, VisitSlotsData } from "@/lib/api/assistant";
import type { CardCtx } from "./types";

/** 요청 전 희망 기간 카드(업체가 답한 기간이 없고 희망 기간 후보가 있음) */
export const isWish = (d: VisitSlotsData) => !d.window && d.wishes.length > 0;

/** 마지막 실측 요청 승인 카드: 열림(live) · 이미 보냄(sent, 화면에서 직접 보낸 것도) */
export function requestState(ctx: CardCtx): { live: ActionOut | null; sent: boolean } {
  const a = ctx.lastAction("visit_request");
  if (!a) return { live: null, sent: false };
  if (a.status === "executed" || (a.status === "proposed" && ctx.handledOf(a.action_id))) return { live: null, sent: true };
  return { live: a.status === "proposed" || a.status === "approved" ? a : null, sent: false };
}

/** 승인 카드에 든 업체(요약의 업체별 가견적 줄 이름) → 이 카드의 이름표 */
export function vendorsOf(card: CardOut<"vendor_picks">, a: ActionOut): string[] {
  return card.data.picks.filter((p) => a.summary.amounts?.some((x) => x.label === p.name)).map((p) => p.ref);
}

/** 업체 추천 카드에서 지금 고른 업체 이름표(카드 순서) */
export function pickedVendors(ctx: CardCtx, card: CardOut<"vendor_picks">): string[] {
  const mine = ctx.marks[card.card_id];
  if (mine) return card.data.picks.filter((p) => mine.includes(p.ref)).map((p) => p.ref);
  const { live } = requestState(ctx);
  if (live) return vendorsOf(card, live);
  return card.data.picks.filter((p: VendorPick) => p.picked).map((p) => p.ref);
}

/** 대화의 희망 기간 카드에서 고른 기간(없으면 null) */
export function chosenWish(ctx: CardCtx): string | null {
  const card = ctx.lastCard("visit_slots", (c) => isWish(c.data));
  if (!card) return null;
  const r = ctx.marks[card.card_id]?.[0] ?? card.data.chosen;
  return r && card.data.wishes.some((w) => w.ref === r) ? r : null;
}

/** 대화의 업체 추천 카드에서 고른 업체(카드가 없으면 빈 목록) */
export function chosenVendors(ctx: CardCtx): string[] {
  const card = ctx.lastCard("vendor_picks");
  return card ? pickedVendors(ctx, card) : [];
}

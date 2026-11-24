// 받은 견적서 사진 가리기(components/assistant/PhotoMask)의 계산 없는 모양 함수들. 고객이 이름 · 주소 · 전화번호 위를 끌어 상자로
// 가리고, 가린 그림만 올려요(고정 선 3). 그림 크기 · 상자 좌표만 다루고 금액은 없어요.

export type Box = { x: number; y: number; w: number; h: number };
export type Pt = { x: number; y: number };

/** 올릴 그림 긴 변(px). 서버가 LLM에 보낼 때 1568로 다시 줄여요(크면 올리는 시간만 길어져요) */
export const MASK_SIDE = 2000;
/** 이보다 작은 상자는 손이 스친 것으로 보고 버려요(그림 px) */
export const MIN_BOX = 6;
/** 한 턴에 붙이는 사진 수(서버 FILES_MAX와 같아요) */
export const PHOTOS_MAX = 3;
/** 글 없이 사진만 보낼 때 대화에 남길 말 */
export const PHOTO_SAY = "받은 견적서 사진이에요. 점검해 주세요.";

/** 긴 변이 max를 넘지 않게 줄인 정수 크기(작으면 그대로) */
export function fitSize(w: number, h: number, max = MASK_SIDE): { w: number; h: number } {
  if (w <= 0 || h <= 0) return { w: 0, h: 0 };
  const k = Math.min(1, max / Math.max(w, h));
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

/** 화면 좌표(누른 곳) → 그림 좌표. rect는 그림이 그려진 칸(getBoundingClientRect), cw · ch는 그림 크기 */
export function toImage(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }, cw: number, ch: number): Pt {
  if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
  return {
    x: clamp(((clientX - rect.left) / rect.width) * cw, 0, cw),
    y: clamp(((clientY - rect.top) / rect.height) * ch, 0, ch),
  };
}

/** 끈 두 점 → 그림 안 상자(어느 쪽으로 끌어도 같은 상자). 너무 작으면 null */
export function dragBox(a: Pt, b: Pt, cw: number, ch: number): Box | null {
  const x1 = clamp(Math.min(a.x, b.x), 0, cw);
  const y1 = clamp(Math.min(a.y, b.y), 0, ch);
  const x2 = clamp(Math.max(a.x, b.x), 0, cw);
  const y2 = clamp(Math.max(a.y, b.y), 0, ch);
  const box = { x: Math.round(x1), y: Math.round(y1), w: Math.round(x2 - x1), h: Math.round(y2 - y1) };
  return box.w < MIN_BOX || box.h < MIN_BOX ? null : box;
}

/** [올리기]를 켤지: '개인정보를 가렸어요'를 확인했고, 그림을 읽었고, 올리는 중이 아닐 때. 가릴 게 없는 견적서도 있어 상자 수는 보지 않아요 */
export function canUpload(confirmed: boolean, ready: boolean, busy: boolean): boolean {
  return confirmed && ready && !busy;
}

/** 보낼 말: 쓴 글이 있으면 그 글, 사진만 있으면 정해 둔 말, 둘 다 없으면 "" */
export function sendText(text: string, photos: number): string {
  const t = text.trim();
  return t || (photos > 0 ? PHOTO_SAY : "");
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

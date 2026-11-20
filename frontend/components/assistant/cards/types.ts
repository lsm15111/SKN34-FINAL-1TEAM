// 대화 카드가 받는 것. 카드는 값을 계산하지 않고, 고른 것을 턴(send)이나 승인(approve)으로만 넘겨요.
import type { ActionOut, AddressHit, CardKind, CardOut, TurnIn } from "@/lib/api/assistant";

export type CardCtx = {
  projectId: string;
  /** 서버 시각(기한 · 오늘 말에만) */
  now: string;
  /** 턴이 도는 중(새 턴은 기다려요) */
  busy: boolean;
  send: (text: string, context?: TurnIn["context"]) => void;
  /** 제안 행동 승인(home_info 카드의 [맞아요] 등 카드 안 단추) */
  approve: (actionId: string) => void;
  actionOf: (actionId: string) => ActionOut | null;
  pendingOf: (actionId: string) => boolean;
  dismissNudge: (cardId: string, nudgeId: string) => void;
  searchAddress: (q: string) => Promise<AddressHit[]>;
};

export type CardProps<K extends CardKind> = { card: CardOut<K>; ctx: CardCtx; old: boolean };

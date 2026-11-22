// 대화 카드가 받는 것. 카드는 값을 계산하지 않고, 고른 것을 턴(send)이나 승인(approve)으로만 넘겨요.
import type { ActionKind, ActionOut, CardKind, CardOut, TurnIn } from "@/lib/api/assistant";

export type CardCtx = {
  projectId: string;
  /** 서버 시각(기한 · 오늘 말에만) */
  now: string;
  /** 턴이 도는 중(새 턴은 기다려요) */
  busy: boolean;
  /** 지금 집 정보가 잠겼어요(실측 요청 뒤, lockedNow). 카드 때 값이 아니라 지금 값이라 옛 카드의 고치기 단추도 숨겨요 */
  locked: boolean;
  send: (text: string, context?: TurnIn["context"]) => void;
  /** 제안 행동 승인(home_info 카드의 [맞아요] 등 카드 안 단추) */
  approve: (actionId: string) => void;
  actionOf: (actionId: string) => ActionOut | null;
  pendingOf: (actionId: string) => boolean;
  /** 전체 화면 카드 안 v3 단추로 이미 처리한 행동 */
  handledOf: (actionId: string) => boolean;
  dismissNudge: (cardId: string, nudgeId: string) => void;
  /** 화면에서 고른 이름표(card_id마다). 업체 추천 카드 ↔ 희망 기간 카드가 같이 봐요. 서버에는 choice로만 가요 */
  marks: Record<string, string[]>;
  mark: (cardId: string, refs: string[] | null) => void;
  /** 대화에서 가장 나중의 그 kind 카드 · 그 종류 행동(test를 주면 맞는 것만, 없으면 null) */
  lastCard: <K extends CardKind>(kind: K, test?: (c: CardOut<K>) => boolean) => CardOut<K> | null;
  lastAction: (kind: ActionKind, test?: (a: ActionOut) => boolean) => ActionOut | null;
  /** 대화 기록을 다시 읽어요(조사 카드가 끝난 것을 보면 결과 줄이 보이게) */
  reload?: () => void;
};

export type CardProps<K extends CardKind> = { card: CardOut<K>; ctx: CardCtx; old: boolean };

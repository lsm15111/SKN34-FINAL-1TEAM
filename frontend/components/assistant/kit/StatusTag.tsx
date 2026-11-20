// 상태 표시(v3 N4 C): 아이콘 + 글자, 색은 작은 아이콘에만. 작업 중 · 기다리는 중 · 완료 · 실패 · 취소 · (승인 카드) 내 차례
import type { ReactNode } from "react";
import type { RowState, Source } from "@/lib/api/assistant";
import { I, type IconName } from "./icons";
import k from "./kit.module.css";

export type Tone = RowState | "ok";
const ICON: Record<Tone, IconName> = { running: "spin", waiting: "circle", done: "check", ok: "check", failed: "alert", cancelled: "minus", need: "dot" };
const CLS: Record<Tone, string> = { running: k.running, waiting: k.waiting, done: k.ok, ok: k.ok, failed: k.failed, cancelled: k.cancelled, need: k.need };
/** 작업 상태 기본 글자 */
export const TASK_WORD: Record<"running" | "waiting" | "done" | "failed" | "cancelled", string> = { running: "작업 중", waiting: "기다리는 중", done: "완료", failed: "실패", cancelled: "취소" };

export function StatusTag({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`${k.stat} ${CLS[tone]}`}>
      <I n={ICON[tone]} />
      {children}
    </span>
  );
}

const SRC_WORD: Record<Source, string> = { calc: "믿집 계산", ai: "AI 답변", guide: "믿집 안내" };
/** 묶음마다 출처 이름표: 믿집 계산(계산 엔진) · AI 답변(LLM 글) · 믿집 안내(정해 둔 글) */
export function SourceTag({ src }: { src: Source }) {
  return (
    <span className={src === "ai" ? `${k.src} ${k.srcAi}` : k.src}>
      {src === "ai" ? <I n="sparkle" /> : null}
      {SRC_WORD[src]}
    </span>
  );
}

/** 정한 것 줄(다시 묻지 않기): '벽지는 실크로 정했어요' */
export function DecidedLine({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <p className={k.decided}>
      <I n="check" />
      {children}
      {action}
    </p>
  );
}

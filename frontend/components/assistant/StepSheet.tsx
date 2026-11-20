"use client";
// 전체 화면 카드(2.1): 웹은 가운데 1080 · 뒤 대화는 어둡게, 폰은 화면 전체. kind="dialog"는 가운데 창 560(폰은 아래 시트).
// 닫기 = 뒤로 가기(대화에서 열었으면 대화 자리가 그대로). 링크로 바로 들어왔으면 이 공사 대화로 바꿔 가요(Shell이 정해요).
// 열리면 제목에 초점, Esc로 닫혀요. 안에는 지금 v3 경로 화면의 본문이 그대로 들어와요(머리 · 이동 경로 · 옆 AI 칸은 숨겨요).
import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

/** 겹창 공통: 제목 초점 · Esc 닫기(안쪽 창이 열려 있으면 그것부터) */
export function useOverlay(onClose: () => void): RefObject<HTMLHeadingElement | null> {
  const head = useRef<HTMLHeadingElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  useEffect(() => {
    head.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) close.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return head;
}

/** 겹창 머리: 제목 + 닫기 원 44 */
export function SheetHead({ id, title, head, onClose }: { id: string; title: string; head: RefObject<HTMLHeadingElement | null>; onClose: () => void }) {
  return (
    <div className={s.sheetHead}>
      <h2 id={id} ref={head} tabIndex={-1}>{title}</h2>
      <button type="button" className={s.x} aria-label={`${title} 닫기`} onClick={onClose}><I n="x" /></button>
    </div>
  );
}

export function StepSheet({ title, dialog = false, onClose, children }: { title: string; dialog?: boolean; onClose: () => void; children: ReactNode }) {
  const id = useId();
  const head = useOverlay(onClose);
  return (
    <div className={s.sheetBg} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={dialog ? `${s.sheet} ${s.sheetDialog}` : s.sheet} role="dialog" aria-modal="true" aria-labelledby={id}>
        <SheetHead id={id} title={title} head={head} onClose={onClose} />
        <div className={s.sheetBody}>{children}</div>
      </div>
    </div>
  );
}

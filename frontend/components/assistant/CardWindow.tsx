"use client";
// 카드 창(2.1): 대화 위에 뜨는 창 하나. 경로마다 모양만 달라요 — 전체 화면 카드(웹 가운데 1080 · 뒤 대화는 어둡게, 폰은 화면
// 전체) · 서랍(웹 오른쪽 480, 폰 아래 시트 90%) · 가운데 창(560, 폰 아래 시트). 안에는 v3 경로 화면의 본문이 그대로 들어와요
// (머리 · 이동 경로 · 옆 AI 칸은 숨겨요).
// 창 안에서 다른 카드 주소로 가면 바탕 · 틀은 그대로 두고 안만 바꿔요(iOS 시트 · 머티리얼처럼). 처음 열 때만 올라오고, 모양이
// 바뀌어도(시트 ↔ 서랍 ↔ 가운데 창) 다시 올라오지 않아요. 앞 단계가 있으면 머리 왼쪽 '앞 화면으로'(한 칸 뒤로),
// 바탕 · X · Esc는 창 전체를 닫고 대화로 가요(몇 칸 돌아갈지는 Shell이 정해요). 단계를 옮기면 제목에 초점을 두고,
// 뒤로 · 앞으로 돌아온 단계는 그때 보던 스크롤 자리로, 새 단계는 맨 위에서 열어요. 스크롤은 머리 아래 몸통만 해요.
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

export type WindowKind = "sheet" | "drawer" | "dialog";
/** 창 안 한 단계: 길의 자리 · 주소 · 뒤로 · 앞으로 왔는지 */
export type WindowStep = { at: number; path: string; pop: boolean };

const PANEL: Record<WindowKind, string> = { sheet: s.sheet, dialog: `${s.sheet} ${s.sheetDialog}`, drawer: s.drawer };

export function CardWindow({ kind, title, step, onBack, onClose, children }: {
  kind: WindowKind; title: string; step: WindowStep; onBack?: () => void; onClose: () => void; children: ReactNode;
}) {
  const id = useId();
  const head = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  // 처음 열 때만 올라와요(애니메이션이 끝나면 떼서, 모양을 바꿔도 다시 돌지 않아요)
  const [entering, setEntering] = useState(true);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  // Esc: 안쪽 창(<dialog>, 확정 · 크게 보기)이 열려 있으면 그것부터 닫혀요
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) close.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // 단계마다: 떠난 단계의 스크롤 자리를 적고(내용이 바뀌기 전 값), 돌아온 단계는 그 자리로 · 새 단계는 맨 위로. 제목에 초점
  const tops = useRef(new Map<string, number>());
  const top = useRef(0);
  const shown = useRef<string | null>(null);
  const key = `${step.at}|${step.path}`;
  useLayoutEffect(() => {
    const el = body.current;
    if (el && shown.current !== null && shown.current !== key) {
      tops.current.set(shown.current, top.current);
      el.scrollTop = step.pop ? (tops.current.get(key) ?? 0) : 0;
      top.current = el.scrollTop;
    }
    shown.current = key;
    head.current?.focus({ preventScroll: true });
  }, [key, step.pop]);

  const enter = entering ? "" : undefined;
  return (
    <div className={s.sheetBg} data-enter={enter} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className={PANEL[kind]}
        data-enter={enter}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        onAnimationEnd={(e) => { if (e.target === e.currentTarget) setEntering(false); }}
      >
        <div className={onBack ? `${s.sheetHead} ${s.sheetHeadBack}` : s.sheetHead}>
          {onBack ? <button type="button" className={s.back} aria-label="앞 화면으로" onClick={onBack}><I n="back" /></button> : null}
          <h2 id={id} ref={head} tabIndex={-1}>{title}</h2>
          <button type="button" className={s.x} aria-label={`${title} 닫기`} onClick={onClose}><I n="x" /></button>
        </div>
        <div ref={body} className={s.sheetBody} onScroll={(e) => { top.current = e.currentTarget.scrollTop; }}>{children}</div>
      </div>
    </div>
  );
}

"use client";
// 첫 화면 칸 이름 옆 '?'(2026-11-24 사용자: 실크 · 합지처럼 처음 고객이 모를 말은 쉽게): 누르면 그 자리에 쉬운 말이 떠요.
// 백과 용어는 '자세히'로 용어 칸을 이 화면 위에 열어요(?term=, /start가 OpenTerm을 그려요). 백과에 없는 말은 한두 줄(note)만 둬요.
// 다시 누르기 · Esc · 바깥 누르기 · 초점이 밖으로 나가면 닫혀요(HelpTip · TermTip과 같아요). 펼친 칸은 화면 옆 여백 안에 맞춰요.
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { TermLink } from "@/components/guide/TermPanel";
import t from "./start.module.css";

/** 백과 용어 한 줄(페이지가 용어 사전에서 골라 넘겨요): 주소 이름 · 용어 · 쉬운 말 */
export type StartTip = { id: string; term: string; text: string };

export function TermHelp({ label, tips = [], note }: { label: string; tips?: StartTip[]; note?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const box = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (box.current?.contains(document.activeElement)) btn.current?.focus();
      setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  // 대화 열 밖으로 넘치지 않게 좌우 끝을 화면 옆 여백(--mj-gutter) 안에 맞춰요
  useLayoutEffect(() => {
    const el = pop.current;
    if (!open || !el) return;
    el.style.transform = "";
    const r = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--mj-gutter")) || 16;
    const dx = r.right > vw - gap ? vw - gap - r.right : r.left < gap ? gap - r.left : 0;
    if (dx) el.style.transform = `translateX(${Math.round(dx)}px)`;
  }, [open]);

  if (!tips.length && !note) return null;
  return (
    <span
      ref={box}
      className={t.help}
      onBlur={(e) => { if (open && e.relatedTarget && !box.current?.contains(e.relatedTarget as Node)) setOpen(false); }}
    >
      <button ref={btn} type="button" className={t.helpBtn} aria-label={`${label} 설명`} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        <span aria-hidden="true">?</span>
      </button>
      <span id={id} ref={pop} role="note" className={t.helpPop} hidden={!open}>
        {tips.map((x) => (
          <span key={x.id} className={t.tipRow}>
            <span className={t.tipHead}>
              <b>{x.term}</b>
              <TermLink
                className={t.tipMore}
                term={x.id}
                aria-label={`${x.term} 자세히`}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                  // 용어 칸을 닫으면 초점이 이 '?'로 돌아와요
                  btn.current?.focus();
                  setOpen(false);
                }}
              >
                자세히
              </TermLink>
            </span>
            <span>{x.text}</span>
          </span>
        ))}
        {note ? <span className={t.tipRow}>{note}</span> : null}
      </span>
    </span>
  );
}

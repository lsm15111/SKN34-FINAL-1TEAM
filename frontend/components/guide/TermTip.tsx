"use client";
// 글 속 용어(점선 밑줄): 누르면 바로 아래에 쉬운 말 한 줄이 떠요. 다시 누르기 · Esc · 바깥 누르기 · 초점이 밖으로 나가면 닫혀요.
// Esc로 닫으면 초점을 용어 단추로 돌려줘요. 펼친 칸은 화면 밖으로 넘치지 않게 좌우를 화면 안쪽 12px에 맞춰요(HelpTip과 같은 방식).
// '용어 사전에서 보기'는 글 위에 자세히 칸을 열어요. 풍선은 닫고 초점을 용어 단추에 둬서, 칸을 닫으면 초점이 글 속 그 자리로 돌아와요.
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { TermLink } from "./TermPanel";
import s from "./guide.module.css";

export function TermTip({ label, name, trade, easy, term }: { label: string; name: string; trade: string; easy: string; term: string }) {
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

  useLayoutEffect(() => {
    const el = pop.current;
    if (!open || !el) return;
    el.style.transform = "";
    const r = el.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const dx = r.right > vw - 12 ? vw - 12 - r.right : r.left < 12 ? 12 - r.left : 0;
    if (dx) el.style.transform = `translateX(${Math.round(dx)}px)`;
  }, [open]);

  return (
    <span
      ref={box}
      className={s.termWrap}
      // Tab으로 다른 곳에 초점이 가면 닫아요(글자를 누르는 것처럼 초점이 갈 곳이 없으면 그대로 둬요)
      onBlur={(e) => { if (open && e.relatedTarget && !box.current?.contains(e.relatedTarget as Node)) setOpen(false); }}
    >
      <button ref={btn} type="button" className={s.term} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>{label}</button>
      <span id={id} ref={pop} role="note" className={s.pop} hidden={!open}>
        <span className={s.tag}>{trade}</span>
        <b>{name}</b>
        <span>{easy}</span>
        <TermLink
          term={term}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            btn.current?.focus();
            setOpen(false);
          }}
        >
          용어 사전에서 보기
        </TermLink>
      </span>
    </span>
  );
}

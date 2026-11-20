"use client";
// 글 속 용어(점선 밑줄): 누르면 바로 아래에 쉬운 말 한 줄이 떠요. 다시 누르기 · Esc · 바깥 누르기로 닫혀요.
// 펼친 칸은 화면 밖으로 넘치지 않게 좌우를 화면 안쪽 12px에 맞춰요(HelpTip과 같은 방식).
import Link from "next/link";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import s from "./guide.module.css";

export function TermTip({ label, name, trade, easy, href }: { label: string; name: string; trade: string; easy: string; href: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const box = useRef<HTMLSpanElement>(null);
  const pop = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
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
    <span ref={box} className={s.termWrap}>
      <button type="button" className={s.term} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>{label}</button>
      <span id={id} ref={pop} role="note" className={s.pop} hidden={!open}>
        <span className={s.tag}>{trade}</span>
        <b>{name}</b>
        <span>{easy}</span>
        <Link href={href}>용어 사전에서 보기</Link>
      </span>
    </span>
  );
}

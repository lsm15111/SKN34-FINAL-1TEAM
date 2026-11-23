"use client";
// 글 오른쪽 '이 글에서'(넓은 웹 ≥1280): 지금 읽는 칸을 파랗게 표시하고, 아래에 'AI 채팅에 묻기' 단추를 둬요.
// 읽는 칸은 머리 아래 1/3 지점을 지난 마지막 칸이에요(IntersectionObserver 대신 스크롤로 재서 끝 칸도 잡혀요).
import { useEffect, useState } from "react";
import { AskButton } from "./Triggers";
import s from "./guide.module.css";

export function ArticleToc({ items, canAsk }: { items: { id: string; title: string }[]; canAsk: boolean }) {
  const [cur, setCur] = useState(items[0]?.id ?? "");
  useEffect(() => {
    const els = items.map((x) => document.getElementById(x.id)).filter((e): e is HTMLElement => !!e);
    if (!els.length) return;
    let raf = 0;
    const measure = () => {
      raf = 0;
      const line = window.innerHeight / 3;
      let id = els[0].id;
      for (const el of els) if (el.getBoundingClientRect().top <= line) id = el.id;
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) id = els[els.length - 1].id;
      setCur(id);
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on); if (raf) cancelAnimationFrame(raf); };
  }, [items]);

  return (
    <nav className={s.toc} aria-label="이 글에서">
      <h2>이 글에서</h2>
      <ol>
        {items.map((x) => (
          <li key={x.id}><a href={`#${x.id}`} aria-current={x.id === cur ? "location" : undefined}>{x.title}</a></li>
        ))}
      </ol>
      {canAsk ? <div className={s.tocAsk}><AskButton /></div> : null}
    </nav>
  );
}

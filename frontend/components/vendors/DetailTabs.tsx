"use client";
// 업체 자세히 위 탭(C11 '가견적 · 사례 · 리뷰'). 같은 화면 안 묶음으로 옮겨 가는 바로 가기예요.
// 지금 보이는 묶음의 탭을 굵게 + 밑줄로 보여요(aria-current="true"). 사업자 정보는 탭 없이 맨 아래 접기예요.
import { useEffect, useState, type ReactNode } from "react";
import s from "./vendors3.module.css";

export type TabItem = { id: string; label: ReactNode };

export function DetailTabs({ items }: { items: TabItem[] }) {
  const [now, setNow] = useState(items[0]?.id);
  useEffect(() => {
    const els = items.map((t) => document.getElementById(t.id)).filter((x): x is HTMLElement => !!x);
    if (!els.length || typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, number>();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(e.target.id, e.isIntersecting ? e.intersectionRatio : 0);
      const top = items.find((t) => (seen.get(t.id) ?? 0) > 0);
      if (top) setNow(top.id);
    }, { rootMargin: "-30% 0px -55% 0px", threshold: [0, 0.01] });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [items]);
  return (
    <nav className={s.tabs} aria-label="업체 자세히 바로 가기">
      {items.map((t) => (
        <a key={t.id} href={`#${t.id}`} className={s.tab} aria-current={now === t.id ? "true" : undefined} onClick={() => setNow(t.id)}><span>{t.label}</span></a>
      ))}
    </nav>
  );
}

"use client";
// 업체 자세히 섹션 띠(C11 '가견적 · 시공 사례 · 리뷰'). 같은 화면 안 묶음으로 옮겨 가는 바로 가기예요.
// 머리 묶음 아래에 붙여 한 카드로 보이고, 내리면 위에 붙어요(화면은 붙는 머리 아래, 카드 창은 창 몸통 맨 위).
// 지금 보는 묶음의 탭을 굵게 + 밑줄로 보여요(aria-current): 스크롤 칸(카드 창 몸통 · 없으면 화면)에서 띠 바로 아래 선을 지난
// 마지막 묶음이고, 끝까지 내리면 마지막 묶음이에요(pickSection). 누르면 그 묶음으로 부드럽게 가고 초점도 옮겨요.
// 주소에 #을 붙이지 않아요(카드 창의 뒤로 가기 길이 꼬이지 않게). 사업자 정보는 탭 없이 접기예요.
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { pickSection } from "./v3text";
import s from "./vendors3.module.css";

export type TabItem = { id: string; label: ReactNode };

/** 띠 아래 이만큼 안으로 올라온 묶음을 지금 보는 묶음으로 봐요(누른 묶음은 띠 아래 21px쯤에 멈춰요) */
const LINE = 32;

/** 세로로 스크롤하는 가장 가까운 조상(카드 창 몸통). 없으면 null(화면 전체) */
function scrollRoot(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if (y === "auto" || y === "scroll") return p;
  }
  return null;
}

export function DetailTabs({ items }: { items: TabItem[] }) {
  const bar = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(items[0]?.id);
  // 눌러서 가는 중인 묶음: 그사이 지나가는 묶음으로 표시를 바꾸지 않고, 스크롤이 끝나면(scrollend · 멎음) 놓아요
  const aim = useRef<string | null>(null);
  const moved = useRef(false);
  const picked = useRef<string | null>(null); // 마지막으로 누른 묶음(다음에 직접 스크롤하면 잊어요)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const release = useRef<() => void>(() => {});
  const ids = items.map((t) => t.id).join(" ");

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const list = ids.split(" ");
    const root = scrollRoot(el);
    const box = root ?? document.scrollingElement ?? document.documentElement;
    const target: HTMLElement | Window = root ?? window;
    // scrollend가 있으면 그것으로 놓고, 멎음 시간은 놓친 때만 쓰는 안전 줄이에요(없는 브라우저는 0.15초 멎으면 놓아요)
    const idle = "onscrollend" in window ? 1500 : 150;
    let frame = 0;
    const update = () => {
      frame = 0;
      if (aim.current) return;
      const line = el.getBoundingClientRect().bottom + LINE;
      const boxes = list.flatMap((id) => {
        const r = document.getElementById(id)?.getBoundingClientRect();
        return r ? [{ id, top: r.top, bottom: r.bottom }] : [];
      });
      const end = box.scrollHeight - box.clientHeight > 1 && box.scrollTop > 0 && box.scrollTop + box.clientHeight >= box.scrollHeight - 2;
      const next = pickSection(boxes, line, end, picked.current);
      if (next) setNow(next);
    };
    const letGo = () => { clearTimeout(timer.current); aim.current = null; update(); };
    release.current = letGo;
    const onScroll = () => {
      if (aim.current) {
        moved.current = true;
        clearTimeout(timer.current);
        timer.current = setTimeout(letGo, idle);
        return;
      }
      picked.current = null;
      if (!frame) frame = requestAnimationFrame(update);
    };
    const onEnd = () => { if (aim.current && moved.current) letGo(); };
    const onResize = () => { if (!frame) frame = requestAnimationFrame(update); };
    target.addEventListener("scroll", onScroll, { passive: true });
    target.addEventListener("scrollend", onEnd);
    window.addEventListener("resize", onResize);
    update();
    return () => {
      target.removeEventListener("scroll", onScroll);
      target.removeEventListener("scrollend", onEnd);
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(frame);
      clearTimeout(timer.current);
      release.current = () => {};
    };
  }, [ids]);

  const go = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const sec = document.getElementById(id);
    if (!sec) return;
    e.preventDefault();
    aim.current = id;
    moved.current = false;
    picked.current = id;
    setNow(id);
    // 이미 그 자리라 스크롤이 일지 않으면 1초 뒤에 놓아요
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (!moved.current) release.current(); }, 1000);
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    sec.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    // 읽는 자리도 그 묶음으로(키보드 · 화면 읽기). 화면은 이미 옮기는 중이라 초점이 스크롤을 다시 움직이지 않게
    if (!sec.hasAttribute("tabindex")) sec.setAttribute("tabindex", "-1");
    sec.focus({ preventScroll: true });
  };

  return (
    <div ref={bar} className={s.tabsBar}>
      <nav className={s.tabs} aria-label="업체 자세히 바로 가기">
        {items.map((t) => (
          <a key={t.id} href={`#${t.id}`} className={s.tab} aria-current={now === t.id ? "true" : undefined} onClick={(e) => go(e, t.id)}><span>{t.label}</span></a>
        ))}
      </nav>
    </div>
  );
}

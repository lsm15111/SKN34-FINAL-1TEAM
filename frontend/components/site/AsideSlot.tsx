"use client";
// 옆 AI 칸 자리(N2 A). 내용(대화 · 입력)은 B5가 AsidePanel 안에 채워요.
// - 웹 ≥1024: 본문 첫 묶음과 같은 윗줄에서 붙는 칸. 붙은 뒤 높이 max(460px, 창 − 위 띠 − 32px), 창이 낮으면 입력 칸이 창 아래에 붙어요(top 음수).
//   9판의 100cqh(위 띠 아래 스크롤 칸)를 실제 화면에서는 100dvh − 위 띠 높이(--mj-sticky-top)로 계산해요(tokens.css --mj-aside-*).
//   붙기 전(첫 화면)에는 칸이 아래에서 시작하니, 높이를 '창 높이 − 칸이 시작하는 위치 − 16px'로 줄여 입력 칸이 창 안에 오게 해요.
//   칸이 시작하는 위치는 여기서 재서 --mj-aside-start로 넘기고, 높이 계산은 frame.module.css가 해요.
// - 폰 · 태블릿: 숨겨 두고, 'AI에게 묻기'(AsideOpenButton)를 누르면 전체 화면 층으로 열려요. 주소에 ?ai=1을 얕게 붙여 뒤로 가기로 닫혀요.
// - 대화 목록만 칸 안에서 스크롤하고(overscroll-behavior: contain · 얇은 막대 8px), 끝에 닿아도 페이지가 같이 스크롤되지 않아요.
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { MQ } from "./breakpoints";
import { Icon } from "@/components/ui/Icon";
import s from "./frame.module.css";

const PARAM = "ai";
const EVENT = "mj:aside";
const isOpenUrl = () => new URLSearchParams(window.location.search).get(PARAM) === "1";

type Aside = { layer: boolean; close: () => void; titleId: string };
const Ctx = createContext<Aside>({ layer: false, close: () => {}, titleId: "" });
export const useAside = () => useContext(Ctx);

/** 옆 칸 밖 창(백과 'AI 채팅에 묻기')에서 AsidePanel을 쓸 때: 머리에 ×를 두고 onClose로 닫아요 */
export function AsideHost({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  return <Ctx.Provider value={{ layer: true, close: onClose, titleId }}>{children}</Ctx.Provider>;
}

/** 폰 · 태블릿에서 옆 칸을 전체 화면 층으로 열어요(주소 ?ai=1) */
export function openAside() {
  const u = new URL(window.location.href);
  if (u.searchParams.get(PARAM) === "1") return;
  u.searchParams.set(PARAM, "1");
  history.pushState({ ...history.state, mjAside: true }, "", u);
  window.dispatchEvent(new Event(EVENT));
}
function closeAside() {
  if (history.state?.mjAside) { history.back(); return; }
  const u = new URL(window.location.href);
  u.searchParams.delete(PARAM);
  history.replaceState(history.state, "", u);
  window.dispatchEvent(new Event(EVENT));
}

export function AsideSlot({ children, label }: { children: ReactNode; label: string }) {
  const [layer, setLayer] = useState(false);
  const titleId = useId();
  const ref = useRef<HTMLElement>(null);

  // 웹: 칸이 시작하는 위치(창 기준, 붙는 자리보다 위로는 안 감)를 스크롤 · 창 크기 · 내용 높이가 바뀔 때마다 재요.
  // 칸 자신이 아니라 틀(WithAside)의 윗줄을 재서, 끝에서 칸이 밀려 올라가도 높이가 다시 바뀌지 않아요.
  useEffect(() => {
    const el = ref.current;
    const box = el?.parentElement;
    if (!el || !box) return;
    const mq = window.matchMedia(MQ.web);
    let last = NaN;
    const measure = () => {
      if (!mq.matches) return;
      const stuck = parseFloat(getComputedStyle(el).top) || 0;
      const v = Math.round(Math.max(box.getBoundingClientRect().top, stuck));
      if (v === last) return;
      last = v;
      el.style.setProperty("--mj-aside-start", `${v}px`);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(document.body);
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    mq.addEventListener("change", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      mq.removeEventListener("change", measure);
    };
  }, []);

  useEffect(() => {
    const sync = () => setLayer(isOpenUrl() && !window.matchMedia(MQ.web).matches);
    sync();
    const mq = window.matchMedia(MQ.web);
    window.addEventListener("popstate", sync);
    window.addEventListener(EVENT, sync);
    mq.addEventListener("change", sync);
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener(EVENT, sync); mq.removeEventListener("change", sync); };
  }, []);

  // 층이 열리면 뒤 페이지를 멈추고, Esc로 닫아요
  useEffect(() => {
    if (!layer) return;
    const root = document.documentElement;
    const prev = root.style.overflow;
    root.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) closeAside(); };
    document.addEventListener("keydown", onKey);
    document.getElementById(titleId)?.focus();
    return () => { root.style.overflow = prev; document.removeEventListener("keydown", onKey); };
  }, [layer, titleId]);

  const close = useCallback(() => closeAside(), []);
  return (
    <Ctx.Provider value={{ layer, close, titleId }}>
      <aside ref={ref} className={layer ? `${s.aside} ${s.layer}` : s.aside} aria-label={label} {...(layer ? { role: "dialog", "aria-modal": true } : {})}>
        {children}
      </aside>
    </Ctx.Provider>
  );
}

/** 옆 칸 안 틀: 머리(제목 · 폰 층의 ×) + 스크롤 목록 + 바닥(빠른 질문 칩 · 입력 칸). B5가 채워요 */
export function AsidePanel({ title, head, foot, children, listLabel }: {
  title: string;
  /** 제목 오른쪽(예: 접기 — N5 결정 전이라 아직 비워 둬요) */
  head?: ReactNode;
  /** 빠른 질문 · 입력 칸. 창이 낮아도 늘 보여요 */
  foot?: ReactNode;
  children: ReactNode;
  /** 목록 이름(예: 'AI 대화') */
  listLabel?: string;
}) {
  const { layer, close, titleId } = useAside();
  return (
    <section className={s.panel} aria-labelledby={titleId}>
      <div className={s.panelHead}>
        <h2 id={titleId} className={s.panelTitle} tabIndex={-1}>{title}</h2>
        {head}
        {layer ? <button type="button" className={s.panelX} aria-label="닫기" onClick={close}><Icon name="close" /></button> : null}
      </div>
      <div className={s.list} aria-label={listLabel} role={listLabel ? "region" : undefined}>{children}</div>
      {foot ? <div className={s.foot}>{foot}</div> : null}
    </section>
  );
}

/** 폰 · 태블릿 머리 오른쪽 'AI에게 묻기'. 웹(≥1024)에서는 옆 칸이 늘 보여서 숨겨요 */
export function AsideOpenButton({ children = "AI 채팅" }: { children?: ReactNode }) {
  return <button type="button" className={s.openBtn} onClick={openAside}>{children}</button>;
}

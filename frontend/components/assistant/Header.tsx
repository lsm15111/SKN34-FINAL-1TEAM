"use client";
// 머리: 웹은 로고 · 'AI 비서' · 공사 이름 ▾ · (목업이면 '예시 대본') · 종 · 나, 폰은 ‹ · 공사 이름 · 종.
// 공사 이름 ▾ 메뉴: 내 공사 모두 보기 · 이 공사 서류 · 이전 화면(v3)으로.
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { MOCK_SCRIPTS, type MockScript } from "@/lib/mock/assistant/mode";
import { Bell } from "./Bell";
import { I, Logo } from "./kit/icons";
import { UiSwitchButton } from "./UiSwitch";
import s from "./assistant.module.css";

export function Header({ projectId, name, unread, tick, mock, onMock }: {
  projectId: string;
  name: string;
  unread: number;
  /** 대화가 바뀔 때마다 늘어요(목업 알림 수 다시 읽기) */
  tick: number;
  mock: MockScript | null;
  onMock: (script: MockScript) => void;
}) {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return (
    <header className={s.top}>
      <div className={s.topIn}>
        <span className={s.webOnly}>
          <Link className={s.logo} href="/"><Logo />믿집</Link>
          <span className={s.pill}>AI 비서</span>
          <Pop button={<>{name}<I n="down" /></>} buttonClass={s.proj} left>
            <Link href="/my">내 공사 모두 보기</Link>
            <Link href={`${base}/docs`} scroll={false}>이 공사 서류</Link>
            <UiSwitchButton to="v3">이전 화면(v3)으로 보기</UiSwitchButton>
          </Pop>
        </span>
        <span className={s.phoneOnly}>
          <Link className={s.iconBtn} href="/my" aria-label="내 공사"><I n="back" /></Link>
          <h1 className={s.title}>{name}</h1>
        </span>
        <span className={s.spacer} />
        {mock ? (
          <Pop label="예시 대본 고르기" button={<><I n="sparkle" />예시</>} buttonClass={s.mockBtn}>
            <p className={s.menuNote}>비서 API 전 예시 대본이에요</p>
            {MOCK_SCRIPTS.map((x) => (
              <button key={x.key} type="button" aria-current={mock === x.key ? "true" : undefined} onClick={() => onMock(x.key)}>{x.label}{mock === x.key ? " · 처음부터" : ""}</button>
            ))}
          </Pop>
        ) : null}
        <Bell projectId={projectId} start={unread} tick={tick} />
        <span className={s.webOnly}>
          <Pop label="내 메뉴" button={<span><I n="user" /></span>} buttonClass={s.meBtn}>
            <Link href="/my">내 공사</Link>
            <Link href="/account">내 정보</Link>
            <UiSwitchButton to="v3">이전 화면(v3)으로 보기</UiSwitchButton>
          </Pop>
        </span>
      </div>
    </header>
  );
}

/** 작은 펼침 메뉴(바깥을 누르거나 Esc면 닫혀요) */
function Pop({ label, button, buttonClass, left, children }: { label?: string; button: ReactNode; buttonClass: string; left?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div ref={box} className={s.pop}>
      <button type="button" className={buttonClass} aria-label={label} aria-expanded={open} onClick={() => setOpen((v) => !v)}>{button}</button>
      {open ? <div className={left ? `${s.menu} ${s.menuLeft}` : s.menu} onClick={(e) => { if ((e.target as HTMLElement).closest("a,button")) setOpen(false); }}>{children}</div> : null}
    </div>
  );
}

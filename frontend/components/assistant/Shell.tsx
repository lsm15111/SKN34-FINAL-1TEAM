"use client";
// 비서 대화 한 화면(v4 고객): 머리 · 단계 띠 · 대화 · 입력 칸 · 내 공사 보드 · 카드 자리.
// app/projects/[id]/layout.tsx가 그리고, 아래 경로(page.tsx)는 카드 자리에 들어와요. 레이아웃이라 카드를 열고 닫아도
// 대화 · 스크롤 · 연결이 그대로예요. 닫기는 대화에서 열었으면 뒤로 가기, 링크로 바로 왔으면 이 공사 대화로 바꿔 가요.
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { mockScriptOf, type ActionOut } from "@/lib/api/assistant";
import type { MockScript } from "@/lib/mock/assistant/mode";
import { Board } from "./Board";
import { CardSlot } from "./CardSlot";
import { Composer } from "./Composer";
import { Feed } from "./Feed";
import { Header } from "./Header";
import type { CardCtx } from "./cards/types";
import { useAssistant } from "./hooks/useAssistant";
import type { ActionHandlers } from "./Message";
import { StepBar } from "./StepBar";
import s from "./assistant.module.css";

export function Shell({ projectId, name, unread, children }: { projectId: string; name: string; unread: number; children: ReactNode }) {
  const a = useAssistant(projectId);
  const router = useRouter();
  const path = usePathname();
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const col = useRef<HTMLDivElement>(null);
  const [boardOpen, setBoardOpen] = useState(false);
  const [mock, setMock] = useState<MockScript | null>(null);

  // 이 공사 안에서 다닌 길(닫기 = 뒤로 가기가 이 화면 안에 머무는지 알려고)
  const stack = useRef<string[]>([]);
  const opener = useRef<HTMLElement | null>(null);
  const cardOpen = path.replace(/\/$/, "") !== base;
  useEffect(() => {
    const st = stack.current;
    if (st.length >= 2 && st[st.length - 2] === path) st.pop();
    else if (st[st.length - 1] !== path) st.push(path);
    // 카드를 닫고 대화로 오면 카드를 연 단추로 초점을 돌려요
    if (!cardOpen && opener.current?.isConnected) { opener.current.focus({ preventScroll: true }); opener.current = null; }
  }, [path, cardOpen]);
  const close = useCallback(() => {
    if (stack.current.length > 1) router.back();
    else router.replace(base, { scroll: false });
  }, [router, base]);

  useEffect(() => {
    let alive = true;
    void mockScriptOf(projectId).then((x) => { if (alive) setMock(x); });
    return () => { alive = false; };
  }, [projectId, a.loaded]);

  const last = a.items[a.items.length - 1];
  const liveId = last && last.role === "assistant" && !last.done ? last.id : null;
  const waitingReply = a.running && last?.role === "user";
  const tick = a.items.length + (last?.role === "assistant" && last.done ? 1000 : 0);

  const { approve: approveFn, actionOf, send, pending } = a;
  const ctx: CardCtx = useMemo(() => ({
    projectId,
    now: a.now,
    busy: a.running,
    send: (text, context) => { void send(text, context); },
    approve: (id) => { void approveFn(actionOf(id) ?? id); },
    actionOf,
    pendingOf: (id) => !!pending[id],
    dismissNudge: (cardId, nudgeId) => { void a.dismissNudge(cardId, nudgeId); },
    searchAddress: a.searchAddress,
  }), [projectId, a.now, a.running, send, approveFn, actionOf, pending, a.dismissNudge, a.searchAddress]);

  const act: ActionHandlers = {
    approve: (x) => { void a.approve(x); },
    reject: (x) => { void a.reject(x); },
    remake: (x: ActionOut) => { void a.send(`${x.summary.title} 다시 만들어 줘`); },
    pending: a.pending,
    errors: a.errors,
  };

  const headroom = useCallback(() => col.current?.querySelector<HTMLElement>("[data-stepper]")?.offsetHeight ?? 64, []);
  const scrollTo = useCallback((sel: string) => {
    const el = col.current?.querySelector<HTMLElement>(sel);
    const box = col.current;
    if (!el || !box) return false;
    const msg = el.closest<HTMLElement>("[data-id]") ?? el;
    box.scrollTo({ top: msg.offsetTop - headroom() - 12, behavior: "smooth" });
    return true;
  }, [headroom]);

  return (
    <div className={s.shell}>
      <div inert={cardOpen || boardOpen} style={{ display: "contents" }}>
        <Header projectId={projectId} name={a.board?.project_name && mock ? a.board.project_name : name} unread={unread} tick={tick} mock={mock} onMock={(x) => { void a.reset(x).then(() => setMock(x)); }} />
      </div>
      <div className={s.body}>
        <div
          ref={col}
          className={s.col}
          inert={cardOpen || boardOpen}
          onPointerDownCapture={(e) => { const t = (e.target as HTMLElement).closest<HTMLElement>("a[href^='/projects/'], button"); if (t) opener.current = t; }}
        >
          <div className={s.thread}>
            <StepBar
              base={base}
              editHref={`/start?edit=${encodeURIComponent(projectId)}`}
              current={a.board?.step ?? 0}
              onHome={() => scrollTo("section[aria-label='집 확인'], section[aria-label='주소 찾기']")}
              today={a.board?.today_pin ?? 0}
              onToday={() => { scrollTo("[data-today]"); }}
            />
            <Feed
              items={a.items}
              loaded={a.loaded}
              loadError={a.loadError}
              ctx={ctx}
              act={act}
              liveId={liveId}
              waitingReply={waitingReply}
              scroller={col}
              headroom={headroom}
              onRetry={() => { void a.reload(); }}
            />
            <Composer projectId={projectId} chips={a.chips} busy={a.running} onSend={(t) => { void a.send(t); }} band={a.board?.todo ?? 0} onBand={() => setBoardOpen(true)} />
          </div>
        </div>
        <Board board={a.board} open={boardOpen} flash={a.flash} onClose={() => setBoardOpen(false)} onForget={(id) => { void a.forget(id); }} />
      </div>
      <CardSlot onClose={close}>{children}</CardSlot>
    </div>
  );
}

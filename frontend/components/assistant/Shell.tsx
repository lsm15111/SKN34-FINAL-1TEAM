"use client";
// 비서 대화 한 화면(v4 고객): 머리 · 단계 띠 · 대화 · 입력 칸 · 내 공사 보드 · 카드 자리.
// app/projects/[id]/layout.tsx가 그리고, 아래 경로(page.tsx)는 카드 자리에 들어와요. 레이아웃이라 카드를 열고 닫아도
// 대화 · 스크롤 · 연결이 그대로예요. 닫기는 대화에서 열었으면 뒤로 가기, 링크로 바로 왔으면 이 공사 대화로 바꿔 가요.
// 알림 링크에 ?nudge={id}가 붙어 오면 먼저 말 건 제안을 '열었어요'로 알리고 주소에서 떼요.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { lastActionIn, lastCardIn, lockedNow, mockScriptOf, type ActionOut } from "@/lib/api/assistant";
import type { MockScript } from "@/lib/mock/assistant/mode";
import { Board } from "./Board";
import { CardSlot } from "./CardSlot";
import { Composer } from "./Composer";
import { Feed } from "./Feed";
import { Header } from "./Header";
import type { CardCtx } from "./cards/types";
import { useAssistant } from "./hooks/useAssistant";
import { MyName, type ActionHandlers } from "./Message";
import { StepBar } from "./StepBar";
import s from "./assistant.module.css";

/** me: 로그인한 고객 이름(비서 글의 '고객님'을 그릴 때만 바꿔요, 없으면 null). locked: 처음 연 때 집 정보 잠김(실측 요청 뒤).
 *  siteHeader: 사이트 공통 머리(웹, 레이아웃이 그려 넘겨요). 있으면 비서 머리는 웹에서 얇은 공사 줄만 그려요 */
export function Shell({ projectId, name, me, unread, locked: lockedAtOpen = false, siteHeader, children }: {
  projectId: string; name: string; me: string | null; unread: number; locked?: boolean; siteHeader?: ReactNode; children: ReactNode;
}) {
  const a = useAssistant(projectId);
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const col = useRef<HTMLDivElement>(null);
  const [boardOpen, setBoardOpen] = useState(false);
  const [mock, setMock] = useState<MockScript | null>(null);
  // 카드에서 고른 이름표(card_id마다, 화면에만). 공사 · 목업 대본이 바뀌면 비워요
  const [marks, setMarks] = useState<Record<string, string[]>>({});
  useEffect(() => { setMarks({}); }, [projectId]);
  const mark = useCallback((cardId: string, refs: string[] | null) => setMarks((m) => {
    const { [cardId]: _, ...rest } = m;
    return refs ? { ...rest, [cardId]: refs } : rest;
  }), []);

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

  // 알림에서 온 먼저 말 걸기(?nudge=): 열었다고 알리고 주소에서 떼요
  const nudge = params.get("nudge");
  const { openNudge } = a;
  useEffect(() => {
    if (!nudge) return;
    void openNudge(nudge);
    const q = new URLSearchParams(params.toString());
    q.delete("nudge");
    router.replace(`${path}${q.size ? `?${q}` : ""}`, { scroll: false });
  }, [nudge, openNudge, params, path, router]);

  useEffect(() => {
    let alive = true;
    void mockScriptOf(projectId).then((x) => { if (alive) setMock(x); });
    return () => { alive = false; };
  }, [projectId, a.loaded]);

  // 도는 턴 · 답 기다림은 기록의 마지막 말로 봐요(화면이 만든 말 · 오늘 정할 일이 끝에 와도 입력 중 표시가 꺼지지 않게)
  const tail = a.tail;
  const liveId = tail && tail.role === "assistant" && !tail.done ? tail.id : null;
  const waitingReply = a.running && tail?.role === "user";
  const tick = a.items.length + (tail?.role === "assistant" && tail.done ? 1000 : 0);

  const { approve: approveFn, actionOf, send, pending, handled, dismissNudge, items, reload } = a;
  // 지금 잠김: 처음 연 때 값 + 보드 단계 + 이 대화에서 실행한 실측 요청(카드 때 값 can_change는 그때 모습이에요)
  const locked = lockedNow(lockedAtOpen, a.board, items);
  const home = a.board?.home ?? null;
  const ctx: CardCtx = useMemo(() => ({
    projectId,
    home,
    now: a.now,
    busy: a.running,
    locked,
    send: (text, context) => { void send(text, context); },
    approve: (id) => { void approveFn(actionOf(id) ?? id); },
    actionOf,
    pendingOf: (id) => !!pending[id],
    handledOf: (id) => !!handled[id],
    dismissNudge: (cardId, nudgeId) => { void dismissNudge(cardId, nudgeId); },
    marks,
    mark,
    lastCard: (kind, test) => lastCardIn(items, kind, test),
    lastAction: (kind, test) => lastActionIn(items, kind, test),
    reload: () => { void reload(); },
  }), [projectId, home, a.now, a.running, locked, send, approveFn, actionOf, pending, handled, dismissNudge, marks, mark, items, reload]);

  const act: ActionHandlers = {
    approve: (x) => { void a.approve(x); },
    reject: (x) => { void a.reject(x); },
    remake: (x: ActionOut) => { void a.send(`${x.summary.title} 다시 만들어 줘`); },
    pending: a.pending,
    errors: a.errors,
    handled: a.handled,
    ended: a.ended,
    openNudge: (id) => { void a.openNudge(id); },
    dismissNudge: (id) => { void a.dismissNudge("", id); },
    gone: a.gone,
    settled: a.settled,
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
        {siteHeader}
        <Header projectId={projectId} name={a.board?.project_name && mock ? a.board.project_name : name} unread={unread} tick={tick} mock={mock} site={!!siteHeader} onMock={(x) => { setMarks({}); void a.reset(x).then(() => setMock(x)); }} />
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
              editHref={`${base}/home`}
              current={a.board?.step ?? 0}
              onHome={() => scrollTo("section[aria-label='집 확인']")}
              today={a.board?.today_pin ?? 0}
              onToday={() => { scrollTo("[data-today]"); }}
            />
            <MyName.Provider value={me}>
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
                fresh={a.fresh}
                hasOlder={a.hasOlder}
                olderBusy={a.olderBusy}
                onOlder={() => { void a.loadOlder(); }}
              />
            </MyName.Provider>
            {/* 대화를 못 읽었으면(읽는 중 · 실패) 보내지 않아요: 보낸 말 · 답이 보이지 않은 채 턴만 돌지 않게.
                넘쳐서(503) 끝내 못 보냈으면 send가 "busy"를 돌려주고 입력 칸이 쓴 글을 되살려요 */}
            <Composer projectId={projectId} chips={a.chips} busy={a.running || !a.loaded || !!a.loadError} onSend={(t) => a.send(t)} band={a.board?.todo ?? 0} onBand={() => setBoardOpen(true)} health={a.health} />
          </div>
        </div>
        <Board board={a.board} memory={a.memory} open={boardOpen} flash={a.flash} editHref={`${base}/home`} onClose={() => setBoardOpen(false)} onForget={(id) => { void a.forget(id); }} />
      </div>
      <CardSlot onClose={close}>{children}</CardSlot>
    </div>
  );
}

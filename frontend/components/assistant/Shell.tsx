"use client";
// 비서 대화 한 화면(v4 고객): 머리 · 단계 띠 · 대화 · 입력 칸 · 내 공사 보드 · 카드 자리.
// app/projects/[id]/layout.tsx가 그리고, 아래 경로(page.tsx)는 카드 자리에 들어와요. 레이아웃이라 카드를 열고 닫아도
// 대화 · 스크롤 · 연결이 그대로예요. 카드 창 안에서 주소를 옮기면 창은 그대로 두고 길(trail)에 적어요: '앞 화면으로'는 한 칸 뒤로,
// 닫기(바탕 · X · Esc)는 대화에서 열었으면 쌓인 칸만큼 한 번에 뒤로(history.go), 링크로 바로 왔으면 처음 카드 칸을 대화로 바꿔요.
// 알림 링크에 ?nudge={id}가 붙어 오면 먼저 말 건 제안을 '열었어요'로 알리고 주소에서 떼요.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { lastActionIn, lastCardIn, lockedNow, mockScriptOf, type ActionOut } from "@/lib/api/assistant";
import { canBack, cardsBefore, closePlan, EMPTY_TRAIL, walk, type Move, type Trail } from "@/lib/assistant/trail";
import type { MockScript } from "@/lib/mock/assistant/mode";
import { Board } from "./Board";
import { CardSlot, cardOf } from "./CardSlot";
import type { WindowStep } from "./CardWindow";
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

  // 이 공사 화면이 뜬 뒤 다닌 길(브라우저 기록과 같은 차례, lib/assistant/trail). 주소가 바뀐 까닭은 popstate · Shell의 replace로 알아요
  const here = path.replace(/\/$/, "");
  const cardOpen = here !== base;
  const [trail, setTrail] = useState<Trail>(EMPTY_TRAIL);
  const popTo = useRef<string | null>(null); // 뒤로 · 앞으로가 온 주소
  const replaceTo = useRef<string | null>(null); // Shell이 바꿔 가는 주소
  const goTo = useRef<number | null>(null); // 닫기의 history.go가 갈 길 자리
  const [closing, setClosing] = useState(false);
  const closingRef = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const shown = useRef(here); // 그려 둔 주소(popstate가 같은 주소로 왔는지 보려고)
  const toChat = useCallback(() => {
    replaceTo.current = base;
    router.replace(base, { scroll: false });
  }, [router, base]);
  useEffect(() => {
    const onPop = () => {
      const p = window.location.pathname.replace(/\/$/, "");
      popTo.current = p;
      // 닫는 중 지금과 같은 주소 칸에 닿으면(목록 → 업체 → 목록 · ?view= 같은 얕은 칸) 아래 효과가 돌지 않아서 여기서 길을 옮기고,
      // 라우터가 뒤로 가기를 받은 뒤 그 칸을 대화 주소로 바꿔요
      if (closingRef.current && p !== base && p === shown.current) {
        const to = goTo.current;
        goTo.current = null;
        setTrail((t) => walk(t, p, "pop", to));
        window.setTimeout(toChat, 0);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [base, toChat]);
  // 그리기 전에 길을 적어요(창 머리 '앞 화면으로' · 스크롤 자리가 한 박자 늦게 바뀌지 않게)
  useLayoutEffect(() => {
    shown.current = here;
    const move: Move = replaceTo.current === here ? "replace" : popTo.current === here ? "pop" : "push";
    const to = goTo.current;
    if (move === "replace") replaceTo.current = null; // 바꾸기는 그 주소에 닿을 때만 떼요(사이에 뒤로 가기 칸이 끼어도)
    popTo.current = null;
    goTo.current = null;
    setTrail((t) => walk(t, here, move, to));
    if (cardOpen) {
      // 닫는 중인데 카드 칸에 닿았으면(링크로 바로 연 창의 처음 카드 · 기록이 길보다 길었음) 그 칸을 대화 주소로 바꿔요
      if (closingRef.current) toChat();
      return;
    }
    closingRef.current = false;
    setClosing(false);
    // 카드를 닫고 대화로 오면 카드를 연 칸(대화 · 보드)으로 초점을 돌려요
    if (opener.current?.isConnected) { opener.current.focus({ preventScroll: true }); opener.current = null; }
  }, [here, cardOpen, toChat]);
  // 창 전체 닫기: 대화 자리까지 한 번에 돌아가요. 닫는 사이에는 창을 그리지 않아요(지나가는 카드가 비치지 않게)
  const close = useCallback(() => {
    const plan = closePlan(trail, base);
    closingRef.current = true;
    setClosing(true);
    if (plan.back > 0) {
      goTo.current = trail.at - plan.back;
      window.history.go(-plan.back);
    } else toChat();
  }, [trail, base, toChat]);
  // 1초 안에 대화 자리에 닿지 못하면(기록이 길과 달라 history.go가 움직이지 않음) 지금 칸을 대화 주소로 바꿔요
  useEffect(() => {
    if (!closing) return;
    const t = window.setTimeout(() => {
      if (closingRef.current && window.location.pathname.replace(/\/$/, "") !== base) toChat();
    }, 1000);
    return () => window.clearTimeout(t);
  }, [closing, base, toChat]);
  const step: WindowStep = { at: trail.at, path: trail.list[trail.at] ?? here, pop: trail.move === "pop" };
  const back = canBack(trail, base) ? () => router.back() : undefined;
  // 이 창 앞 칸에 큰 창(업체 보기 · 실측 일정 …)이 있었으면 서랍 주소(업체 자세히)도 큰 창 그대로예요(CardSlot)
  const wide = cardsBefore(trail, base).some((p) => cardOf(p.slice(base.length + 1).split("/"), null)?.kind === "sheet");
  const markOpener = (target: EventTarget) => {
    const t = (target as HTMLElement).closest<HTMLElement>("a[href^='/projects/'], button");
    if (t) opener.current = t;
  };

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
    slots: a.slotsNow,
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
      {/* 카드를 연 단추(대화 · 보드 칸, 누르거나 Enter)를 기억해 닫으면 그리로 초점을 돌려요 */}
      <div
        className={s.body}
        onPointerDownCapture={(e) => markOpener(e.target)}
        onKeyDownCapture={(e) => { if (e.key === "Enter" || e.key === " ") markOpener(e.target); }}
      >
        <div ref={col} className={s.col} inert={cardOpen || boardOpen}>
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
        <Board board={a.board} failed={a.boardFailed} onRetry={a.retryBoard} open={boardOpen} flash={a.flash} base={base} onClose={() => setBoardOpen(false)} />
      </div>
      <CardSlot step={step} wide={wide} onBack={back} onClose={close} hidden={closing}>{children}</CardSlot>
    </div>
  );
}

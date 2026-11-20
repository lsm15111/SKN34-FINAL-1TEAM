// 옆 AI 칸 · 폰 전체 화면 AI (C09 · D01 · D03 · D06~D08 · D15~D19). 자리는 B4의 WithAside · AsidePanel이고, 내용은 여기(B5).
// - 사용자 · 프로젝트는 서버가 세션으로 정해요. 화면은 보던 화면(screen)과 프로젝트 id만 보내요.
// - 처음 열 때 AI 알림 한 번(AI 기본법 · 9판 C09). 닫은 것은 이 기기에만 기억해요(실패해도 다시 보여 줄 뿐).
// - 같은 공사 화면 사이를 옮겨도 layout이 이 조각을 그대로 두면 대화가 이어져요(F7 A).
// - 질문 + 답을 한 턴으로 그려요. 보내면 새 질문이 대화 목록 맨 위로 올라가고 답은 그 아래로 자라요(긴 답도 첫 줄부터 읽게).
//   마지막 턴은 목록 높이만큼 자리를 잡아 짧은 답이어도 질문이 위로 올라가요. 답이 오는 동안 · 온 뒤에는 스크롤을 건드리지 않아요.
//   위로 올려 읽다가 마지막 질문이 목록 아래로 숨으면 '최신 대화로' 단추가 떠요.
// - LLM 모드는 고정 몫(계산 결과 · 정해 둔 글)이 먼저 오고(part), 같은 자리 아래로 AI 글이 이어 붙어요(이미 보인 글은 바뀌지 않아요).
"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AsidePanel } from "@/components/site/AsideSlot";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { errorText } from "@/lib/backend/client";
import { askAi, newClientKey, type AiAnswer as AiAnswerT, type AiButton, type AiScreen, type AiTurnOut } from "@/lib/api/chat";
import { AiAnswer } from "./AiAnswer";
import s from "./ai.module.css";

const NOTICE = "AI가 답해요. 금액 · 날짜는 믿집 계산을 그대로 보여 주고, 저장 · 확정은 하지 않아요.";
const NOTICE_KEY = "mj-ai-notice-seen";
const MAX = 1000;
const CHIPS: Partial<Record<AiScreen, string[]>> = {
  standard: ["철거는 왜 합계에 안 들어가요?", "합지랑 실크는 뭐가 달라요?", "며칠 걸려요?"],
  vendors: ["가견적은 어떻게 나와요?", "업체 견적은 왜 달라요?"],
  vendor: ["가견적은 어떻게 나와요?", "실측은 돈이 들어요?"],
  visits: ["실측 날짜는 어떻게 정해요?", "업체가 언제 답해 줘요?"],
  visit_request: ["실측 일정 요청 초안 만들어 줘", "실측 날짜는 어떻게 정해요?"],
  quotes: ["실측 견적서 두 곳은 어떻게 비교해요?"],
  plan: ["공사 순서가 어떻게 돼요?"],
};
const PLACEHOLDER: Partial<Record<AiScreen, string>> = {
  standard: "이 견적서에 대해 물어보세요", visits: "일정에 대해 물어보세요", visit_request: "일정에 대해 물어보세요",
};
const TOP_GAP = 8; // 올린 질문 위 여백(px)
const AUTO_MS = 700; // 질문을 올리는 부드러운 스크롤 동안은 '최신 대화로' 단추를 다시 재지 않아요

/** part: LLM 모드에서 먼저 온 고정 몫. out: 마지막 답(앞 묶음이 part와 같아요) */
type Turn = { id: number; q: string; part?: AiAnswerT; out?: AiTurnOut };

function seenNotice(): boolean {
  try {
    return window.localStorage.getItem(NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

/** 가장 가까운 세로 스크롤 칸(옆 칸 · 폰 층의 대화 목록). 없으면 null(페이지가 스크롤해요) */
function scroller(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement ?? null; p; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if (oy === "auto" || oy === "scroll") return p;
  }
  return null;
}

/** 턴(질문)을 스크롤 칸 맨 위로. 칸만 스크롤해서 페이지는 움직이지 않아요. 움직임 줄이기 설정이면 바로 가요 */
function toTurn(el: HTMLElement) {
  const behavior: ScrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const box = scroller(el);
  if (!box) {
    el.scrollIntoView({ block: "nearest", behavior });
    return;
  }
  const from = box.scrollTop;
  const top = Math.max(0, el.getBoundingClientRect().top - box.getBoundingClientRect().top + from - TOP_GAP);
  box.scrollTo({ top, behavior });
  // 부드러운 스크롤이 시작도 못 했으면(화면에 안 그려지는 탭 등) 바로 옮겨요. 그사이 손으로 움직였으면 두어요
  if (behavior === "smooth" && Math.abs(top - from) > 1) {
    window.setTimeout(() => {
      if (Math.abs(box.scrollTop - from) < 1) box.scrollTo({ top });
    }, AUTO_MS);
  }
}

export function AiPanel({ screen, projectId, ids, embed = false }: {
  screen: AiScreen;
  projectId?: string;
  /** 보던 것(실측 · 업체 id 등, 5개까지). 서버가 본인 것인지 다시 봐요 */
  ids?: string[];
  /** 예전 '보는 중' 줄 글. 11-19부터 보이지 않아요(부르는 쪽 호환으로만 받아요) */
  context?: string;
  /** 다른 옆 칸 안에 끼울 때(예: 확정 공정표 '공사 전 할 일' 칸 아래). 칸 틀(AsidePanel) 없이 대화 · 입력만 그려요 */
  embed?: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(false); // 서버 그림과 같게 시작하고, 열린 뒤 이 기기 기록을 봐요
  const [away, setAway] = useState(false); // 마지막 질문이 목록 아래로 숨었어요(위로 올려 읽는 중)
  const seq = useRef(0);
  const msgsRef = useRef<HTMLDivElement>(null);
  const lastRef = useRef<HTMLDivElement>(null);
  const autoUntil = useRef(0);
  useEffect(() => {
    if (!seenNotice()) setNotice(true);
  }, []);

  function closeNotice() {
    setNotice(false);
    try {
      window.localStorage.setItem(NOTICE_KEY, "1");
    } catch {
      /* 저장이 막혀도 다음에 한 번 더 보일 뿐이에요 */
    }
  }

  /** 마지막 턴 자리 = 목록 높이(끼운 칸은 입력 칸이 목록 안에 있어서 자리를 잡지 않아요) */
  function sizeLast() {
    const el = msgsRef.current;
    const box = scroller(el);
    if (!el || !box || embed) return;
    el.style.setProperty("--mj-turn-min", `${Math.max(0, box.clientHeight - TOP_GAP - 4)}px`);
  }

  function jump() {
    if (!lastRef.current) return;
    autoUntil.current = performance.now() + AUTO_MS;
    setAway(false);
    toTurn(lastRef.current);
  }

  const count = turns.length;
  // 새 질문을 보냈을 때만 그 질문을 목록 맨 위로 올려요(답이 올 때는 움직이지 않아요)
  useLayoutEffect(() => {
    if (!count) return;
    sizeLast();
    jump();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);

  // 목록 높이가 바뀌면(창 크기 · 칩이 사라짐 · 폰 층이 열림) 마지막 턴 자리도 다시 재요
  useEffect(() => {
    const box = scroller(msgsRef.current);
    if (!box || embed) return;
    const ro = new ResizeObserver(() => sizeLast());
    ro.observe(box);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embed]);

  // 위로 올려 읽다가 마지막 질문이 목록 아래로 숨으면 '최신 대화로' 단추를 보여요
  useEffect(() => {
    const box = scroller(msgsRef.current);
    if (!box || !count) return;
    const check = () => {
      if (performance.now() < autoUntil.current) return;
      const last = lastRef.current;
      setAway(!!last && last.getBoundingClientRect().top > box.getBoundingClientRect().bottom - 24);
    };
    box.addEventListener("scroll", check, { passive: true });
    return () => box.removeEventListener("scroll", check);
  }, [count]);

  async function send(q: string, button?: AiButton) {
    const t = q.trim().slice(0, MAX);
    if (!t || busy) return;
    const id = ++seq.current;
    const put = (patch: Partial<Turn>) => setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    setBusy(true);
    setError("");
    setTurns((ts) => [...ts, { id, q: t }]);
    setText("");
    try {
      const out = await askAi({
        client_key: newClientKey(), text: t, chat_id: chatId,
        context: { screen, project_id: projectId ?? null, ids: ids?.slice(0, 5) ?? [] }, button: button ?? null,
      }, { onPart: (part) => put({ part }) });
      if (out.chat_id) setChatId(out.chat_id);
      put({ out });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const chips = turns.length ? [] : CHIPS[screen] ?? ["처음이라 순서를 알고 싶어요", "표준견적서는 업체 견적이에요?"];
  const foot = (
    <>
      {chips.length ? (
        <div className={s.choices}>
          {chips.map((c) => <Button key={c} variant="weak" size="sm" onClick={() => send(c)}>{c}</Button>)}
        </div>
      ) : null}
      {error ? <p className={s.error} role="alert">{error}</p> : null}
      <form className={s.composer} onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <label className="mj-sr" htmlFor="ai-input">AI에게 물을 말</label>
        <textarea
          id="ai-input" className={s.input} rows={1} maxLength={MAX} value={text}
          placeholder={PLACEHOLDER[screen] ?? "궁금한 걸 물어보세요"} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); } }}
        />
        <Button type="submit" busy={busy} disabled={!text.trim()}>{busy ? "답 기다리는 중" : "보내기"}</Button>
      </form>
    </>
  );

  const body = (
      <div ref={msgsRef} className={s.msgs} aria-live="polite">
        {notice ? (
          <div className={s.notice1}>
            <p>{NOTICE}</p>
            <div><Button variant="secondary" size="sm" onClick={closeNotice}>알겠어요</Button></div>
          </div>
        ) : null}
        {turns.map((t, i) => {
          const last = i === turns.length - 1;
          const waiting = last && busy && !t.out;
          return (
            <div key={t.id} ref={last ? lastRef : undefined} className={last && !embed ? `${s.turn} ${s.turnLast}` : s.turn}>
              <p className={s.user}>{t.q}</p>
              {t.out ? (
                <AiAnswer key="a" answer={t.out.answer} projectId={projectId} onPick={(q, b) => void send(q, b)} />
              ) : t.part && (waiting || t.part.sections.length) ? (
                <AiAnswer key="a" answer={t.part} projectId={projectId} pending={waiting} />
              ) : waiting ? (
                <p className={s.working} role="status">
                  <span className="mj-sr">답을 기다리는 중이에요</span>
                  <span className={s.dots} aria-hidden="true"><i /><i /><i /></span>
                </p>
              ) : null}
            </div>
          );
        })}
        <div className={s.jumpWrap}>
          {away ? (
            <button type="button" className={s.jump} aria-label="최신 대화로" onClick={jump}>
              <Icon name="chevron-down" />
            </button>
          ) : null}
        </div>
      </div>
  );
  if (embed) {
    return (
      <div className={s.embed}>
        {body}
        {foot}
      </div>
    );
  }
  return (
    <AsidePanel title="AI 채팅" listLabel="AI 대화" foot={foot}>
      {body}
    </AsidePanel>
  );
}

// 옆 AI 칸 · 폰 전체 화면 AI (C09 · D01 · D03 · D06~D08 · D15~D19). 자리는 B4의 WithAside · AsidePanel이고, 내용은 여기(B5).
// - 사용자 · 프로젝트는 서버가 세션으로 정해요. 화면은 보던 화면(screen)과 프로젝트 id만 보내요.
// - 처음 열 때 AI 알림 한 번(AI 기본법 · 9판 C09). 닫은 것은 이 기기에만 기억해요(실패해도 다시 보여 줄 뿐).
// - 같은 공사 화면 사이를 옮겨도 layout이 이 조각을 그대로 두면 대화가 이어져요(F7 A).
// - 화면을 옮겨 새로 열려도 같은 공사(없으면 공사 밖)의 24시간 안 마지막 대화를 이어 가요(맥락 L2). 지난 턴은 저장된 글로만 보여요.
//   '새 대화'를 누르면 비워요. 접은 대화는 이 기기에서 다시 잇지 않고, 다음 질문부터 새 대화방이에요.
// - 공사 화면은 되묻기에 답한 칸을 '기억한 조건' 칩으로 보여요(맥락 L3). X로 지우면 AI가 그 칸을 다시 물어요.
// - 공사가 없는 화면(자주 묻는 질문 등)은 진행 중인 내 공사를 '○○ 기준' 칩으로 보여요. 하나면 그 공사로 묻고,
//   둘 이상이면 고르게 해요. 칩을 눌러 다른 공사로 바꾸거나 '공사 빼고 묻기'로 끌 수 있어요(고른 공사 id만 보내요).
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
import {
  askAi, deleteAiCondition, getAiConditions, getAiProjects, getLatestAiThread, newClientKey,
  type AiAnswer as AiAnswerT, type AiButton, type AiCondition, type AiProjectPick, type AiScreen, type AiThreadDetail,
  type AiTurnOut,
} from "@/lib/api/chat";
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
const CLOSED_KEY = "mj-ai-closed"; // '새 대화'로 접은 대화 id(공사마다, 이 기기만)

/** part: LLM 모드에서 먼저 온 고정 몫. out: 마지막 답(앞 묶음이 part와 같아요). old: 이어 온 지난 턴의 저장된 답 글 */
type Turn = { id: number; q: string; part?: AiAnswerT; out?: AiTurnOut; old?: string };

function seenNotice(): boolean {
  try {
    return window.localStorage.getItem(NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

function closedChat(projectId?: string): string | null {
  try {
    return window.localStorage.getItem(`${CLOSED_KEY}:${projectId ?? "none"}`);
  } catch {
    return null;
  }
}

function closeChat(projectId: string | undefined, chatId: string) {
  try {
    window.localStorage.setItem(`${CLOSED_KEY}:${projectId ?? "none"}`, chatId);
  } catch {
    /* 저장이 막혀도 다른 화면에서 그 대화가 이어질 뿐이에요 */
  }
}

/** 저장된 줄(질문 · 답)을 턴으로 묶어요. id는 음수라 새로 묻는 턴(양수)과 겹치지 않아요 */
function pastTurns(d: AiThreadDetail): Turn[] {
  const by = new Map<number, Turn>();
  for (const m of d.messages) {
    const t = by.get(m.turn) ?? { id: -m.turn, q: "", old: "" };
    if (m.role === "user") t.q = m.text;
    else t.old = m.text;
    by.set(m.turn, t);
  }
  return [...by.values()].filter((t) => t.q);
}

const OLD_LINES = 3; // 이어 온 지난 답은 앞 줄만 보여요

/** 이어 온 지난 답: 저장된 글의 앞 3줄 + '자세히 보기'(지금 답의 짧은 답과 같은 모양) */
function OldAnswer({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const lines = text.split("\n").filter(Boolean);
  const more = lines.length - OLD_LINES;
  return (
    <div className={s.answer}>
      <p className={s.old}>{(open || more <= 0 ? lines : lines.slice(0, OLD_LINES)).join("\n")}</p>
      {more > 0 ? (
        <Button variant="text" size="sm" className={s.more} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "짧게 보기" : `자세히 보기 · ${more}줄 더`}
        </Button>
      ) : null}
    </div>
  );
}

/** 가장 가까운 세로 스크롤 칸(옆 칸 · 폰 층의 대화 목록). 없으면 null(페이지가 스크롤해요) */
function scroller(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement ?? null; p; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if (oy === "auto" || oy === "scroll") return p;
  }
  return null;
}

/** 턴(질문)을 스크롤 칸 맨 위로. 칸만 스크롤해서 페이지는 움직이지 않아요. 움직임 줄이기 설정 · now(이어 온 대화)면 바로 가요 */
function toTurn(el: HTMLElement, now = false) {
  const behavior: ScrollBehavior = now || window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
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
  const [conds, setConds] = useState<AiCondition[]>([]);
  const [ready, setReady] = useState(false); // 이어 볼 대화를 찾은 뒤(못 찾아도) 빠른 질문 칩을 보여요(깜빡임 없게)
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(false); // 서버 그림과 같게 시작하고, 열린 뒤 이 기기 기록을 봐요
  const [away, setAway] = useState(false); // 마지막 질문이 목록 아래로 숨었어요(위로 올려 읽는 중)
  const seq = useRef(0);
  const msgsRef = useRef<HTMLDivElement>(null);
  const lastRef = useRef<HTMLDivElement>(null);
  const autoUntil = useRef(0);
  const instant = useRef(false); // 이어 온 대화는 부드럽게 굴리지 않고 바로 마지막 턴으로 가요
  const [mine, setMine] = useState<AiProjectPick[] | null>(null); // 공사 없는 화면: 진행 중인 내 공사(받기 전 null)
  const [picked, setPicked] = useState<string | null | undefined>(undefined); // undefined: 안 고름 · null: 공사 빼고
  const [menu, setMenu] = useState(false);
  const scopeRef = useRef<HTMLDivElement>(null);
  const auto = mine?.length === 1 ? mine[0].id : undefined;
  /** 이 대화가 기준으로 삼는 공사: 공사 화면이면 그 공사, 아니면 칩에서 고른(하나뿐이면 그) 공사 */
  const pid = projectId ?? (picked === undefined ? auto : picked ?? undefined);
  const scopeReady = !!projectId || mine !== null;
  useEffect(() => {
    if (!seenNotice()) setNotice(true);
  }, []);

  // 공사 없는 화면이면 진행 중인 내 공사를 받아 칩을 만들어요(못 받으면 칩 없이 공사 밖 대화)
  useEffect(() => {
    if (projectId) return;
    let off = false;
    getAiProjects()
      .then((ps) => { if (!off) setMine(ps); })
      .catch(() => { if (!off) setMine([]); });
    return () => {
      off = true;
    };
  }, [projectId]);

  // 칩 메뉴는 바깥을 누르거나 Esc로 닫아요
  useEffect(() => {
    if (!menu) return;
    const out = (e: PointerEvent) => { if (!scopeRef.current?.contains(e.target as Node)) setMenu(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    document.addEventListener("pointerdown", out);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", out);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  // 이어 볼 대화 · 기억한 조건을 받아요. 받기 전에 이미 물었거나 '새 대화'를 눌렀으면(seq가 바뀜) 대화는 덮지 않아요
  useEffect(() => {
    if (!scopeReady) return;
    let off = false;
    const at = seq.current;
    setReady(false);
    void Promise.all([
      getLatestAiThread(pid).catch(() => null),
      pid ? getAiConditions(pid).catch(() => null) : Promise.resolve([] as AiCondition[]),
    ]).then(([d, cs]) => {
      if (off) return;
      if (cs) setConds(cs);
      if (seq.current === at) {
        const past = d && d.chat_id !== closedChat(pid) ? pastTurns(d) : [];
        instant.current = past.length > 0;
        setChatId(past.length && d ? d.chat_id : null);
        setTurns(past);
      }
      setReady(true);
    });
    return () => {
      off = true;
    };
  }, [pid, scopeReady]);

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

  function jump(now = false) {
    if (!lastRef.current) return;
    autoUntil.current = performance.now() + AUTO_MS;
    setAway(false);
    toTurn(lastRef.current, now);
  }

  const count = turns.length;
  // 새 질문을 보냈을 때 · 지난 대화를 이어 왔을 때만 마지막 질문을 목록 맨 위로 올려요(답이 올 때는 움직이지 않아요)
  useLayoutEffect(() => {
    if (!count) return;
    sizeLast();
    jump(instant.current);
    instant.current = false;
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
        context: { screen, project_id: pid ?? null, ids: ids?.slice(0, 5) ?? [] }, button: button ?? null,
      }, { onPart: (part) => put({ part }) });
      if (out.chat_id) setChatId(out.chat_id);
      if (pid && out.conditions) setConds(out.conditions);
      put({ out });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  /** '새 대화': 지금 대화를 접고 비워요. 다음 질문부터 새 대화방이라 이어 묻기 맥락도 새로 시작해요 */
  function fresh() {
    if (busy) return;
    if (chatId) closeChat(pid, chatId);
    seq.current += 1; // 아직 오는 이어 보기 결과가 비운 대화를 다시 채우지 않게
    setChatId(null);
    setTurns([]);
    setError("");
    setAway(false);
  }

  /** 칩에서 기준 공사를 바꿔요(null: 공사 빼고). 그 공사의 이어 볼 대화를 새로 받아요 */
  function choose(id: string | null) {
    setMenu(false);
    if (busy || id === (pid ?? null)) return;
    setPicked(id);
    setChatId(null);
    setTurns([]);
    setConds([]);
    setError("");
  }

  async function dropCond(key: string) {
    if (!pid) return;
    setError("");
    try {
      setConds(await deleteAiCondition(pid, key));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const chips = !ready || turns.length ? [] : CHIPS[screen] ?? ["처음이라 순서를 알고 싶어요", "표준견적서는 업체 견적이에요?"];
  const newChat = turns.length ? (
    <Button variant="text" size="sm" className={s.newChat} disabled={busy} onClick={fresh}>
      <Icon name="plus" size={16} />새 대화
    </Button>
  ) : null;
  const pidName = mine?.find((p) => p.id === pid)?.name;
  const scope = !projectId && mine?.length ? (
    <div ref={scopeRef} className={s.scopeWrap}>
      <button type="button" className={s.scope} aria-expanded={menu} aria-haspopup="menu" onClick={() => setMenu((v) => !v)}>
        <span className={s.condText}>{pidName ? `${pidName} 기준` : picked === null ? "공사 빼고 묻는 중" : "어느 공사 기준으로 볼까요?"}</span>
        <Icon name="chevron-down" size={16} />
      </button>
      {menu ? (
        <div className={s.scopeMenu} role="menu" aria-label="기준 공사">
          {mine.map((p) => (
            <button key={p.id} type="button" role="menuitemradio" aria-checked={p.id === pid} onClick={() => choose(p.id)}>{p.name}</button>
          ))}
          <button type="button" role="menuitemradio" aria-checked={!pid} onClick={() => choose(null)}>공사 빼고 묻기</button>
        </div>
      ) : null}
    </div>
  ) : null;
  const foot = (
    <>
      {scope}
      {conds.length ? (
        <div className={s.conds} role="group" aria-label="기억한 조건">
          <span className={s.condsHead} aria-hidden="true">기억한 조건</span>
          {conds.map((c) => (
            <span key={c.key} className={s.cond}>
              <span className={s.condText}>{c.label}: {c.value}</span>
              <button type="button" className={s.condX} aria-label={`${c.label} 조건 지우기`} onClick={() => void dropCond(c.key)}>
                <Icon name="close" size={16} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      {chips.length ? (
        <div className={s.choices}>
          {chips.map((c) => <Button key={c} variant="weak" size="sm" onClick={() => send(c)}>{c}</Button>)}
        </div>
      ) : null}
      {error ? <p className={s.error} role="alert">{error}</p> : null}
      {embed && newChat ? <div className={s.embedNew}>{newChat}</div> : null}
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
                <AiAnswer key="a" answer={t.out.answer} projectId={pid} onPick={(q, b) => void send(q, b)} />
              ) : t.old !== undefined ? (
                t.old ? <OldAnswer text={t.old} /> : null
              ) : t.part && (waiting || t.part.sections.length) ? (
                <AiAnswer key="a" answer={t.part} projectId={pid} pending={waiting} />
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
            <button type="button" className={s.jump} aria-label="최신 대화로" onClick={() => jump()}>
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
    <AsidePanel title="AI 채팅" listLabel="AI 대화" head={newChat} foot={foot}>
      {body}
    </AsidePanel>
  );
}

"use client";
// v2 화면 껍데기 (v10 머리 · route · showChat · startFlow · renderSteps · resetCtl · onSend · boot).
// 첫 화면(#)과 상담 화면(#chat)을 주소 뒤 #으로 나눈다. 단계 화면은 F 표의 함수가 대화에 카드로 붙인다.
import { useEffect, useRef, useState } from "react";
import { Board, BoardBand } from "./Board";
import { CAT, type Material, MODE_LABEL, STEP_INDEX, STEPS, type StyleData } from "./data";
import { bot, busy, F, Feed, me, Overlays, Quick, quick, resetFeed, Toast, useFeed } from "./engine";
import { stepFn } from "./flow";
import { Home } from "./home/Home";
import "./modules";
import { setImgMode, view } from "./photo";
import { chat, DATA, loadSaved, resetState, S, store, touch, useV2 } from "./store";
import s from "./v2.module.css";

/** 첫 화면에서 상담을 어떻게 시작할지 (v10 startMode · pendingAsk · pendingTool · pendingLook) */
export const start = { mode: null as null | "resume" | "quick" | "ask" | "tool" | "look", ask: "", tool: "", look: "", style: "" };
export function goChat(mode: typeof start.mode = null, extra: Partial<typeof start> = {}) {
  Object.assign(start, { mode }, extra);
  chat.built = false;
  location.hash = "chat";
}

function useHash() {
  const [hash, setHash] = useState("");
  useEffect(() => {
    const on = () => setHash(location.hash.replace("#", ""));
    on();
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

async function startFlow() {
  const mode = start.mode;
  start.mode = null;
  if (mode === "resume") {
    const v = loadSaved();
    if (v) {
      Object.assign(S, v, { photos: [], refs: [], imgMode: S.imgMode });
      S.scope.cats = (S.scope.cats || []).filter((c) => CAT[c]);
      S.picks = Object.fromEntries(Object.entries(S.picks || {}).filter(([c, id]) => CAT[c] && DATA.materials.some((m) => m.id === id && m.cat === c)));
      touch();
      await bot("지난번에 고른 걸 불러왔어요. 이어서 할게요.");
      return S.far >= 5 ? F.matStep() : stepFn(STEPS[S.far][0])();
    }
  }
  if (mode === "quick") {
    Object.assign(S.scope, { kind: "all", spaces: [], cats: [] });
    S.guideSeen = true;
    S.far = 5;
    touch();
    await bot("스탠다드로 골라 뒀어요. 평형 · 예산은 위 단계를 눌러 바꿀 수 있어요.");
    return F.matStep();
  }
  if (mode === "ask" && start.ask) {
    const q = start.ask;
    start.ask = "";
    await F.askClaude(q, { label: q });
    quick([["처음부터 시작하기", () => F.welcome()]]);
    return;
  }
  if (mode === "tool" && start.tool) {
    const t = start.tool;
    start.tool = "";
    await (t === "calc" ? F.calcStep() : F.checkStep());
    quick([["처음부터 시작하기", () => F.welcome()]]);
    return;
  }
  if (mode === "look" && start.style) {
    const ok = F.startLook?.(start.style, start.look);
    start.style = start.look = "";
    if (ok) return;
  }
  F.welcome();
}

function Steps() {
  useV2();
  const ref = useRef<HTMLElement>(null);
  const now = STEP_INDEX[S.step] ?? 0;
  useEffect(() => {
    const el = ref.current, cur = el?.querySelector<HTMLElement>(".now");
    if (el && cur && el.scrollWidth > el.clientWidth) el.scrollLeft = Math.max(0, cur.offsetLeft - el.clientWidth / 2 + cur.offsetWidth / 2);
  });
  return (
    <nav className="steps" aria-label="상담 진행" ref={ref}>
      {STEPS.map(([id, ko], i) => {
        const done = i < now || (i <= S.far && i !== now);
        return (
          <button
            key={id}
            type="button"
            className={i === now ? "now" : done ? "done" : ""}
            aria-current={i === now ? "step" : undefined}
            title={done ? `${ko} 고치기` : undefined}
            onClick={() => {
              if (done && !busy.asking) stepFn(id)();
            }}
          >
            {ko}
          </button>
        );
      })}
    </nav>
  );
}

function ResetCtl({ onReset }: { onReset: () => void }) {
  const [ask, setAsk] = useState(false);
  if (!ask)
    return (
      <span>
        <button type="button" className="btn-text gray" onClick={() => setAsk(true)}>처음부터</button>
      </span>
    );
  return (
    <span>
      <span className="reset-ask">
        모두 지울까요?
        <button type="button" className="btn-text" style={{ color: "var(--danger)" }} onClick={onReset}>지우기</button>
        <button type="button" className="btn-text gray" onClick={() => setAsk(false)}>취소</button>
      </span>
    </span>
  );
}

/** 흐름 단어는 버튼 흐름으로, 나머지는 AI로 (v10 routeText · onSend) */
function routeText(t: string) {
  if (/순서|공정.*(뭐|설명|알려)/.test(t) && t.length < 25) return () => F.guideStep(false);
  if (/스타일.*(다시|바꿔)/.test(t) && t.length < 20) return () => F.reopenStyles();
  return null;
}

function Composer() {
  useV2();
  const f = useFeed();
  const [text, setText] = useState("");
  const [withPhotos, setWithPhotos] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);
  const send = async () => {
    const t = text.trim();
    if (!t || busy.asking) return;
    setText("");
    if (ta.current) ta.current.style.height = "auto";
    if (!S.typed) {
      S.typed = true;
      F.collapseRail?.();
    }
    me(t);
    const r = routeText(t);
    if (r) return r();
    await F.askClaude(t, { withPhotos });
  };
  void f;
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <BoardBand />
      <Quick />
      <div className="cbox">
        <textarea
          ref={ta}
          id="chat-in"
          rows={1}
          placeholder="궁금한 걸 물어보세요"
          aria-label="메시지"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="send" type="submit" aria-label="보내기" disabled={!!busy.asking}>↑</button>
      </div>
      <label className="with-photos" id="send-photos-l" hidden={!(S.photos.length || S.refs.length)}>
        <input type="checkbox" id="send-photos" checked={withPhotos} onChange={(e) => setWithPhotos(e.target.checked)} />
        사진 같이 보내기
      </label>
    </form>
  );
}

function ChatView() {
  const [key, setKey] = useState(0);
  useEffect(() => {
    if (chat.built) return;
    chat.built = true;
    startFlow();
  }, [key]);
  const reset = () => {
    resetFeed();
    resetState();
    F.resetLocal?.();
    chat.built = false;
    window.scrollTo(0, 0);
    setKey((k) => k + 1);
  };
  return (
    <div className="wrap chatview" key={key}>
      <section className="thread">
        <div className="stepper">
          <Steps />
          <ResetCtl onReset={reset} />
        </div>
        <Feed />
        <Composer />
      </section>
      <Board />
    </div>
  );
}

function Header({ inChat }: { inChat: boolean }) {
  const st = useV2();
  return (
    <header className="top">
      <div className="wrap">
        <a className="logo" href="#home" aria-label="믿집 첫 화면">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 11 12 4l9 7v9H3z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            <path d="M9 20v-5h6v5" fill="none" stroke="var(--accent)" strokeWidth="2" />
          </svg>
          믿집
        </a>
        {inChat ? <span className="pill-ai" id="ai-pill">AI 상담</span> : null}
        <span className="spacer" />
        <div className="seg" role="group" aria-label="사진 종류">
          {(["free", "mfg", "ai"] as const).map((m) => (
            <button key={m} type="button" data-mode={m} aria-pressed={st.imgMode === m} onClick={() => setImgMode(m)}>
              {m === "free" ? "무료 사진" : m === "mfg" ? "제조사" : "AI"}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}

export function V2App() {
  const hash = useHash();
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    const saved = store.get("mj-imgmode");
    if (saved && MODE_LABEL[saved]) S.imgMode = saved as typeof S.imgMode;
    view.empty = store.get("mj-empty") === "1";
    fetch("/v2/data.json")
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json() as Promise<{ materials: Material[]; styles: Record<string, StyleData> }>;
      })
      .then((d) => {
        DATA.materials = d.materials;
        DATA.styles = d.styles;
        DATA.ready = true;
        touch();
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);
  const inChat = hash === "chat";
  useEffect(() => {
    if (!inChat) window.scrollTo(0, 0);
  }, [inChat]);
  return (
    <div className={s.root}>
      <Header inChat={inChat} />
      <main id="main">
        {state === "loading" ? (
          <div className="wrap loading">불러오는 중이에요…</div>
        ) : state === "error" ? (
          <div className="wrap loading">자료를 불러오지 못했어요. 새로고침해 주세요.</div>
        ) : inChat ? (
          <ChatView />
        ) : (
          <Home />
        )}
      </main>
      <Overlays />
      <Toast />
    </div>
  );
}

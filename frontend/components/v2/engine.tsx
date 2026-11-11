"use client";
// v2 대화 엔진: v10의 addMsg · bot · me · quick · toast · 시트(겹창)를 같은 이름으로 옮겼다.
// 메시지 · 빠른 답 · 알림 · 겹창은 이 파일의 저장소에 쌓이고 <Feed /> · <Quick /> · <Overlays /> · <Toast />가 그린다.
// 단계 함수는 F 표에 이름으로 넣고 부른다(파일끼리 서로 import하지 않게): F.infoStep(), F.matStep() …
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { wait } from "./store";

type Part = ReactNode;
type Msg = { id: number; who: "bot" | "me"; parts: Part[]; typing?: boolean; scroll?: "start" | "nearest" };
type QuickItem = [string, () => void];
type Overlay = { id: number; node: ReactNode };

const feed = {
  msgs: [] as Msg[],
  quick: [] as QuickItem[],
  overlays: [] as Overlay[],
  toast: null as { text: string; undo?: () => void; id: number } | null,
};
let seq = 0;
let ver = 0;
const subs = new Set<() => void>();
const emit = () => {
  ver++;
  subs.forEach((f) => f());
};
const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};
export function useFeed() {
  useSyncExternalStore(subscribe, () => ver, () => 0);
  return feed;
}

/** 흐름 함수 표. 각 단계 파일이 register로 넣는다 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const F: Record<string, (...a: any[]) => any> = {};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function register(fns: Record<string, (...a: any[]) => any>) {
  Object.assign(F, fns);
}
/** AI 답을 만드는 중이면 그 요청 (v10 asking) */
export const busy = { asking: null as AbortController | null };

export type MsgHandle = {
  id: number;
  set: (...parts: Part[]) => void;
  append: (part: Part) => void;
  remove: () => void;
};
function handle(id: number): MsgHandle {
  return {
    id,
    set: (...parts) => {
      const m = feed.msgs.find((x) => x.id === id);
      if (m) {
        m.parts = parts;
        emit();
      }
    },
    append: (part) => {
      const m = feed.msgs.find((x) => x.id === id);
      if (m) {
        m.parts = [...m.parts, part];
        emit();
      }
    },
    remove: () => {
      feed.msgs = feed.msgs.filter((x) => x.id !== id);
      emit();
    },
  };
}

export function addMsg(who: "bot" | "me", ...parts: Part[]): MsgHandle {
  const id = ++seq;
  feed.msgs = [...feed.msgs, { id, who, parts }];
  emit();
  return handle(id);
}

/** 봇 말: 잠깐 '입력 중'을 보인 뒤 글과 카드를 붙이고 그 메시지로 내린다 */
export async function bot(text: string | null, ...widgets: Part[]): Promise<MsgHandle> {
  const id = ++seq;
  feed.msgs = [...feed.msgs, { id, who: "bot", parts: [], typing: true }];
  emit();
  await wait(320);
  const m = feed.msgs.find((x) => x.id === id);
  if (m) {
    m.typing = false;
    m.parts = [text ? <div className="bubble" key="t">{text}</div> : null, ...widgets];
    m.scroll = "start";
    feed.msgs = [...feed.msgs];
    emit();
  }
  return handle(id);
}
export function me(text: string) {
  addMsg("me", <div className="bubble">{text}</div>);
}

/** 빠른 답 칩. 누르면 칩을 지우고 고객 말로 남긴 뒤 fn을 부른다 */
export function quick(items: QuickItem[]) {
  feed.quick = items;
  emit();
}
export function clearQuick() {
  if (!feed.quick.length) return;
  feed.quick = [];
  emit();
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(text: string, undo?: () => void) {
  clearTimeout(toastTimer);
  feed.toast = { text, undo, id: ++seq };
  emit();
  toastTimer = setTimeout(() => {
    feed.toast = null;
    emit();
  }, 5000);
}

/** 겹창(시트 · 문서 · 사진 보기)을 연다. node는 close를 받아 그린다 */
export function openOverlay(render: (close: () => void) => ReactNode): { close: () => void } {
  const id = ++seq;
  const last = typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null;
  const close = () => {
    feed.overlays = feed.overlays.filter((o) => o.id !== id);
    emit();
    last?.focus?.();
  };
  feed.overlays = [...feed.overlays, { id, node: render(close) }];
  emit();
  return { close };
}
export const closeAllOverlays = () => {
  feed.overlays = [];
  emit();
};

/** 대화를 처음으로 */
export function resetFeed() {
  busy.asking?.abort();
  busy.asking = null;
  feed.msgs = [];
  feed.quick = [];
  feed.overlays = [];
  feed.toast = null;
  emit();
}

/** 다시 그려야 하는 카드가 상태를 직접 보지 않을 때 (드묾) */
export const refreshFeed = emit;

/** 값이 바뀌면 다시 그리는 작은 저장소. AI 답 글처럼 한 메시지 안에서만 바뀌는 것에 쓴다 */
export function live<T>(init: T) {
  let v = init;
  let n = 0;
  const ls = new Set<() => void>();
  return {
    get: () => v,
    set: (x: T) => {
      v = x;
      n++;
      ls.forEach((f) => f());
    },
    use: () => {
      useSyncExternalStore(
        (f) => {
          ls.add(f);
          return () => ls.delete(f);
        },
        () => n,
        () => 0,
      );
      return v;
    },
  };
}

/* ---------- 그리는 쪽 ---------- */

function MsgView({ m }: { m: Msg }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (m.scroll && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: m.scroll });
      m.scroll = undefined;
    }
  });
  const body = m.typing ? (
    <div className="typing" aria-label="입력 중"><i /><i /><i /></div>
  ) : (
    m.parts.map((p, i) => <PartBox key={i}>{p}</PartBox>)
  );
  if (m.who === "me") return <div className="msg me" ref={ref}><div className="body">{body}</div></div>;
  return (
    <div className="msg" ref={ref}>
      <div className="av" aria-hidden="true">AI</div>
      <div className="body">{body}</div>
    </div>
  );
}
const PartBox = ({ children }: { children: ReactNode }) => <>{children}</>;

export function Feed() {
  const f = useFeed();
  return (
    <div className="msgs" role="log" aria-live="polite" aria-label="상담 대화">
      {f.msgs.map((m) => <MsgView key={m.id} m={m} />)}
    </div>
  );
}

export function Quick() {
  const f = useFeed();
  return (
    <div className="quick">
      {f.quick.map(([label, fn]) => (
        <button
          key={label}
          type="button"
          className="chip"
          onClick={() => {
            clearQuick();
            me(label);
            fn();
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function Overlays() {
  const f = useFeed();
  return <>{f.overlays.map((o) => <div key={o.id}>{o.node}</div>)}</>;
}

export function Toast() {
  const f = useFeed();
  const t = f.toast;
  if (!t) return null;
  return (
    <div className="toast" role="status" key={t.id}>
      {t.text}
      {t.undo ? (
        <button
          type="button"
          onClick={() => {
            t.undo?.();
            feed.toast = null;
            emit();
          }}
        >
          되돌리기
        </button>
      ) : null}
    </div>
  );
}

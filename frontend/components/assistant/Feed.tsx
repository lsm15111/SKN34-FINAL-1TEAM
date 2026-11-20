"use client";
// 대화 목록(role=log): 날짜가 바뀌면 날짜 줄, 새 말이 오면 그 말 머리로 부드럽게 내려가요.
// 위를 보고 있으면(사용자가 올려 본 뒤) 끌어내리지 않고 '새 소식 ↓' 단추만 띄워요.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { FeedItem } from "@/lib/api/assistant";
import { dateSeoul, dateSpoken } from "@/lib/format";
import type { CardCtx } from "./cards/types";
import { I } from "./kit/icons";
import { Message, type ActionHandlers } from "./Message";
import s from "./assistant.module.css";

export function Feed({ items, loaded, loadError, ctx, act, liveId, waitingReply, scroller, headroom, onRetry }: {
  items: FeedItem[];
  loaded: boolean;
  loadError: string | null;
  ctx: CardCtx;
  act: ActionHandlers;
  /** 지금 도는 턴의 비서 말 id(입력 중 점) */
  liveId: string | null;
  /** 보냈는데 아직 답 말이 안 생겼어요(ack 전) */
  waitingReply: boolean;
  scroller: RefObject<HTMLDivElement | null>;
  /** 단계 띠 높이(말 머리를 그 아래에 맞춰요) */
  headroom: () => number;
  onRetry: () => void;
}) {
  const [news, setNews] = useState(false);
  const up = useRef(false);
  const lastTop = useRef(0);
  const first = useRef(true);
  const sig = signature(items);

  // 사용자가 위로 올려 보면 끌어내리지 않아요. 맨 아래에 닿으면 다시 따라가요
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      if (el.scrollTop < lastTop.current - 4) up.current = true;
      if (near) { up.current = false; setNews(false); }
      lastTop.current = el.scrollTop;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [scroller]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !items.length) return;
    if (first.current) {
      first.current = false;
      el.scrollTop = el.scrollHeight;
      lastTop.current = el.scrollTop;
      return;
    }
    const last = items[items.length - 1];
    if (last.role === "user") up.current = false;
    if (up.current) { setNews(true); return; }
    const node = el.querySelector<HTMLElement>(`[data-id="${CSS.escape(last.id)}"]`);
    const top = last.role === "user" || !node ? el.scrollHeight : node.offsetTop - headroom() - 12;
    el.scrollTo({ top, behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  if (!loaded) return <div className={s.skel} aria-busy="true" aria-label="대화를 불러오고 있어요"><i /><i /></div>;
  if (loadError) return <p className={s.fail} role="alert"><I n="alert" />{loadError}<button type="button" className={s.textBtn} onClick={onRetry}>다시 해 보기</button></p>;

  let day = "";
  return (
    <>
      <div className={s.msgs} role="log" aria-label="비서 대화" aria-live="polite" aria-relevant="additions">
        {items.map((it) => {
          const d = it.at ? dateSeoul(it.at) : day;
          const line = d && d !== day ? <div className={s.day} key={`d-${d}`}>{dateSpoken(d)}</div> : null;
          day = d || day;
          return [line, <Message key={it.id} item={it} ctx={ctx} act={act} live={it.id === liveId} onRetry={onRetry} />];
        })}
        {waitingReply ? (
          <div className={s.msg}>
            <div className={s.av} aria-hidden="true">AI</div>
            <div className={s.msgBody}><span className={s.status} role="status"><span className={s.typing} aria-hidden="true"><i /><i /><i /></span>답을 만들고 있어요</span></div>
          </div>
        ) : null}
      </div>
      {news ? (
        <button type="button" className={s.newBtn} onClick={() => { const el = scroller.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }); up.current = false; setNews(false); }}>
          새 소식<I n="arrowDown" />
        </button>
      ) : null}
    </>
  );
}

/** 대화가 바뀐 정도(말 수 · 마지막 말의 조각 수 · 상태)만 봐요 */
function signature(items: FeedItem[]) {
  const last = items[items.length - 1];
  if (!last) return "0";
  return `${items.length}:${last.id}:${last.role === "assistant" ? `${last.parts.length}:${last.done ? 1 : 0}:${last.status ?? ""}` : ""}`;
}

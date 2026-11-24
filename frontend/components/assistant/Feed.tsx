"use client";
// 대화 목록(role=log): 날짜가 바뀌면 날짜 줄, 새 말이 오면 그 말 머리로 부드럽게 내려가요.
// 위를 보고 있으면(사용자가 올려 본 뒤) 끌어내리지 않고 '새 소식 ↓' 단추만 띄워요.
// 맨 위 '앞 대화 더 보기'는 서버 feed의 앞 쪽(턴 번호 커서)을 읽어 붙여요(보던 자리는 그대로). 대화가 처음이면 인사 한 줄(첫 말 뒤에도 그대로).
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { FeedItem } from "@/lib/api/assistant";
import { dateSeoul, dateSpoken } from "@/lib/format";
import type { CardCtx } from "./cards/types";
import { SourceTag } from "./kit/StatusTag";
import { I } from "./kit/icons";
import { Message, type ActionHandlers } from "./Message";
import s from "./assistant.module.css";

export function Feed({ items, loaded, loadError, ctx, act, liveId, waitingReply, scroller, headroom, onRetry, fresh, hasOlder, olderBusy, onOlder }: {
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
  /** 처음 열 때 이 공사의 비서 대화가 없었어요(첫 인사를 보여요. 화면이 만든 말 · 오늘 정할 일이 있어도, 첫 말을 보낸 뒤에도) */
  fresh: boolean;
  hasOlder: boolean;
  olderBusy: boolean;
  onOlder: () => void;
}) {
  const [news, setNews] = useState(false);
  const up = useRef(false);
  const lastTop = useRef(0);
  const first = useRef(true);
  const keep = useRef<{ h: number; top: number } | null>(null);
  const prepended = useRef(false);
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

  // 앞 쪽을 붙이면 보던 말이 그 자리에 있게 늘어난 높이만큼 내려요
  const head = items[0]?.id;
  useLayoutEffect(() => {
    const el = scroller.current;
    const k = keep.current;
    if (!el || !k) return;
    keep.current = null;
    prepended.current = true;
    el.scrollTop = k.top + (el.scrollHeight - k.h);
    lastTop.current = el.scrollTop;
  }, [head, scroller]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !items.length) return;
    if (prepended.current) { prepended.current = false; return; }
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
      {hasOlder ? (
        <div className={s.older}>
          <button type="button" className={s.textBtn} disabled={olderBusy} aria-busy={olderBusy || undefined}
            onClick={() => { const el = scroller.current; if (el) keep.current = { h: el.scrollHeight, top: el.scrollTop }; onOlder(); }}>
            {olderBusy ? "불러오고 있어요" : "앞 대화 더 보기"}
          </button>
        </div>
      ) : null}
      <div className={s.msgs} role="log" aria-label="비서 대화" aria-live="polite" aria-relevant="additions">
        {fresh ? (
          <div className={s.msg}>
            <div className={s.av} aria-hidden="true">AI</div>
            <div className={s.msgBody}>
              <span className={s.aiTag}><SourceTag src="guide" /></span>
              <p className={`${s.bubble} ${s.say}`}>공사를 끝까지 챙기는 믿집 비서예요. 업체 추천부터 실측 일정까지 챙겨 드려요.{"\n"}도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물어보세요.</p>
            </div>
          </div>
        ) : null}
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

/** 대화가 바뀐 정도(말 수 · 마지막 말의 조각 수 · 상태)만 봐요. 다음에 물을 말은 세지 않아요
 *  (먼저 말 건 줄이 '완료'가 되며 제안만 빠질 때 보던 자리에서 그 말 머리로 끌어올리지 않게).
 *  화면이 만든 말(local: 오늘 정할 일 · 기록 밖 승인 카드)은 맨 끝에 있을 때만 세요(가운데에서 바뀌어도 끌어내리지 않고,
 *  흐르는 답은 기록의 마지막 말로 따라가요) */
function signature(items: FeedItem[]) {
  let end = items.length;
  const tailLocal: string[] = [];
  while (end > 0 && isLocal(items[end - 1])) tailLocal.unshift(items[--end].id);
  const real = items.slice(0, end).filter((x) => !isLocal(x));
  const last = real[real.length - 1];
  if (!last) return `0|${tailLocal.join(",")}`;
  const parts = last.role === "assistant" ? last.parts.filter((p) => p.t !== "suggest").length : 0;
  return `${real.length}:${last.id}:${last.role === "assistant" ? `${parts}:${last.done ? 1 : 0}:${last.status ?? ""}` : ""}|${tailLocal.join(",")}`;
}
const isLocal = (x: FeedItem) => x.role === "assistant" && !!x.local;

"use client";
// 말 하나: 비서는 28px 'AI' 원 + 말풍선 없는 글 · 카드, 고객은 회색 말풍선(18 18 4 18).
// 비서 말 안 순서는 서버가 보낸 순서 그대로예요: 정해 둔 글 · 계산 카드가 먼저, AI 글은 뒤에 붙어요('AI 답변' 이름표).
// 무료 모드(LLM 없이)에서 카드만 남았으면 '설명을 만들지 못했어요', 한도에 닿아 멈췄으면(stopped) 그렇게 알려요.
import type { ActionOut, FeedItem, FeedPart, SuggestOut } from "@/lib/api/assistant";
import { ApprovalCard } from "./kit/ApprovalCard";
import { SourceTag } from "./kit/StatusTag";
import { SuggestCard } from "./kit/SuggestCard";
import { TaskCard } from "./kit/TaskCard";
import { I } from "./kit/icons";
import { Card } from "./cards/registry";
import type { CardCtx } from "./cards/types";
import k from "./kit/kit.module.css";
import s from "./assistant.module.css";

export type ActionHandlers = {
  approve: (a: ActionOut) => void;
  reject: (a: ActionOut) => void;
  remake: (a: ActionOut) => void;
  pending: Record<string, boolean>;
  errors: Record<string, string>;
  /** 전체 화면 카드 안 v3 단추로 이미 처리한 행동 */
  handled: Record<string, true>;
  /** 먼저 말 건 제안: 열기([해 볼게요]) · 닫기([괜찮아요]) · 숨길 것(API 없음 · 닫음) */
  openNudge: (nudgeId: string) => void;
  dismissNudge: (nudgeId: string) => void;
  gone: Record<string, true>;
};

export function Message({ item, ctx, act, live, onRetry }: { item: FeedItem; ctx: CardCtx; act: ActionHandlers; live: boolean; onRetry: () => void }) {
  if (item.role === "user") {
    return (
      <div className={`${s.msg} ${s.me}`} data-id={item.id}>
        <div className={s.msgBody}><p className={s.bubble}>{item.text}</p></div>
      </div>
    );
  }
  const waiting = live && !item.done;
  const hasAi = item.parts.some((p) => p.t === "text" && p.src === "ai");
  const hasAnswer = item.parts.some((p) => p.t === "card" && p.card.kind === "answer");
  const hasCard = item.parts.some((p) => p.t === "card");
  // 숨기는 조각: 닫은 먼저 말 걸기 · 집 정보 저장 행동(집 카드의 [맞아요]가 맡아요)
  const parts = item.parts.filter((p) => !(p.t === "suggest" && p.suggest.nudge_id && act.gone[p.suggest.nudge_id]) && !(p.t === "action" && p.action.kind === "home_info"));
  if (!parts.length && !waiting && !item.error) return null;
  // 다음에 물을 말(턴 끝 done.suggest 0~3개 · 먼저 말 건 줄 하나)은 말 끝에 모아 그려요
  const ideas = parts.flatMap((p) => (p.t === "suggest" ? [p.suggest] : []));
  return (
    <div className={`${s.msg} ${s.enter}`} data-id={item.id}>
      <div className={s.av} aria-hidden="true">AI</div>
      <div className={s.msgBody}>
        {parts.map((p, i) => (p.t === "suggest" ? null : <Part key={partKey(p, i)} part={p} ctx={ctx} act={act} />))}
        <Suggests list={ideas} ctx={ctx} act={act} />
        {waiting ? (
          <span className={s.status} role="status">
            <span className={s.typing} aria-hidden="true"><i /><i /><i /></span>
            {item.status ?? (item.parts.length ? "" : "답을 만들고 있어요")}
          </span>
        ) : null}
        {item.done && item.stopped ? <p className={s.note}>설명을 끝까지 만들지 못해 카드만 보여 드려요</p> : null}
        {item.done && !item.stopped && item.mode === "free" && hasCard && !hasAi && !hasAnswer ? <p className={s.note}>설명을 만들지 못했어요</p> : null}
        {item.error ? (
          <p className={s.fail} role="alert"><I n="alert" />{item.error.message}<button type="button" className={s.textBtn} onClick={onRetry}>다시 불러오기</button></p>
        ) : null}
      </div>
    </div>
  );
}

const partKey = (p: FeedPart, i: number) =>
  p.t === "card" ? `c-${p.card.card_id}` : p.t === "task" ? `t-${p.task.task_id}` : p.t === "action" ? `a-${p.action.action_id}` : p.t === "suggest" ? `s-${p.suggest.id}` : `x-${i}`;

function Part({ part: p, ctx, act }: { part: FeedPart; ctx: CardCtx; act: ActionHandlers }) {
  switch (p.t) {
    case "text":
      return p.src === "ai"
        ? <div className={s.ai}><span className={s.aiTag}><SourceTag src="ai" /></span><p className={s.bubble}>{p.text}</p></div>
        : <p className={`${s.bubble} ${s.say}`}>{p.text}</p>;
    case "card":
      return (
        <>
          {p.card.say ? <p className={`${s.bubble} ${s.say}`}>{p.card.say}</p> : null}
          <Card card={p.card} ctx={ctx} old={false} />
        </>
      );
    case "task":
      return <TaskCard task={p.task} now={ctx.now} />;
    case "action":
      return (
        <ApprovalCard
          action={p.action}
          now={ctx.now}
          busy={!!act.pending[p.action.action_id]}
          handled={!!act.handled[p.action.action_id]}
          error={act.errors[p.action.action_id] ?? null}
          onApprove={() => act.approve(p.action)}
          onReject={() => act.reject(p.action)}
          onRemake={() => act.remake(p.action)}
        />
      );
    case "suggest":
      return null;
    case "note":
      return <p className={s.note}>{p.text}</p>;
  }
}

/** 첫 제안은 제안 카드([해 볼게요] · [괜찮아요]), 둘째부터는 칩으로 짧게. 먼저 말 걸기에서 왔으면 누를 때 열었다고 알려요 */
function Suggests({ list, ctx, act }: { list: SuggestOut[]; ctx: CardCtx; act: ActionHandlers }) {
  if (!list.length) return null;
  const [first, ...more] = list;
  const go = (x: SuggestOut) => { if (x.nudge_id) act.openNudge(x.nudge_id); ctx.send(x.say); };
  const nid = first.nudge_id ?? null;
  return (
    <>
      <SuggestCard
        key={first.id}
        suggest={first}
        disabled={ctx.busy}
        onAccept={() => go(first)}
        onDismiss={nid ? () => act.dismissNudge(nid) : undefined}
      />
      {more.length ? (
        <div className={s.ideas} role="group" aria-label="이어서 물을 말">
          {more.map((x) => <button key={x.id} type="button" className={`${k.chip} ${k.chipSm}`} disabled={ctx.busy} onClick={() => go(x)}><I n="sparkle" />{x.text}</button>)}
        </div>
      ) : null}
    </>
  );
}

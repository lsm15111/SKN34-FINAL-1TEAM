"use client";
// 말 하나: 비서는 28px 'AI' 원 + 말풍선 없는 글 · 카드, 고객은 회색 말풍선(18 18 4 18).
// 비서 말 안 순서는 서버가 보낸 순서 그대로예요: 정해 둔 글 · 계산 카드가 먼저, AI 글은 뒤에 붙어요('AI 답변' 이름표).
import type { ActionOut, FeedItem, FeedPart } from "@/lib/api/assistant";
import { ApprovalCard } from "./kit/ApprovalCard";
import { SourceTag } from "./kit/StatusTag";
import { SuggestCard } from "./kit/SuggestCard";
import { TaskCard } from "./kit/TaskCard";
import { I } from "./kit/icons";
import { Card } from "./cards/registry";
import type { CardCtx } from "./cards/types";
import s from "./assistant.module.css";

export type ActionHandlers = {
  approve: (a: ActionOut) => void;
  reject: (a: ActionOut) => void;
  remake: (a: ActionOut) => void;
  pending: Record<string, boolean>;
  errors: Record<string, string>;
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
  const hasCard = item.parts.some((p) => p.t === "card");
  if (!item.parts.length && !waiting && !item.error) return null;
  return (
    <div className={`${s.msg} ${s.enter}`} data-id={item.id}>
      <div className={s.av} aria-hidden="true">AI</div>
      <div className={s.msgBody}>
        {item.parts.map((p, i) => <Part key={partKey(p, i)} part={p} ctx={ctx} act={act} />)}
        {waiting ? (
          <span className={s.status} role="status">
            <span className={s.typing} aria-hidden="true"><i /><i /><i /></span>
            {item.status ?? (item.parts.length ? "" : "답을 만들고 있어요")}
          </span>
        ) : null}
        {item.done && item.mode === "free" && hasCard && !hasAi ? <p className={s.note}>설명을 만들지 못했어요</p> : null}
        {item.error ? (
          <p className={s.fail} role="alert"><I n="alert" />{item.error.message}<button type="button" className={s.textBtn} onClick={onRetry}>다시 해 보기</button></p>
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
      // 집 정보 저장은 집 카드의 [맞아요]가 맡아요(따로 승인 카드를 띄우지 않아요)
      if (p.action.kind === "home_info") return null;
      return (
        <ApprovalCard
          action={p.action}
          now={ctx.now}
          busy={!!act.pending[p.action.action_id]}
          error={act.errors[p.action.action_id] ?? null}
          onApprove={() => act.approve(p.action)}
          onReject={() => act.reject(p.action)}
          onRemake={() => act.remake(p.action)}
        />
      );
    case "suggest":
      return <SuggestCard suggest={p.suggest} disabled={ctx.busy} onAccept={(say) => ctx.send(say)} />;
    case "note":
      return <p className={s.note}>{p.text}</p>;
  }
}

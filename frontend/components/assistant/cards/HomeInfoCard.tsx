"use client";
// C1 집 정보 확인(계약서 3장: confirm 모양만): 집 요약 줄 · 면적(계산 엔진) · 비서가 제안한 바뀜 · 철거 범위 질문.
// [맞아요, 저장]은 비서가 만든 '집 정보 저장' 제안의 승인이에요(되돌릴 수 있어요). 실측을 요청한 뒤에는 잠겨요(C50).
// 주소 찾기는 범위 밖이라 첫 대화(/start)에서 글로만 받아요. 동 · 호는 받지 않아요.
// 철거 범위(demolition: full · partial · none)는 백엔드 담당이 같은 키로 더해요. 고르면 그 말로 턴을 보내요(비서가 저장 제안을 만들어요).
import Link from "next/link";
import { DEMOLITION, type Demolition } from "@/lib/api/assistant";
import { decText } from "@/lib/format";
import { SourceTag, StatusTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

const BASIS = { supply: "공급", exclusive: "전용" } as const;
const SAY: Record<Demolition, string> = { full: "철거는 전체 철거로 할게요", partial: "철거는 일부만 할게요", none: "철거는 안 할게요" };
const CLOSED = new Set(["rejected", "expired", "failed"]);

export function HomeInfoCard({ card, ctx }: CardProps<"home_info">) {
  const d = card.data;
  const act = d.action_id ? ctx.actionOf(d.action_id) : null;
  const handled = !!d.action_id && ctx.handledOf(d.action_id) && act?.status !== "executed";
  const saved = d.saved || act?.status === "executed";
  const closed = !!act && CLOSED.has(act.status);
  const pending = d.action_id ? ctx.pendingOf(d.action_id) : false;
  const asking = !!d.action_id && !saved && !closed && !handled;
  const editHref = `/start?edit=${encodeURIComponent(ctx.projectId)}`;
  // 면적은 아래 큰 상자로 보여요(요약 줄의 ㎡ · 평은 겹치지 않게 빼요)
  const facts = d.area ? d.facts.filter((f) => !/㎡|^\d+(\.\d+)?평$/.test(f)) : d.facts;
  const demo = d.demolition ?? null;
  const demoLabel = DEMOLITION.find((x) => x.key === demo)?.label;
  // 철거 범위를 아직 안 물었으면(저장한 집이어도) 묻기 칩을 보여요. 다 정한 집 카드는 끝난 모양(흐림)으로 남아요
  const ask = !d.locked && (!demo || asking);
  const finished = (saved || handled) && !ask;

  return (
    <section className={finished ? `${k.card} ${k.done}` : k.card} aria-label="집 확인">
      <div className={k.top}>
        <h3>우리 집</h3>
        {d.locked ? <StatusTag tone="cancelled">실측 요청 뒤라 고칠 수 없어요</StatusTag> : null}
      </div>
      {facts.length ? <ul className={k.facts}>{facts.map((f) => <li key={f}>{f}</li>)}</ul> : null}
      {d.area ? (
        <div className={c.area}>
          <div className={c.areaL}>
            <span>이 집 면적</span>
            <b className={k.num}>{BASIS[d.area.basis]} {decText(d.area.m2)}㎡</b>
            {d.area.pyeong ? <span className={`${c.sub} ${k.num}`}>{decText(d.area.pyeong)}평</span> : null}
          </div>
          <SourceTag src="calc" />
        </div>
      ) : null}
      {asking && d.changes.length ? (
        <dl className={k.rows} aria-label="바꿀 칸">
          {d.changes.map((x) => <div key={x.label}><dt>{x.label}</dt><dd>{x.after}<small>지금 {x.before ?? "없음"}</small></dd></div>)}
        </dl>
      ) : null}
      {!ask ? (
        demoLabel ? <p className={k.decided}><I n="check" />철거 범위 · {demoLabel}</p> : null
      ) : (
        <div className={c.field} role="group" aria-labelledby={`${card.card_id}-demo`}>
          <span className={c.lbl} id={`${card.card_id}-demo`}>철거 범위</span>
          <div className={k.chips}>
            {DEMOLITION.map((x) => (
              <button key={x.key} type="button" className={k.chip} aria-pressed={demo === x.key} disabled={ctx.busy}
                onClick={() => { if (demo !== x.key) ctx.send(SAY[x.key], { card_id: card.card_id, choice: `demolition:${x.key}` }); }}>
                {x.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {handled ? (
        <p className={k.decided}><StatusTag tone="ok">처리됨</StatusTag>기본 정보 화면에서 저장했어요</p>
      ) : saved ? (
        <p className={k.decided}><I n="check" />집 정보를 저장했어요</p>
      ) : asking ? (
        <div className={k.row}>
          <button type="button" className={`${k.btn} ${k.pri}`} disabled={pending || ctx.busy} aria-busy={pending || undefined} onClick={() => d.action_id && ctx.approve(d.action_id)}>
            {act?.summary.approve_label ?? "맞아요, 저장"}
          </button>
          <Link className={`${k.text} ${k.gray}`} href={editHref}>직접 고칠게요</Link>
        </div>
      ) : d.locked ? null : (
        <div className={k.row}>
          {closed ? <span className={k.muted}>저장하지 않았어요</span> : null}
          <Link className={`${k.btn} ${k.sm}`} href={editHref}>기본 정보 고치기</Link>
        </div>
      )}
    </section>
  );
}

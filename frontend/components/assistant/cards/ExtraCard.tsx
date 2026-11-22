"use client";
// 07 추가 금액 카드: 업체가 적은 한 일 · 이유 · 공급가 · 부가세 · 합계(부가세 포함) · 승인하면 공사 금액.
// 금액은 서버(계산 엔진) 값 그대로예요. 한 일 · 이유는 업체 글이라 '업체가 적은' 인용 칸에만 보여요(믿집 계산 줄과 섞지 않아요).
// [승인할래요] · [거절할래요] · [업체에 물어볼래요]는 choice extra_answer:x…로 그 답의 승인 카드를 받아요(무료 모드도).
// 업체에 답이 가는 건 그 승인 카드를 눌렀을 때뿐이에요. 비서는 승인 카드를 미리 만들지 않아요(고객이 단추로 골라요).
// 이미 채팅으로 물어봤으면(asked) [물어볼래요]는 빼요. [○○ 채팅 열기]는 사진 · 까닭을 물어볼 믿집 채팅이에요.
// 카드는 보낸 때 모습이라, 이 추가 금액에 답한 승인 카드가 대화에서 실행됐으면 단추를 빼요(할 일이 끝난 줄의 카드 old도).
import Link from "next/link";
import { CHOICE, type ActionOut, type ExtraData } from "@/lib/api/assistant";
import { won } from "@/lib/format";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import c from "./cards.module.css";
import s from "./ExtraCard.module.css";
import type { CardProps } from "./types";

const ANSWER: Record<string, string> = {
  pending: "답을 기다려요",
  asked: "채팅으로 물어봤어요",
  approved: "승인했어요",
  rejected: "거절했어요",
};

/** 이 추가 금액에 답한 승인 카드인지: 대상 id(target_id)가 이 추가 금액이면 그것, 대상 id가 없는 옛 행동은 만든 때 상태
 *  (target_ver '답:판') · 합계 · 업체가 같은 것으로 봐요 */
const answers = (d: ExtraData) => (a: ActionOut) =>
  a.target_id
    ? a.target_id === d.extra_id
    : a.target_ver === `${d.answer}:${d.version}` && a.summary.amount_won === d.total_won && (a.summary.rows ?? []).some((r) => r.value === d.vendor_name);

export function ExtraCard({ card, ctx, old }: CardProps<"extra">) {
  const d = card.data;
  const answer = ctx.lastAction("extra_answer", answers(d));
  const answered = !!answer && (answer.status === "executed" || ctx.handledOf(answer.action_id));
  const open = !old && !answered && (d.answer === "pending" || d.answer === "asked");
  const press = (to: "approve" | "reject" | "ask", text: string) =>
    ctx.send(text, { card_id: card.card_id, choice: CHOICE.extraAnswer(d.ref, to) });
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>추가 금액</h3>
        <SourceTag src="calc" />
      </div>
      <p className={s.who}>
        {d.vendor_name} · {d.trade}
        <span>{answered ? "답했어요" : ANSWER[d.answer] ?? ""}{d.version > 1 ? ` · ${d.version}판` : ""}</span>
      </p>
      <blockquote className={c.vnote}>
        <b>업체가 적은 한 일</b>
        {d.title}
      </blockquote>
      {d.vendor_note ? (
        <blockquote className={c.vnote}>
          <b>업체가 적은 말</b>
          {d.vendor_note}
        </blockquote>
      ) : null}
      <dl className={s.rows}>
        <div>
          <dt>공급가</dt>
          <dd className={k.num}>{won(d.supply_won)}</dd>
        </div>
        <div>
          <dt>부가세</dt>
          <dd className={k.num}>{won(d.vat_won)}</dd>
        </div>
        <div className={s.total}>
          <dt>합계<small>업체가 적은 방식 · {d.vat_label}</small></dt>
          <dd className={k.num}><b>{won(d.total_won)}</b></dd>
        </div>
      </dl>
      {d.after_total_won != null ? (
        <p className={s.after}>
          <span>승인하면 공사 금액</span>
          <b className={k.num}>{won(d.after_total_won)}</b>
          {d.grand_total_won != null ? <small className={k.num}>지금 {won(d.grand_total_won)}</small> : null}
        </p>
      ) : null}
      {open ? (
        <div className={s.btns} role="group" aria-label="추가 금액에 답하기">
          <button type="button" className={`${k.btn} ${k.pri} ${k.sm}`} disabled={ctx.busy} onClick={() => press("approve", "추가 금액 승인할래요")}>
            승인할래요
          </button>
          <button type="button" className={`${k.btn} ${k.sm}`} disabled={ctx.busy} onClick={() => press("reject", "추가 금액 거절할래요")}>
            거절할래요
          </button>
          {d.answer === "pending" ? (
            <button type="button" className={`${k.btn} ${k.sm}`} disabled={ctx.busy} onClick={() => press("ask", "추가 금액을 업체에 물어볼래요")}>
              업체에 물어볼래요
            </button>
          ) : null}
        </div>
      ) : null}
      <div className={k.row}>
        <Link className={k.text} href={d.href} scroll={false}>
          공사 화면에서 보기<I n="chev" />
        </Link>
        {d.chat_href && !old ? (
          <Link className={k.text} href={d.chat_href} scroll={false}>
            {d.vendor_name} 채팅 열기<I n="chev" />
          </Link>
        ) : null}
        {d.photo_count ? <span className={k.muted}>사진 {d.photo_count}장</span> : null}
      </div>
    </section>
  );
}

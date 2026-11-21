"use client";
// 07 추가 금액 카드: 한 일 · 공급가 · 부가세 · 합계(부가세 포함) · 승인하면 공사 금액 · 업체가 적은 말.
// 금액은 서버(계산 엔진) 값 그대로예요. 한 일 · 업체가 적은 말은 업체 글이라 그 칸에만 보여요.
// [승인할래요] · [거절할래요] · [채팅으로 물어볼래요]는 choice extra_answer:x…로 승인 카드를 받아요(무료 모드도).
// 업체에 답이 가는 건 그 승인 카드를 눌렀을 때뿐이에요.
import Link from "next/link";
import { CHOICE } from "@/lib/api/assistant";
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

export function ExtraCard({ card, ctx, old }: CardProps<"extra">) {
  const d = card.data;
  const open = !old && (d.answer === "pending" || d.answer === "asked");
  const press = (answer: "approve" | "reject" | "ask", text: string) =>
    ctx.send(text, { card_id: card.card_id, choice: CHOICE.extraAnswer(d.ref, answer) });
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>추가 금액</h3>
        <SourceTag src="calc" />
      </div>
      <p className={s.who}>
        {d.vendor_name} · {d.trade}
        <span>{ANSWER[d.answer] ?? ""}{d.version > 1 ? ` · ${d.version}판` : ""}</span>
      </p>
      <dl className={s.rows}>
        <div>
          <dt>한 일</dt>
          <dd>{d.title}</dd>
        </div>
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
      {d.vendor_note ? (
        <blockquote className={c.vnote}>
          <b>업체가 적은 말</b>
          {d.vendor_note}
        </blockquote>
      ) : null}
      {open ? (
        <div className={s.btns} role="group" aria-label="추가 금액에 답하기">
          <button type="button" className={`${k.btn} ${k.pri} ${k.sm}`} disabled={ctx.busy} onClick={() => press("approve", "추가 금액 승인할래요")}>
            승인할래요
          </button>
          <button type="button" className={`${k.btn} ${k.sm}`} disabled={ctx.busy} onClick={() => press("reject", "추가 금액 거절할래요")}>
            거절할래요
          </button>
          <button type="button" className={`${k.btn} ${k.sm}`} disabled={ctx.busy} onClick={() => press("ask", "추가 금액을 채팅으로 물어볼래요")}>
            채팅으로 물어볼래요
          </button>
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

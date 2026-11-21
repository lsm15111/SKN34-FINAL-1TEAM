// C2 표준견적서 요약: 큰 금액(부가세 포함) · 큰 줄 몇 개 · 공사 일수 · '믿집 계산' · [견적서 열기]. 풀이는 그 아래 'AI 답변'으로 붙어요.
// 첫 대화(/start, 로그인 전)도 같은 모양(StandardSummary)을 써요. 금액 · 일수는 계산 엔진 값 그대로예요.
import Link from "next/link";
import type { ReactNode } from "react";
import type { StandardQuoteData } from "@/lib/api/assistant";
import { daysCaption } from "@/lib/guest/standard";
import { won } from "@/lib/format";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function StandardSummary({ id, data: d, more }: { id: string; data: StandardQuoteData; more?: ReactNode }) {
  const days = daysCaption(d.days);
  return (
    <section className={k.card} aria-labelledby={`${id}-t`}>
      <div className={k.top}>
        <h3 id={`${id}-t`}>표준견적서</h3>
        <SourceTag src="calc" />
      </div>
      <div className={k.kpi}>
        <span>{d.label}</span>
        <b className={k.num}>{won(d.total_won)}</b>
        <small>{["부가세 포함", days, d.partial ? "실측 후 확정 줄이 있어요" : ""].filter(Boolean).join(" · ")}</small>
      </div>
      {d.lines.length ? (
        <ul className={c.lines} aria-label="큰 줄">
          {d.lines.map((l) => <li key={l.name}><span>{l.name}</span><b className={k.num}>{won(l.won)}</b></li>)}
        </ul>
      ) : null}
      <div className={k.row}>
        {/* 주소가 비면(로그인한 고객의 첫 대화: 공사를 만들기 전) 열기 단추를 빼요 */}
        {d.href ? <Link className={`${k.btn} ${k.sm}`} href={d.href} scroll={false}>견적서 열기</Link> : null}
        {more}
      </div>
    </section>
  );
}

export function StandardQuoteCard({ card, ctx }: CardProps<"standard_quote">) {
  return (
    <StandardSummary
      id={card.card_id}
      data={card.data}
      more={<button type="button" className={k.text} disabled={ctx.busy} onClick={() => ctx.send("표준견적서 금액 풀이해 줘")}><I n="sparkle" />금액 풀이 듣기</button>}
    />
  );
}

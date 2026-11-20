// C2 표준견적서 요약: 큰 금액(부가세 포함) · 큰 줄 2~3개 · '믿집 계산' · [견적서 열기]. 풀이는 그 아래 'AI 답변'으로 붙어요.
import Link from "next/link";
import { won } from "@/lib/format";
import { DecidedLine, SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function StandardQuoteCard({ card, ctx }: CardProps<"standard_quote">) {
  const d = card.data;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>표준견적서</h3>
        <SourceTag src="calc" />
      </div>
      <div className={k.kpi}>
        <span>{d.label}</span>
        <b className={k.num}>{won(d.total_won)}</b>
        <small>부가세 포함{d.partial ? " · 실측 후 확정 줄이 있어요" : ""}</small>
      </div>
      <ul className={c.lines} aria-label="큰 줄">
        {d.lines.map((l) => <li key={l.name}><span>{l.name}</span><b className={k.num}>{won(l.won)}</b></li>)}
      </ul>
      {d.decided?.map((t) => <DecidedLine key={t}>{t}</DecidedLine>)}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.href} scroll={false}>견적서 열기</Link>
        <button type="button" className={k.text} disabled={ctx.busy} onClick={() => ctx.send("표준견적서 금액 풀이 해 줘")}><I n="sparkle" />금액 풀이 듣기</button>
      </div>
    </section>
  );
}

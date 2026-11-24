"use client";
// 받은 견적서 점검 카드(check_outside_quote · outside_quote): 믿집 밖에서 받은 도배 견적서를 이 집 표준견적서와 줄마다 견준 값.
// - 숫자(받은 금액 · 표준 금액 · 차이 · 합계)와 판정(빠짐 · 많음 · 비슷 · 적음 · 표준에 없음)은 모두 서버(계산 엔진) 값이에요. 화면은 모양만 바꿔요.
// - 받은 금액은 부가세 포함으로 맞춘 값이고, 합계는 같은 범위(표준에 없는 줄은 뺌)로 견줬어요. 표준 대비 %는 없어요.
// - 올퍼티 판단 · 그 업체에 물을 것 · 다음 걸음 한 줄은 서버 틀 글이에요. 누르는 단추는 표준견적서 보기 링크뿐이에요(승인 카드 아님).
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { budgetText, diffText, PUTTY_TONE, ROW_CHIP, rowParts, sortRows, SOURCE_WORD, TOTAL_WORD } from "@/lib/assistant/outside";
import { oneLine, won as wonText } from "@/lib/format";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import s from "./OutsideQuoteCard.module.css";

/** 금액은 한 덩어리로(폰 360에서 '309만 / 1,076원'처럼 숫자 가운데서 줄이 바뀌지 않게, QA r10 U4) */
const won = oneLine(wonText);

export function OutsideQuoteCard({ card }: CardProps<"outside_quote">) {
  const d = card.data;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>받은 견적서 점검</h3>
        <SourceTag src="calc" />
      </div>
      <p className={k.muted}>{SOURCE_WORD[d.source]} · {d.basis}</p>
      <div className={s.total}>
        <div>
          <span>받은 견적서</span>
          <b className={k.num}>{won(d.outside_won)}</b>
        </div>
        <div>
          <span>표준견적서</span>
          <b className={k.num}>{won(d.standard_won)}</b>
        </div>
        <p className={s.gap}>
          <span>{TOTAL_WORD[d.state]}</span>
          <b className={k.num}>{diffText(d.diff_won, won)}</b>
        </p>
      </div>
      <ul className={s.rows} aria-label="줄마다 견주기">
        {sortRows(d.rows).map((r, i) => (
          <li key={`${r.key}-${r.name}-${i}`}>
            <div className={s.head}>
              <span className={s.name}>{r.name}</span>
              <Badge tone={ROW_CHIP[r.state].tone}>{ROW_CHIP[r.state].label}</Badge>
            </div>
            <p className={s.nums}>
              {rowParts(r, won).join(" · ")}
              {r.diff_won != null ? <> · <b className={k.num}>{diffText(r.diff_won, won)}</b></> : null}
            </p>
            {r.note ? <p className={s.note}>{r.note}</p> : null}
          </li>
        ))}
      </ul>
      <div className={s.putty}>
        <div className={s.head}>
          <b>올퍼티</b>
          <Badge tone={PUTTY_TONE[d.putty.need]}>{d.putty.label}</Badge>
        </div>
        <p>{d.putty.why}</p>
        <p className={s.note}>받은 견적서: {d.putty.found_label}</p>
      </div>
      {d.budget ? <p className={s.budget}>{budgetText(d.budget, won)}</p> : null}
      {d.asks.length ? (
        <div>
          <p className={s.asksHead}>그 업체에 물어볼 것</p>
          <ul className={s.asks}>{d.asks.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      ) : null}
      {d.notes.length ? <ul className={s.notes}>{d.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
      <p className={s.next}>{d.next}</p>
      <div className={k.row}>
        <Link className={k.text} href={d.href} scroll={false}>표준견적서 보기<I n="chev" /></Link>
      </div>
    </section>
  );
}

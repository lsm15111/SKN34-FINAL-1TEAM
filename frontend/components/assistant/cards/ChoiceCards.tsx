"use client";
// 고르기를 돕는 작은 카드 셋(새 판 도구): 숫자는 모두 서버(계산 엔진) 값 그대로예요. 화면은 모양만 바꾸고 계산하지 않아요.
// - 벽지 두 종류 견주기(compare_grades): 지금 집 조건으로 도배 표준견적서를 합지 · 실크로 함께 센 두 합계(부가세 포함) · 차액 ·
//   달라지는 줄(부가세 별도). 저장하지 않는 계산이라 표준견적서 · 고른 벽지는 그대로예요. [○○로 바꾸기]는 choice 'grade:<값>'으로
//   집 정보 승인 카드를 받아요(누르기 전에는 바뀌지 않아요). 실측을 요청한 뒤 · 옛 공사면 단추가 없어요. 표준 대비 %는 없어요.
// - 시세 범위(market_range): 이 집 조건으로 실견적에서 낸 가운데 절반 범위(부가세 포함 · 만 원 단위)와 출처 한 줄. 원자료는 없어요.
// - 고르기 칩(options): 거둘 카드 · 취소할 요청이 여럿일 때 하나를 골라요. 누르면 그 말을 비서에게 보내요.
// 할 일이 끝난 줄의 카드(old)는 단추를 두지 않아요.
import Link from "next/link";
import type { GradeCompareData } from "@/lib/api/assistant";
import { CHOICE } from "@/lib/api/assistant";
import { won, wonDelta } from "@/lib/format";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";
import s from "./ChoiceCards.module.css";

const PAPER: Record<"economy" | "basic", string> = { economy: "합지", basic: "실크" };
const amount = (n: number | null) => (n == null ? "없음" : won(n));

export function GradeCompareCard({ card, ctx, old }: CardProps<"grade_compare">) {
  const d: GradeCompareData = card.data;
  const other = d.current === "basic" ? "economy" : d.current === "economy" ? "basic" : null;
  const total = { economy: d.economy_won, basic: d.basic_won };
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>벽지 두 종류 견주기</h3>
        <SourceTag src="calc" />
      </div>
      <p className={k.muted}>{d.label} · 부가세 포함</p>
      <ul className={s.cols} aria-label="벽지별 도배 합계(부가세 포함)">
        {(["economy", "basic"] as const).map((g) => (
          <li key={g} data-on={d.current === g || undefined}>
            <span>{PAPER[g]}</span>
            <b className={k.num}>{won(total[g])}</b>
            {d.current === g ? <small>지금 고른 벽지</small> : null}
          </li>
        ))}
      </ul>
      <p className={s.diff}>
        <span>실크가 합지보다</span>
        <b className={k.num}>{wonDelta(d.diff_won)}</b>
      </p>
      {d.rows.length ? (
        <div>
          <p className={s.rowsHead}>달라지는 줄 · 부가세 별도</p>
          <ul className={s.rows}>
            {d.rows.map((r) => (
              <li key={r.name}>
                <span>{r.name}</span>
                <span className={k.num}>합지 {amount(r.economy_won)} · 실크 {amount(r.basic_won)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className={k.row}>
        {other && d.can_change && !old ? (
          <button
            type="button"
            className={`${k.btn} ${k.sm}`}
            disabled={ctx.busy}
            onClick={() => ctx.send(`벽지를 ${PAPER[other]}로 바꿀래요`, { card_id: card.card_id, choice: CHOICE.grade(other) })}
          >
            {PAPER[other]}로 바꾸기
          </button>
        ) : null}
        <Link className={k.text} href={d.href} scroll={false}>표준견적서 보기<I n="chev" /></Link>
      </div>
    </section>
  );
}

export function MarketRangeCard({ card }: CardProps<"market_range">) {
  const d = card.data;
  // 표본이 모자라면 서버가 카드를 보내지 않아요(범위를 지어내지 않게). 그래도 오면 그리지 않아요
  if (!d.found || d.low_won == null || d.high_won == null) return null;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{d.trade} 시세 범위</h3>
        <SourceTag src="calc" />
      </div>
      <div className={k.kpi}>
        <span>{d.label}</span>
        <b className={`${s.range} ${k.num}`}>{won(d.low_won)}~{won(d.high_won)}</b>
        <small>부가세 포함 · 실측 전 참고 범위예요</small>
      </div>
      {d.assumed.length ? (
        <ul className={c.basisList} aria-label="계산에 넣은 것">{d.assumed.map((x) => <li key={x}>{x}</li>)}</ul>
      ) : null}
      <p className={s.src}>출처 · {d.source}</p>
    </section>
  );
}

export function OptionsCard({ card, ctx, old }: CardProps<"options">) {
  const d = card.data;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <h3 id={`${card.card_id}-t`}>{d.title}</h3>
      <ul className={s.opts}>
        {d.options.map((o) => (
          <li key={o.say}>
            <button type="button" className={s.opt} disabled={ctx.busy || old} onClick={() => ctx.send(o.say)}>
              {o.label}
              {o.sub ? <small>{o.sub}</small> : null}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

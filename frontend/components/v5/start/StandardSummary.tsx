// 첫 대화(/start) 표준견적서 요약: 큰 금액(부가세 포함) · 큰 줄 몇 개 · 공사 일수 · '믿집 계산' · [견적서 열기].
// 금액 · 일수는 계산 엔진 값 그대로예요. 큰 줄 금액은 API가 공급가(부가세 별도)로 줘서 합계와 기준이 달라 줄 머리에 '공급가'를 붙여요.
import Link from "next/link";
import type { ReactNode } from "react";
import { won } from "@/lib/v5/format";
import { daysCaption } from "@/lib/v5/guest/standard";
import t from "./start.module.css";

export type StandardQuoteData = {
  /** 부가세 포함 */
  total_won: number;
  label: string;
  lines: { name: string; won: number }[];
  /** 예상 공사 일수(계산 엔진, 글) */
  days: string | null;
  partial: boolean;
  /** 비면 열기 단추를 빼요 */
  href: string;
};

/** 출처 이름표: 믿집 계산(계산 엔진) · 믿집 안내(정해 둔 글) */
const SRC_WORD = { calc: "믿집 계산", guide: "믿집 안내" } as const;
export function SourceTag({ src }: { src: keyof typeof SRC_WORD }) {
  return <span className={t.src}>{SRC_WORD[src]}</span>;
}

export function StandardSummary({ id, data: d, more }: { id: string; data: StandardQuoteData; more?: ReactNode }) {
  const days = daysCaption(d.days);
  return (
    <section className={t.card} aria-labelledby={`${id}-t`}>
      <div className={t.top}>
        <h3 id={`${id}-t`}>표준견적서</h3>
        <SourceTag src="calc" />
      </div>
      <div className={t.kpi}>
        <span>{d.label}</span>
        <b className={t.num}>{won(d.total_won)}</b>
        <small>{["부가세 포함", days, d.partial ? "실측 후 확정 줄이 있어요" : ""].filter(Boolean).join(" · ")}</small>
      </div>
      {d.lines.length ? (
        <div>
          <p className={t.linesHead} id={`${id}-l`}>큰 줄 · 공급가(부가세 별도)</p>
          <ul className={t.lines} aria-labelledby={`${id}-l`}>
            {d.lines.map((l) => <li key={l.name}><span>{l.name}</span><b className={t.num}>{won(l.won)}</b></li>)}
          </ul>
        </div>
      ) : null}
      <div className={t.row}>
        {/* 주소가 비면(로그인한 고객의 첫 대화: 공사를 만들기 전) 열기 단추를 빼요 */}
        {d.href ? <Link className={`${t.btn} ${t.sm}`} href={d.href} scroll={false}>견적서 열기</Link> : null}
        {more}
      </div>
    </section>
  );
}

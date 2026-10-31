"use client";
// 한눈에 보기: 총액 · 기간 · 공정별 금액 · 실측 때 꼭 물어볼 것 · 금액 근거 · 가견적 받기.
// 금액 · 기간 · 줄 수는 API 값을 그대로 보이고, 실측 질문은 공정 의견에서 고르기만 한다.
import Link from "next/link";
import type { Ref } from "react";
import type { Schemas } from "@/lib/backend/client";
import { duration, won } from "@/lib/format";
import { LINE_BASIS, type LineBasis } from "@/lib/labels";
import { BasisBadge } from "./BasisBadge";
import s from "./Summary.module.css";

type Out = Schemas["ConsultOut"];
type Plan = Schemas["PlanOut"];
type Sum = Schemas["SummaryOut"];

const MAX_CHECKS = 3;

/** 실측 때 꼭 물어볼 것: 공정 의견의 실측 질문을 공정마다 앞에서부터 번갈아 골라 최대 MAX_CHECKS개 */
function pickChecks(results: Out["results"], plans: Record<string, Plan>) {
  const lists = results.map((r) => ({ trade: r.trade, label: r.label, items: plans[r.trade]?.visit_checks ?? [] }));
  const out: { key: string; label: string; text: string }[] = [];
  for (let i = 0; out.length < MAX_CHECKS && lists.some((l) => l.items.length > i); i++) {
    for (const l of lists) {
      if (out.length < MAX_CHECKS && l.items.length > i) out.push({ key: `${l.trade}-${i}`, label: l.label, text: l.items[i] });
    }
  }
  return out;
}

/** 공정 줄을 누르면 그 공정 자세히(details)를 펼친다. 이동은 #주소가 한다 */
function openTrade(trade: string) {
  const el = document.getElementById(`trade-${trade}`);
  if (el instanceof HTMLDetailsElement) el.open = true;
}

type Props = { out: Out; summary: Sum; plans: Record<string, Plan>; projectId: string; headingRef?: Ref<HTMLHeadingElement> };

export function Summary({ out, summary, plans, projectId, headingRef }: Props) {
  const checks = pickChecks(out.results, plans);
  const basis = (Object.keys(LINE_BASIS) as LineBasis[]).filter((k) => summary.basis_counts[k] > 0);
  return (
    <section className={`mj-panel ${s.card}`} aria-labelledby="sum-h">
      <div className={s.head}>
        <h2 id="sum-h" ref={headingRef} tabIndex={-1} className="mj-h2">한눈에 보기</h2>
        <p className="mj-small">공공 기준 단가로 믿집이 계산한 표준견적서예요. 업체 견적이 아니에요.</p>
      </div>

      <dl className={s.stats}>
        <div className={s.stat}>
          <dt>예상 금액 · VAT 포함</dt>
          <dd>
            <b className={`mj-num ${s.total}`}>{won(summary.total)}</b>
            <span className="mj-small mj-num">
              <span className={s.keep}>VAT 별도 {won(summary.subtotal)}</span> · <span className={s.keep}>부가세 {won(summary.vat)}</span>
            </span>
          </dd>
        </div>
        <div className={s.stat}>
          <dt>예상 기간</dt>
          <dd>
            <b className={`mj-num ${s.days}`}>약 {duration(summary.days)}</b>
            <span className="mj-small">일하는 날 기준이에요</span>
          </dd>
        </div>
      </dl>

      <div className={s.block}>
        <h3 className={s.blockH}>공정별 금액 <span className="mj-small">VAT 포함</span></h3>
        <ul className={s.trades}>
          {out.results.map((r) => (
            <li key={r.trade}>
              <a href={`#trade-${r.trade}`} className={s.trade} onClick={() => openTrade(r.trade)}>
                <span className={s.tradeName}>{r.label}</span>{" "}
                <span className={`mj-num ${s.tradeAmt}`}>{won(r.quote.total)}</span>{" "}
                <span className={s.more}>자세히</span>
              </a>
            </li>
          ))}
        </ul>
      </div>

      {out.overlaps.length ? (
        <ul className={s.notes}>
          {out.overlaps.map((t) => <li key={t} className="mj-notice mj-notice-warn"><span>{t}</span></li>)}
        </ul>
      ) : null}

      {checks.length ? (
        <div className={s.block}>
          <h3 className={s.blockH}>실측 때 꼭 물어볼 것</h3>
          <ol className={s.checks}>
            {checks.map((c) => (
              <li key={c.key}><span className={`mj-badge mj-b-in ${s.checkTrade}`}>{c.label}</span> {c.text}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {basis.length ? (
        <div className={s.block}>
          <h3 className={s.blockH}>금액 근거</h3>
          <ul className={s.basis}>
            {basis.map((k) => (
              <li key={k}><BasisBadge basis={k} /> <b className="mj-num">{summary.basis_counts[k]}줄</b>은 {LINE_BASIS[k].desc}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {out.notice ? <p className="mj-notice mj-notice-warn"><span>{out.notice}</span></p> : null}

      <div className={s.cta}>
        <Link href={`/projects/${projectId}/vendors`} className={`mj-btn mj-btn-pri ${s.ctaBtn}`}>가견적 받기</Link>
        <p className="mj-small">업체에 가견적을 요청해서 이 금액과 비교해 봐요.</p>
      </div>
    </section>
  );
}

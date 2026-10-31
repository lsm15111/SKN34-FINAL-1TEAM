// 공정 하나의 자세히 (기본 닫힘): 표준견적서 줄 · 계산에 넣은 가정 · 공정 의견(AI가 만든 설명).
// 줄 표는 넓을 때 표, 좁을 때 줄별 카드로 보인다 (TradeDetail.module.css의 컨테이너 쿼리).
import type { Schemas } from "@/lib/backend/client";
import { duration, halfDays, won, wonFull } from "@/lib/format";
import { LINE_STATE } from "@/lib/labels";
import { BasisBadge } from "./BasisBadge";
import { FoldIcon } from "./FoldIcon";
import s from "./TradeDetail.module.css";

type Result = Schemas["TradeOut"];
type Plan = Schemas["PlanOut"];
type Line = Schemas["LineOut"];

// 합계에 들어가지 않는 줄은 흐리게 보인다 (합계는 계산 엔진 값)
const counted = (l: Line) => l.state === "included" || l.state === "separate";
const qty = (l: Line) => (l.qty != null ? `${l.qty}${l.unit}` : null);
const price = (l: Line) => (l.unit_price != null ? `${wonFull(l.unit_price)}/${l.unit}` : null);
const amount = (l: Line) => (l.amount != null ? wonFull(l.amount) : "—");

export function TradeDetail({ r, plan }: { r: Result; plan?: Plan }) {
  const q = r.quote;
  const id = `trade-${r.trade}`;
  return (
    <details id={id} className={`mj-fold mj-panel ${s.fold}`}>
      <summary className={s.sum}>
        <span className={s.sumName}>{r.label}</span>{" "}
        <span className={`mj-num ${s.sumAmt}`}>{won(q.total)}<span className="mj-sr"> VAT 포함</span></span>
        <FoldIcon />
      </summary>
      <div className={s.body}>
        <dl className={s.totals}>
          <div><dt>VAT 별도</dt><dd className="mj-num">{won(q.subtotal)}</dd></div>
          <div><dt>부가세</dt><dd className="mj-num">{won(q.vat)}</dd></div>
          <div><dt>합계 · VAT 포함</dt><dd className={`mj-num ${s.accent}`}>{won(q.total)}</dd></div>
          <div><dt>{r.label}만 하면</dt><dd className="mj-num">약 {duration(q.days)}</dd></div>
        </dl>

        <h3 className="mj-h3">견적 줄</h3>
        <div className={`mj-table-box ${s.tableBox}`}>
          <table className={`mj-table ${s.table}`}>
            <caption className="mj-sr">{r.label} 표준견적서 줄</caption>
            <thead>
              <tr><th scope="col">항목</th><th scope="col" className="r">수량 × 단가</th><th scope="col" className="r">금액</th><th scope="col">포함 상태</th><th scope="col">근거</th></tr>
            </thead>
            <tbody>
              {q.lines.map((l) => (
                <tr key={l.key} className={counted(l) ? undefined : s.off}>
                  <th scope="row">{l.name} <span className={s.src}>{l.source}</span></th>
                  <td className="r mj-num">{[qty(l), price(l)].filter(Boolean).join(" × ") || "—"}</td>
                  <td className="r mj-num">{amount(l)}</td>
                  <td className={s.nowrap}>{LINE_STATE[l.state]}</td>
                  <td><BasisBadge basis={l.basis} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className={s.cards} aria-label={`${r.label} 표준견적서 줄`}>
          {q.lines.map((l) => {
            const per = [qty(l), price(l)].filter(Boolean).join(" × ");
            return (
              <li key={l.key} className={`${s.item} ${counted(l) ? "" : s.off}`}>
                <div className={s.itemTop}>
                  <b>{l.name}</b>{" "}
                  <BasisBadge basis={l.basis} />
                </div>
                <div className={s.itemAmt}>
                  <span className="mj-num">{amount(l)}</span>{" "}
                  <span className="mj-small">{LINE_STATE[l.state]}</span>
                </div>
                {per ? <> <span className="mj-small mj-num">{per}</span></> : null}
                {" "}<span className={s.src}>{l.source}</span>
              </li>
            );
          })}
        </ul>
        <p className="mj-small">합계에는 &lsquo;포함&rsquo;과 &lsquo;따로 계산&rsquo; 줄만 들어가요. &lsquo;실측 후&rsquo; 줄은 실측 뒤 업체 견적에서 정해져요.</p>

        {q.assumptions.length ? (
          <>
            <h3 className="mj-h3">계산에 넣은 가정</h3>
            <ul className={s.list}>{q.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          </>
        ) : null}

        <section className={s.plan} aria-labelledby={`${id}-plan`}>
          <div className={s.planHead}>
            <h3 id={`${id}-plan`} className="mj-h3">{r.label} 전문가 의견</h3>
            {plan ? <span className="mj-badge mj-b-wait">AI가 만든 설명</span> : null}
          </div>
          {plan ? (
            <>
              <p>{plan.summary}</p>
              <h4 className={s.h4}>작업 순서</h4>
              <ol className={s.list}>
                {q.steps.map((st) => {
                  const note = plan.steps.find((p) => p.key === st.key)?.note;
                  return (
                    <li key={st.key}>
                      <b>{st.name}</b> <span className="mj-small mj-num">{halfDays(st.half_days)}</span>
                      {note ? <> <span className={s.note}>{note}</span></> : null}
                    </li>
                  );
                })}
              </ol>
              {plan.visit_checks.length ? (
                <>
                  <h4 className={s.h4}>실측 때 업체에게 물어볼 것</h4>
                  <ul className={s.list}>{plan.visit_checks.map((c) => <li key={c}>{c}</li>)}</ul>
                </>
              ) : null}
              {plan.cautions.length ? (
                <>
                  <h4 className={s.h4}>알아 두면 좋은 것</h4>
                  <ul className={s.list}>
                    {plan.cautions.map((c) => <li key={c.text}>{c.text} <span className={s.note}>출처 · {c.source}</span></li>)}
                  </ul>
                </>
              ) : null}
            </>
          ) : (
            <p className="mj-small">설명을 만들지 못했어요. 계산 결과만 보여 드려요.</p>
          )}
        </section>
      </div>
    </details>
  );
}

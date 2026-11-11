"use client";
// 미리 보기 결과. 숫자는 API(계산 엔진)가 준 값을 그대로 보이고, 화면에서 더하거나 나누지 않는다.
import type { MvpPreview } from "@/lib/api/mvp";
import { decText, numText, won, wonDelta } from "@/lib/format";
import { crewLabel, tradeLabel } from "@/lib/labels";
import { BASIS, gradeName } from "./labels";
import s from "./mvp.module.css";

type Trade = MvpPreview["trades"][number];

function Lines({ t }: { t: Trade }) {
  return (
    <div className="mj-table-box">
      <table className={`mj-table ${s.lines}`}>
        <caption>{tradeLabel(t.trade)} 줄별 금액 (부가세 별도, 원)</caption>
        <thead>
          <tr>
            <th scope="col">항목</th>
            <th scope="col" className="r">수량</th>
            <th scope="col" className="r">금액</th>
          </tr>
        </thead>
        <tbody>
          {t.lines.map((l) => (
            <tr key={l.key} className={l.state === "after_visit" || l.state === "excluded" ? s.off : undefined}>
              <th scope="row">
                {l.name}
                <span className={s.basis}>{BASIS[l.price_basis] ?? l.price_basis}</span>
                {l.calc ? <span className="mj-small">{l.calc}</span> : null}
              </th>
              <td className="r">{l.qty != null ? `${decText(l.qty)}${l.unit}` : l.unit}</td>
              <td className="r">
                {l.state === "after_visit" ? "실측 후" : l.state === "excluded" ? "안 함" : l.amount != null ? numText(l.amount) : "—"}
                {l.unit_price != null && l.qty != null ? <span className="mj-small">{numText(l.unit_price)}/{l.unit}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeCard({ t }: { t: Trade }) {
  const m = t.market;
  return (
    <section className={s.trade} aria-labelledby={`mvp-${t.trade}`}>
      <div className={s.tradeHead}>
        <h3 id={`mvp-${t.trade}`} className="mj-h3">
          {tradeLabel(t.trade)}
          {t.trade === "dobae" && t.grade ? <span className="mj-small"> · {t.grade === "economy" ? "합지" : "실크"}</span> : null}
        </h3>
        <p className={s.big}>
          {won(t.total)} <span className="mj-small">부가세 포함 · 공공 기준</span>
        </p>
        <p className="mj-small">기간 {decText(t.days)}일 · {crewLabel(t.trade)} 품 {decText(t.man_day)}</p>
      </div>
      <div className={s.market}>
        <p>
          업체 견적은 보통 <b>{won(m.lo)} ~ {won(m.hi)}</b> <span className="mj-small">부가세 별도</span>
        </p>
        <p className="mj-small">실견적 {numText(m.n)}건을 보고 맞춘 범위예요. 시장 기준 금액은 {won(m.supply)}이에요.</p>
        {m.gap.length ? (
          <details>
            <summary>표준견적서와 금액이 다른 이유</summary>
            <ul className={s.gap}>
              <li>
                <span>표준견적서 (부가세 포함)</span>
                <b>{won(m.gap_start)}</b>
              </li>
              {m.gap.map((g) => (
                <li key={g.key}>
                  <span>
                    {g.name}
                    <span className="mj-small">{g.why}</span>
                  </span>
                  <b>{wonDelta(g.d)}</b>
                </li>
              ))}
              <li>
                <span>시장 기준 (부가세 별도)</span>
                <b>{won(m.supply)}</b>
              </li>
            </ul>
          </details>
        ) : null}
      </div>
      <details>
        <summary>줄별 금액 · 계산 방법 보기</summary>
        <Lines t={t} />
        <ul className={s.notes}>
          {t.notes.map((n) => (
            <li key={n} className="mj-small">{n}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export function PreviewResult({ result, busy, error }: { result: MvpPreview | null; busy: boolean; error: string }) {
  return (
    <section className={s.card} aria-labelledby="mvp-res-t" aria-busy={busy}>
      <h2 id="mvp-res-t" className="mj-h2">3. 다시 계산한 견적</h2>
      <p className="mj-small" role="status">
        {error ? null : busy ? "계산하고 있어요…" : result ? `${gradeName(result.grade)} 등급 · ${result.plan ? `${result.plan.name} 평면도` : "평형으로 어림"}` : ""}
      </p>
      {error ? <p className="mj-notice mj-notice-bad" role="alert">{error}</p> : null}
      {result ? (
        <div className={busy ? s.stale : undefined}>
          {result.plan_qty ? (
            <p className="mj-small">
              평면도에서 잰 수량: 벽 {decText(result.plan_qty.wall_m2)}㎡ · 천장 {decText(result.plan_qty.ceiling_m2)}㎡ · 몰딩 {decText(result.plan_qty.molding_m)}m · 걸레받이{" "}
              {decText(result.plan_qty.base_m)}m · 방문 {result.plan_qty.doors}개
              {result.plan_qty.low.length ? ` (그림 비율로 읽은 곳: ${result.plan_qty.low.join(", ")})` : ""}
            </p>
          ) : null}
          {result.trades.map((t) => (
            <TradeCard key={t.trade} t={t} />
          ))}
          <p className={s.sum}>
            합계 <b>{won(result.total)}</b> <span className="mj-small">부가세 포함 · 공공 기준</span>
          </p>
        </div>
      ) : null}
    </section>
  );
}

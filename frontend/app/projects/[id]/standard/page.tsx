import { isDemoProject } from "@/lib/api/project";
import { getStandardQuote } from "@/lib/api/quote";
import { SeeInConsult } from "@/components/project/RealProjectHub";
import { TRADES, TRADE_LABEL } from "@/lib/types";
import { md, won, wonFull } from "@/lib/format";

export const metadata = { title: "표준견적서" };

export default async function StandardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <SeeInConsult id={id} title="표준견적서" />;
  const q = await getStandardQuote(id);
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">표준견적서</h1>
        <p className="mj-sub">우리 집 조건으로 공공 단가를 적용한 기준 금액이에요. 업체 가견적을 볼 때 비교 기준으로 써요.</p>
      </div>

      <section className="mj-panel" aria-labelledby="tot-h" style={{ flexDirection: "row", flexWrap: "wrap", gap: 24 }}>
        <h2 id="tot-h" className="mj-sr">기준 금액 요약</h2>
        {TRADES.map((t) => (
          <div key={t} style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 180 }}>
            <span className="mj-small" style={{ fontWeight: 700 }}>{TRADE_LABEL[t]} 기준 금액</span>
            <b className="mj-num" style={{ fontSize: "var(--fs-h2)" }}>{won(q.totals[t])}</b>
          </div>
        ))}
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 200, paddingLeft: 24, borderLeft: "1px solid var(--line)" }}>
          <span className="mj-small" style={{ fontWeight: 700 }}>합계 · 공공 기준</span>
          <b className="mj-num" style={{ fontSize: "var(--fs-h2)", color: "var(--accent-ink)" }}>{won(q.totals.all)}</b>
          <span className="mj-tiny">부가세 · 일부 자재 제외</span>
        </div>
      </section>

      <p className="mj-notice mj-notice-warn"><span>{q.notice}</span></p>

      {TRADES.map((t) => (
        <div key={t} className="mj-table-box">
          <table className="mj-table">
            <caption>{TRADE_LABEL[t]} · {t === "dobae" ? `도배 면적 ${q.qty.totalM2}㎡ (벽 ${q.qty.wall} · 천장 ${q.qty.ceil})` : `몰딩 ${q.qty.molding}m · 걸레받이 ${q.qty.base}m`}</caption>
            <thead><tr><th scope="col">항목</th><th scope="col" className="r">수량</th><th scope="col" className="r">공공 단가</th><th scope="col" className="r">금액</th><th scope="col">출처 · 적용 시점</th></tr></thead>
            <tbody>
              {q.lines.filter((l) => l.trade === t).map((l) => (
                <tr key={l.k}>
                  <th scope="row">{l.name}</th>
                  <td className="r mj-num">{l.qty != null ? `${l.qty}${l.unit}` : "—"}</td>
                  <td className="r mj-num">{l.unitPrice != null ? `${l.unitPrice.toLocaleString("ko-KR")}원/${l.unit}` : "—"}</td>
                  <td className="r mj-num">{l.amount != null ? wonFull(l.amount) : <span className="mj-badge mj-b-opt">공공 가격 없음</span>}</td>
                  <td className="muted">{l.src}</td>
                </tr>
              ))}
              <tr className="total"><th scope="row" colSpan={3}>{TRADE_LABEL[t]} 기준 금액</th><td className="r mj-num">{wonFull(q.totals[t])}</td><td /></tr>
            </tbody>
          </table>
        </div>
      ))}

      <div className="mj-split">
        <section className="mj-col mj-panel" aria-labelledby="src-h">
          <h2 id="src-h" className="mj-h3">데이터 출처와 적용 시점</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>{q.sources.map((s) => <li key={s}>{s}</li>)}</ul>
          <p className="mj-small">수량 기준: {q.qty.basis}. 만든 날 {md(q.createdAt)}.</p>
        </section>
        <section className="mj-aside mj-panel" aria-labelledby="ex-h">
          <h2 id="ex-h" className="mj-h3">기준 금액에 없는 것</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>{q.excluded.map((s) => <li key={s}>{s}</li>)}</ul>
          <p className="mj-small">이 항목은 업체 가견적에서 확인해요.</p>
        </section>
      </div>
    </main>
  );
}

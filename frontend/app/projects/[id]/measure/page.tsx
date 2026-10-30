import { notFound } from "next/navigation";
import { NotConnected } from "@/components/project/RealProjectHub";
import { getProject, isDemoProject } from "@/lib/api/project";
import { getFinalQuote } from "@/lib/api/quote";
import { listAllVendors } from "@/lib/api/vendor";
import { getVisits } from "@/lib/api/visit";
import { TradeTabs } from "@/components/project/TradeTabs";
import { LineBadge } from "@/components/project/LineBadge";
import { ConfirmPanel } from "@/components/project/ConfirmPanel";
import { TRADE_LABEL, type Trade } from "@/lib/types";
import { md, won, wonDelta, wonFull } from "@/lib/format";

export const metadata = { title: "실측 견적" };

export default async function MeasurePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const { trade: tq } = await searchParams;
  const p = await getProject(id);
  if (!p) notFound();
  const trades = (["dobae", "mokgong"] as Trade[]).filter((t) => p.trades[t]);
  const trade: Trade = tq === "mokgong" && trades.includes("mokgong") ? "mokgong" : trades[0];
  const [f, visits, vendors] = await Promise.all([getFinalQuote(id, trade), getVisits(id), listAllVendors()]);
  const v = vendors.find((x) => x.id === f.vendorId);
  const visit = visits.find((x) => x.trade === trade);

  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">실측 견적</h1>
      </div>
      <TradeTabs base={`/projects/${id}/measure`} trades={trades} current={trade} />

      <div className="mj-split">
        <div className="mj-col">
          <section className="mj-panel" aria-labelledby="fq-h">
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
              <h2 id="fq-h" className="mj-h2">{v?.name} · {TRADE_LABEL[trade]}</h2>
              <span className="mj-small">{visit ? `실측 ${md(visit.at.slice(0, 10))} ${visit.at.slice(11)}` : ""}</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
              <div style={{ display: "flex", flexDirection: "column" }}><span className="mj-small" style={{ fontWeight: 700 }}>실측 견적 · 부가세 별도</span><b className="mj-num" style={{ fontSize: "var(--fs-h1)" }}>{won(f.total)}</b></div>
              <div style={{ display: "flex", flexDirection: "column" }}><span className="mj-small" style={{ fontWeight: 700 }}>가견적과 비교</span><span className="mj-num" style={{ fontSize: "var(--fs-lg)" }}>{won(f.estimateTotal)} → <b style={{ color: f.deltaTotal > 0 ? "var(--danger)" : "var(--ok)" }}>{wonDelta(f.deltaTotal)}</b></span></div>
            </div>
          </section>

          <section className="mj-panel" aria-labelledby="fd-h">
            <h2 id="fd-h" className="mj-h3">실측에서 확인한 것</h2>
            <ul style={{ margin: 0, paddingLeft: 20 }}>{f.findings.map((x) => <li key={x}>{x}</li>)}</ul>
            <h3 className="mj-h3" style={{ fontSize: "var(--fs-md)", marginTop: 4 }}>바뀐 줄</h3>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {f.diff.map((d) => (
                <li key={d.name} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                  <span className="mj-badge" style={{ border: "1.5px solid var(--danger)", color: "var(--danger)" }} aria-label="바뀐 줄">△1</span>
                  <b>{d.name}</b>
                  <span className="mj-num mj-small">{d.from != null && d.to != null ? <><s>{d.from}</s> → {d.to}</> : d.to != null ? "새로 생김" : "빠짐"}</span>
                  <span className="mj-num" style={{ color: d.delta > 0 ? "var(--danger)" : "var(--ok)", fontWeight: 700 }}>{wonDelta(d.delta)}</span>
                </li>
              ))}
            </ul>
          </section>

          <details className="mj-panel">
            <summary style={{ cursor: "pointer", minHeight: 32, fontWeight: 700 }}>실측 견적서 전체 보기</summary>
            <div className="mj-table-box">
              <table className="mj-table">
                <caption className="mj-sr">실측 견적서 항목</caption>
                <thead><tr><th scope="col">항목</th><th scope="col" className="r">수량</th><th scope="col" className="r">금액</th><th scope="col">구분</th><th scope="col">비고</th></tr></thead>
                <tbody>
                  {f.lines.map((l) => <tr key={l.k}><th scope="row" style={{ fontWeight: 500 }}>{l.name}</th><td className="r mj-num">{l.qty != null ? `${l.qty}${l.unit}` : "—"}</td><td className="r mj-num">{l.amount ? wonFull(l.amount) : "—"}</td><td><LineBadge state={l.state} /></td><td className="muted">{l.note}</td></tr>)}
                  <tr className="total"><th scope="row" colSpan={2}>합계 · 부가세 별도</th><td className="r mj-num">{wonFull(f.total)}</td><td colSpan={2} /></tr>
                </tbody>
              </table>
            </div>
          </details>
        </div>

        <aside className="mj-aside">
          <ConfirmPanel projectId={id} trade={trade} tradeLabel={TRADE_LABEL[trade]} vendorName={v?.name ?? ""} confirmedOn="2026-10-28" />
        </aside>
      </div>
    </main>
  );
}

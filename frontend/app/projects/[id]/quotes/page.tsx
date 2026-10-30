import { notFound } from "next/navigation";
import { NotConnected } from "@/components/project/RealProjectHub";
import { getProject, isDemoProject } from "@/lib/api/project";
import { getCompare, getQuoteRequests, getVendorQuotes } from "@/lib/api/quote";
import { listAllVendors } from "@/lib/api/vendor";
import { getVisits } from "@/lib/api/visit";
import { TradeTabs } from "@/components/project/TradeTabs";
import { LineBadge, LineStateLegend } from "@/components/project/LineBadge";
import { MeasurePick } from "@/components/project/MeasurePick";
import { TRADE_LABEL, type CompareCell, type Trade } from "@/lib/types";
import { md, won, wonFull } from "@/lib/format";

export const metadata = { title: "가견적 비교" };
const STATUS = { requested: { t: "요청함", c: "mj-b-wait" }, received: { t: "도착", c: "mj-b-in" }, registered: { t: "등록됨", c: "mj-b-ok" } } as const;

function Cell({ c }: { c: CompareCell }) {
  return c.amount != null
    ? <><span className="mj-num">{wonFull(c.amount)}</span>{c.text ? <span className="muted" style={{ display: "block" }}>{c.text}</span> : null}</>
    : <span className="muted">{c.text}</span>;
}

export default async function QuotesPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const { trade: tq } = await searchParams;
  const p = await getProject(id);
  if (!p) notFound();
  const trades = (["dobae", "mokgong"] as Trade[]).filter((t) => p.trades[t]);
  const trade: Trade = tq === "mokgong" && trades.includes("mokgong") ? "mokgong" : trades[0];
  const [reqs, quotes, cmp, visits, vendors] = await Promise.all([getQuoteRequests(id), getVendorQuotes(id, trade), getCompare(id, trade), getVisits(id), listAllVendors()]);
  const name = (vid: string) => vendors.find((v) => v.id === vid)?.name ?? vid;
  const myReqs = reqs.filter((r) => r.trade === trade);
  const visit = visits.find((v) => v.trade === trade);
  const counts = Object.fromEntries(trades.map((t) => [t, `${reqs.filter((r) => r.trade === t && r.status !== "requested").length}곳 도착`]));

  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">가견적 비교</h1>
      </div>
      <TradeTabs base={`/projects/${id}/quotes`} trades={trades} current={trade} counts={counts} />

      <section aria-labelledby="st-h" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 id="st-h" className="mj-h3">{TRADE_LABEL[trade]} 요청 상태</h2>
        <ul className="mj-chips" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {myReqs.map((r) => (
            <li key={r.vendorId} className="mj-chip" style={{ gap: 8 }}>
              <b>{name(r.vendorId)}</b><span className={`mj-badge ${STATUS[r.status].c}`}>{STATUS[r.status].t}</span><span className="mj-tiny mj-num">요청 {md(r.requestedAt)}{r.receivedAt ? ` · 도착 ${md(r.receivedAt)}` : ""}</span>
            </li>
          ))}
        </ul>
      </section>

      <div className="mj-table-box">
        <table className="mj-table" style={{ minWidth: 760 }}>
          <caption>{TRADE_LABEL[trade]} · 표준견적서와 가견적 비교</caption>
          <thead>
            <tr>
              <th scope="col">항목</th>
              <th scope="col" style={{ background: "var(--accent-weak)", color: "var(--accent-ink)" }}>표준견적서<br /><span style={{ fontWeight: 500 }}>공공 기준</span></th>
              {quotes.map((q) => <th key={q.vendorId} scope="col">{name(q.vendorId)}</th>)}
            </tr>
          </thead>
          <tbody>
            {cmp.rows.map((r) => (
              <tr key={r.key}>
                <th scope="row">{r.label}</th>
                <td style={{ background: "var(--surface)" }}><Cell c={r.std} /></td>
                {quotes.map((q) => <td key={q.vendorId}><Cell c={r.vendors[q.vendorId]} /></td>)}
              </tr>
            ))}
            <tr className="total">
              <th scope="row">{cmp.total.label}</th>
              <td style={{ background: "var(--surface)" }}><Cell c={cmp.total.std} /></td>
              {quotes.map((q) => <td key={q.vendorId}><Cell c={cmp.total.vendors[q.vendorId]} /></td>)}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mj-small">표준견적서는 공공 단가가 있는 줄만 더한 참고 금액이라 업체 합계와 바로 같지 않아요. 같은 줄끼리 보세요.</p>

      <section aria-labelledby="raw-h" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 id="raw-h" className="mj-h3">업체가 보낸 가견적서</h2>
        <LineStateLegend />
        {quotes.map((q) => (
          <details key={q.vendorId} className="mj-panel" style={{ gap: 10 }}>
            <summary style={{ cursor: "pointer", minHeight: 32, fontWeight: 700 }}>{name(q.vendorId)} · <span className="mj-num">{won(q.total)}</span> <span className="mj-small" style={{ fontWeight: 400 }}>· 부가세 별도 {wonFull(q.vat)}</span></summary>
            <div className="mj-table-box">
              <table className="mj-table">
                <caption className="mj-sr">{name(q.vendorId)} 가견적서 항목</caption>
                <thead><tr><th scope="col">항목</th><th scope="col" className="r">수량</th><th scope="col" className="r">금액</th><th scope="col">구분</th><th scope="col">비고</th></tr></thead>
                <tbody>
                  {q.lines.map((l) => (
                    <tr key={l.k}><th scope="row" style={{ fontWeight: 500 }}>{l.name}</th><td className="r mj-num">{l.qty != null ? `${l.qty}${l.unit}` : "—"}</td><td className="r mj-num">{l.amount ? wonFull(l.amount) : "—"}</td><td><LineBadge state={l.state} /></td><td className="muted">{l.note}</td></tr>
                  ))}
                  <tr className="total"><th scope="row" colSpan={2}>합계 · 이윤 {Math.round(q.marginRate * 100)}% 포함</th><td className="r mj-num">{wonFull(q.total)}</td><td colSpan={2} /></tr>
                </tbody>
              </table>
            </div>
          </details>
        ))}
      </section>

      <MeasurePick
        projectId={id}
        trade={trade}
        tradeLabel={TRADE_LABEL[trade]}
        options={quotes.map((q) => ({ id: q.vendorId, name: name(q.vendorId), total: won(q.total) }))}
        current={visit ? { name: name(visit.vendorId), when: `${md(visit.at.slice(0, 10))} ${visit.at.slice(11)}`, done: visit.status === "done" } : null}
      />
    </main>
  );
}

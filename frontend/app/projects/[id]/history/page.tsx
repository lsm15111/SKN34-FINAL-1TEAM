import Link from "next/link";
import { NotConnected } from "@/components/project/RealProjectHub";
import { getHistory, isDemoProject } from "@/lib/api/project";
import { TRADE_LABEL, type Trade } from "@/lib/types";
import { md } from "@/lib/format";

export const metadata = { title: "이력" };

export default async function HistoryPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const { trade } = await searchParams;
  const all = await getHistory(id);
  const t = trade === "dobae" || trade === "mokgong" ? (trade as Trade) : null;
  const items = t ? all.filter((h) => !h.trade || h.trade === t) : all;
  const dates = Array.from(new Set(items.map((h) => h.date)));
  const base = `/projects/${id}/history`;
  return (
    <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 860 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">업체 · 견적 이력</h1>
        <p className="mj-sub">비교한 업체, 표준견적서, 가견적서, 실측 견적서를 날짜순으로 모았어요.</p>
      </div>
      <nav aria-label="공정으로 거르기" className="mj-tabs">
        <Link href={base} aria-current={!t ? "page" : undefined}>전체</Link>
        <Link href={`${base}?trade=dobae`} aria-current={t === "dobae" ? "page" : undefined}>도배</Link>
        <Link href={`${base}?trade=mokgong`} aria-current={t === "mokgong" ? "page" : undefined}>목공</Link>
      </nav>
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 18 }}>
        {dates.map((d) => (
          <li key={d} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h2 className="mj-h3 mj-num">{md(d)}</h2>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, borderLeft: "3px solid var(--accent-pastel)", paddingLeft: 16, display: "flex", flexDirection: "column", gap: 10 }}>
              {items.filter((h) => h.date === d).map((h, i) => (
                <li key={i} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ display: "flex", gap: 8, alignItems: "center" }}><b>{h.kind}</b>{h.trade ? <span className="mj-badge mj-b-in">{TRADE_LABEL[h.trade]}</span> : null}</span>
                  <span className="mj-sub">{h.text}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </main>
  );
}

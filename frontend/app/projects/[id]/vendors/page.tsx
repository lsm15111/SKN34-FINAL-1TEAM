import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getProject, isDemoProject } from "@/lib/api/project";
import { getQuoteRequests, getSentRequests, getSourcing, getStandardQuote } from "@/lib/api/quote";
import { getRecommendations, listVendors } from "@/lib/api/vendor";
import { VendorPicker } from "@/components/vendors/VendorPicker";
import { SentRequests } from "@/components/vendors/SentRequests";
import { SourcingBoard } from "@/components/vendors/SourcingBoard";
import type { Trade } from "@/lib/types";

export const metadata = { title: "업체 고르기" };

export default async function VendorsPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  const { trade } = await searchParams;
  if (!isDemoProject(id)) return <RealVendors id={id} trade={trade} />;
  const p = await getProject(id);
  if (!p) notFound();
  const trades = (["dobae", "mokgong"] as Trade[]).filter((t) => p.trades[t]);
  const [std, reqs, recD, recM, vD, vM] = await Promise.all([
    getStandardQuote(id), getQuoteRequests(id), getRecommendations(id, "dobae"), getRecommendations(id, "mokgong"),
    listVendors({ trade: "dobae" }), listVendors({ trade: "mokgong" }),
  ]);
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">업체 고르기</h1>
      </div>
      <VendorPicker
        projectId={id}
        region={p.complex.sgg}
        trades={trades}
        initialTrade={trade === "mokgong" ? "mokgong" : "dobae"}
        recs={{ dobae: recD, mokgong: recM }}
        vendors={{ dobae: vD, mokgong: vM }}
        requested={{ dobae: reqs.filter((r) => r.trade === "dobae").map((r) => r.vendorId), mokgong: reqs.filter((r) => r.trade === "mokgong").map((r) => r.vendorId) }}
        stdTotals={{ dobae: std.totals.dobae, mokgong: std.totals.mokgong }}
      />
    </main>
  );
}

// 실제 프로젝트: 가견적 후보(받는 길 · 비용 · 출처)와 보낸 요청. 프로젝트 주인인지는 layout이 먼저 본다.
// 후보 설명(가견적 에이전트)이 늦을 수 있어서 후보 칸만 따로 기다린다.
async function RealVendors({ id, trade }: { id: string; trade?: string }) {
  const sent = await getSentRequests(id);
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">업체 고르기</h1>
        <p className="mj-sub">고른 공정과 지역에 맞는 업체예요. 업체마다 가견적을 받는 길이 달라서, 카드에 받는 길을 하나씩 적어 두었어요.</p>
      </div>
      {sent.length ? <SentRequests items={sent} /> : null}
      <Suspense fallback={<p className="mj-notice" role="status"><span>업체를 찾고 있어요. 설명을 붙이느라 조금 걸릴 수 있어요.</span></p>}>
        <Candidates id={id} trade={trade} />
      </Suspense>
    </main>
  );
}

async function Candidates({ id, trade }: { id: string; trade?: string }) {
  const src = await getSourcing(id);
  if (src && src !== "error") return <SourcingBoard data={src} initialTrade={trade} />;
  return (
    <section className="mj-panel" aria-labelledby="src-err-h" style={{ maxWidth: 640 }}>
      <h2 id="src-err-h" className="mj-h3">업체 목록을 불러오지 못했어요</h2>
      <p className="mj-sub">잠시 뒤에 다시 열어 주세요. 업체 찾기를 짧은 시간에 여러 번 하면 잠깐 쉬었다가 열려요.</p>
      <div className="mj-btn-row"><Link href={`/projects/${id}/vendors${trade ? `?trade=${encodeURIComponent(trade)}` : ""}`} className="mj-btn mj-btn-sec">다시 열기</Link></div>
    </section>
  );
}

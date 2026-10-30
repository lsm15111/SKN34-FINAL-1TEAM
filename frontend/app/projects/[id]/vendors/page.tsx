import { notFound } from "next/navigation";
import { NotConnected } from "@/components/project/RealProjectHub";
import { getProject, isDemoProject } from "@/lib/api/project";
import { getQuoteRequests, getStandardQuote } from "@/lib/api/quote";
import { getRecommendations, listVendors } from "@/lib/api/vendor";
import { VendorPicker } from "@/components/vendors/VendorPicker";
import type { Trade } from "@/lib/types";

export const metadata = { title: "업체 고르기" };

export default async function VendorsPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const { trade } = await searchParams;
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

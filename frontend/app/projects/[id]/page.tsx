import Link from "next/link";
import { RealProjectHub } from "@/components/project/RealProjectHub";
import { gradeLabel } from "@/lib/labels";
import { notFound } from "next/navigation";
import { ProjectTrack } from "@/components/project/ProjectTrack";
import { demoTradeLines, getMyProject, getProject, isDemoProject, realTradeLines } from "@/lib/api/project";
import { getFinalQuote, getQuoteRequests } from "@/lib/api/quote";
import { getConfirmedSchedule } from "@/lib/api/schedule";
import { vendorName } from "@/lib/api/vendor";
import { getVisits } from "@/lib/api/visit";
import { projectStep } from "@/lib/trade-status";
import { TRADES, TRADE_LABEL } from "@/lib/types";
import { md, won } from "@/lib/format";

export const metadata = { title: "진행 현황" };
const WHEN = { date: "날짜가 정해졌어요", movein: "이사하는 날만 정해졌어요", months: "1~2달 안에", unknown: "아직 몰라요" } as const;

export default async function ProjectHub({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) {
    const real = await getMyProject(id);
    if (!real) notFound();
    return <RealProjectHub p={real} step={projectStep(realTradeLines(TRADES.filter((t) => real.trades[t])))} />;
  }
  const p = await getProject(id);
  if (!p) notFound();
  const [reqs, visits, conf, lines] = await Promise.all([getQuoteRequests(id), getVisits(id), getConfirmedSchedule(id), demoTradeLines(id)]);
  const rows = await Promise.all(TRADES.filter((t) => p.trades[t]).map(async (t) => {
    const r = reqs.filter((x) => x.trade === t);
    const v = visits.find((x) => x.trade === t);
    const f = await getFinalQuote(id, t);
    return {
      t, requested: r.length, received: r.filter((x) => x.status !== "requested").length,
      visit: v ? `${await vendorName(v.vendorId)} · ${md(v.at.slice(0, 10))} 실측 끝남` : "아직 없어요",
      final: f ? `${won(f.total)}` : "아직 없어요",
      confirmedVendor: await vendorName(conf[t].vendorId),
      period: `${md(conf[t].start)} ~ ${md(conf[t].end)}`,
    };
  }));

  return (
    <main id="main" className="mj-wrap mj-main">
      <div className="mj-split">
        <div className="mj-col">
          <section className="mj-panel" aria-labelledby="now-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
            <ProjectTrack now={projectStep(lines)} />
            <span className="mj-eyebrow">지금 단계</span>
            <h1 id="now-h" className="mj-h2">공사 일정이 확정됐어요</h1>
            <p className="mj-sub">확정 업체가 공사기간을 등록해서 확정 공정표가 만들어졌어요. 공사 전에 관리사무소 신고와 엘리베이터 예약을 해 주세요.</p>
            <div className="mj-btn-row"><Link href={`/projects/${id}/schedule`} className="mj-btn mj-btn-pri">확정 공정표 보기</Link><Link href={`/projects/${id}/history`} className="mj-btn mj-btn-sec">지난 기록 보기</Link></div>
          </section>

          <section aria-labelledby="trade-h" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2 id="trade-h" className="mj-h2">공정별 진행</h2>
            <div className="mj-table-box">
              <table className="mj-table">
                <caption className="mj-sr">공정별 견적 요청 · 실측 · 확정 현황</caption>
                <thead><tr><th scope="col">공정</th><th scope="col">가견적</th><th scope="col">실측</th><th scope="col">실측 견적</th><th scope="col">확정 업체 · 공사기간</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.t}>
                      <th scope="row">{TRADE_LABEL[r.t]}</th>
                      <td><Link href={`/projects/${id}/quotes?trade=${r.t}`}>{r.requested}곳 요청 · {r.received}곳 도착</Link></td>
                      <td>{r.visit}</td>
                      <td className="mj-num"><Link href={`/projects/${id}/measure?trade=${r.t}`}>{r.final}</Link></td>
                      <td><b>{r.confirmedVendor}</b><br /><span className="mj-small mj-num">{r.period}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside className="mj-aside mj-panel" aria-labelledby="info-h">
          <h2 id="info-h" className="mj-h3">기본정보</h2>
          <dl className="mj-kv">
            <dt>단지</dt><dd>{p.complex.name}<br /><span className="mj-small">{p.complex.sido} {p.complex.sgg} {p.complex.dong} · {p.builtYear}년 준공</span></dd>
            <dt>평형</dt><dd className="mj-num">{p.complex.types.find((t) => t.id === p.unitTypeId)?.py}평형 · 공급 {p.area.supply} / 전용 {p.area.jeon}㎡{p.balconyExt ? " · 발코니 확장" : ""}</dd>
            <dt>시기</dt><dd>{WHEN[p.startPlan.kind]}{p.startPlan.date ? ` · ${md(p.startPlan.date)}` : ""}</dd>
            <dt>집 상태</dt><dd>{p.occupied ? "살면서 공사" : "빈집"}</dd>
            <dt>예산</dt><dd>{p.budget ?? "정하지 않음"}</dd>
            <dt>도배</dt><dd>{p.trades.dobae ? `${p.trades.dobae.spaces.length}곳 · ${gradeLabel(p.trades.dobae.grade)}` : "안 함"}</dd>
            <dt>목공</dt><dd>{p.trades.mokgong ? `${p.trades.mokgong.spaces.length}곳 · ${p.trades.mokgong.items.join(" · ")}` : "안 함"}</dd>
            <dt>사진 · 도면</dt><dd>사진 {p.photos.length}장 · {p.floorPlan ? "도면 있음" : "도면 없음"}</dd>
          </dl>
          <p className="mj-tiny">만든 날 {md(p.createdAt)}</p>
        </aside>
      </div>
    </main>
  );
}

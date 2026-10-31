import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { ConsultChat } from "@/components/consult/ConsultChat";
import { listMyProjects } from "@/lib/api/project";
import { sizeLabel } from "@/lib/labels";
import { TRADE_LABEL } from "@/lib/types";
import { requireRole } from "@/lib/session";

export const metadata = { title: "공정 상담" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ConsultPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const { project } = await searchParams;
  const projectId = project && UUID.test(project) ? project : null;
  await requireRole("customer", projectId ? `/consult?project=${projectId}` : "/consult");
  const head = (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="mj-eyebrow">공정 상담</span>
      <h1 className="mj-h1">우리 집 공사, 물어보면서 정해요</h1>
      <p className="mj-sub">견적 받기에서 알려 주신 정보로 공공 기준 표준견적서와 공정별 전문가 의견을 보여 드려요.</p>
    </div>
  );
  if (projectId) {
    return (
      <>
        <SiteHeader />
        <main id="main" className="mj-wrap mj-main">
          {head}
          <ConsultChat projectId={projectId} />
        </main>
      </>
    );
  }

  // 상담은 프로젝트(견적 받기에서 받은 집 정보)로 시작한다
  const mine = (await listMyProjects()).filter((p) => p.trades.some((t) => t in TRADE_LABEL));
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main">
        {head}
        <section className="mj-panel" aria-labelledby="pick-h">
          <h2 id="pick-h" className="mj-h2">{mine.length ? "상담할 프로젝트를 골라 주세요" : "먼저 집 정보를 알려 주세요"}</h2>
          {mine.length ? (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
              {mine.map((p) => (
                <li key={p.id}>
                  {/* 공정이 많으면 이름이 길어서 줄을 바꾼다 (폰 너비에서 가로 스크롤이 생기지 않게) */}
                  <Link href={`/consult?project=${p.id}`} className="mj-btn mj-btn-sec" style={{ width: "100%", justifyContent: "flex-start", whiteSpace: "normal", textAlign: "left", paddingBlock: 10 }}>
                    {p.region} · {sizeLabel(p.size)} · {p.trades.map((t) => TRADE_LABEL[t as keyof typeof TRADE_LABEL] ?? t).join(" · ")}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mj-sub">견적 받기에서 평수 · 공정 같은 기본 정보를 받은 뒤 상담을 시작해요.</p>
          )}
          <div className="mj-btn-row">
            <Link href="/start" className={`mj-btn ${mine.length ? "mj-btn-ghost" : "mj-btn-pri"}`}>새로 견적 받기</Link>
          </div>
        </section>
      </main>
    </>
  );
}

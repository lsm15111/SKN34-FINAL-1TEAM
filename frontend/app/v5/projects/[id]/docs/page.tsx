import { notFound } from "next/navigation";
import { DocsTable } from "@/components/v5/docs/DocsTable";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { ProjectCrumb } from "@/components/v5/project/ProjectCrumb";
import { getMyProject } from "@/lib/v5/api/project";
import { getDocs, listDeals } from "@/lib/api/schedule";
import { getVisitProject } from "@/lib/api/visit";
import { projectTitle, sizeLabel, TRADE_ORDER } from "@/lib/v5/labels";
import s from "@/components/docs/docs.module.css";

export const metadata = { title: "서류" };

// 서류 모음 (시안 WDocs): 이 공사의 표준견적서 · 공정표 · 실측 견적서 · 추가 금액 기록.
// 평은 서류 응답에 없어서 프로젝트를 같이 읽는다(레이아웃과 같은 요청이라 한 번만 부른다).
export default async function DocsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [p, docs, named] = await Promise.all([getMyProject(id), getDocs(id), getVisitProject(id)]);
  if (!p || !docs) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  // 다른 공사 화면과 같은 이름('노원구 아파트 도배')을 써요
  const title = named?.name ?? projectTitle(p.region, trades);
  // 확정 공정표 줄 아래 '목공 확정 · 도배 날짜 수락 전'은 공정별 업체 확정의 수락한 날짜로 쓴다
  const deals = docs.plans.some((x) => x.kind === "final") ? (await listDeals(id)) ?? [] : [];

  return (
    <>
      <AppHeader only="phone" phone={{ title: "서류", back: `/v5/projects/${encodeURIComponent(id)}` }} />
      <main id="main">
        <ProjectCrumb id={id} title={title} here="서류" />
        <div className={`mj-wrap ${s.head}`}>
          <h1 className="mj-h1">이 공사의 서류</h1>
          <p className="mj-sub mj-num">{docs.region} · {sizeLabel(p.size)} · 공사 번호 <span className="mj-code">{docs.code}</span></p>
        </div>
        <section className={`mj-wrap ${s.body}`} aria-labelledby="docs-t">
          <h2 id="docs-t" className="mj-sr">서류 목록</h2>
          <DocsTable docs={docs} trades={trades} deals={deals} />
        </section>
      </main>
    </>
  );
}

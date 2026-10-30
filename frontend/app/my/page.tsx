import { SiteHeader } from "@/components/site/SiteHeader";
import { DraftCard } from "@/components/my/DraftCard";
import { ProjectCard } from "@/components/my/ProjectCard";
import { QuoteButton } from "@/components/start/QuoteDialog";
import { demoProjectEnd, demoTradeLines, listDemoProjects, listMyProjects, realTradeLines } from "@/lib/api/project";
import { requireRole } from "@/lib/session";
import { sizeLabel } from "@/lib/labels";
import { dateSeoul, todaySeoul } from "@/lib/format";

export const metadata = { title: "내 프로젝트" };

// 마이페이지 · 내 프로젝트. 카드마다 공정별 상태 한 줄과 지금 할 일 버튼 하나.
// 견적 내역 · 공정표 · 이력은 프로젝트 안 이동 메뉴에 있어서 카드에 다시 두지 않는다.
export default async function MyPage() {
  await requireRole("customer", "/my");
  const [mine, demos] = await Promise.all([listMyProjects(), listDemoProjects()]);
  const today = todaySeoul();
  const demoCards = await Promise.all(demos.map(async (p) => {
    const [lines, end] = await Promise.all([demoTradeLines(p.id), demoProjectEnd(p.id)]);
    const finished = lines.every((l) => l.stage === "scheduled") && end !== null && end < today;
    return { p, lines, finished };
  }));
  const cards = [
    ...mine.map((p) => ({ key: p.id, finished: false, node: <ProjectCard key={p.id} id={p.id} title={`${p.region} · ${sizeLabel(p.size)}`} created={dateSeoul(p.created_at)} lines={realTradeLines(p.trades)} /> })),
    ...demoCards.map(({ p, lines, finished }) => ({ key: p.id, finished, node: <ProjectCard key={p.id} id={p.id} title={p.title} sub={`${p.complex.sgg} ${p.complex.dong}`} created={p.createdAt} lines={lines} demo /> })),
  ];
  const now = cards.filter((c) => !c.finished);
  const past = cards.filter((c) => c.finished);
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 860 }}>
        <h1 className="mj-h1">내 프로젝트</h1>
        <DraftCard />
        <section aria-labelledby="now-h" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <h2 id="now-h" className="mj-h2">진행 중</h2>
          {now.length ? <ul className="mj-pcards">{now.map((c) => <li key={c.key}>{c.node}</li>)}</ul> : <p className="mj-sub">진행 중인 프로젝트가 없어요.</p>}
          <QuoteButton label="새 견적 받기" className="mj-btn mj-btn-sec" style={{ alignSelf: "flex-start" }} />
        </section>
        {past.length ? (
          <details className="mj-past">
            <summary className="mj-h3">지난 프로젝트 <span className="mj-num">{past.length}</span></summary>
            <ul className="mj-pcards">{past.map((c) => <li key={c.key}>{c.node}</li>)}</ul>
          </details>
        ) : null}
        <p className="mj-small">견적 내역 · 공정표 · 이력은 프로젝트 안에서 볼 수 있어요.</p>
      </main>
    </>
  );
}

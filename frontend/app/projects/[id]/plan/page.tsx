import Link from "next/link";
import { NotConnected } from "@/components/project/RealProjectHub";
import { isDemoProject } from "@/lib/api/project";
import { getExpectedSchedule } from "@/lib/api/schedule";
import { Gantt, type GanttRow } from "@/components/project/Gantt";
import { GanttDownload } from "@/components/project/GanttDownload";
import { md } from "@/lib/format";

export const metadata = { title: "예상 공정표" };

export default async function PlanPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ new?: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const { new: isNew } = await searchParams;
  const s = await getExpectedSchedule(id);
  const rows: GanttRow[] = s.tasks.map((t) => ({ label: t.label, sub: t.team, from: t.from, to: t.to, tone: t.team === "도배" ? "b" : "a" }));
  return (
    <main id="main" className="mj-wrap mj-main">
      {isNew ? <p className="mj-notice" role="status"><b>프로젝트를 만들었어요.</b> 예상 공정표와 표준견적서가 준비됐어요.</p> : null}
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "flex-end", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">예상 공정표</h1>
          <p className="mj-sub mj-num">{md(s.start)} ~ {md(s.end)} · 일하는 날 {s.days.length}일 · {s.weekendNote}</p>
        </div>
        <GanttDownload title={`예상 공정표 · ${md(s.start)} ~ ${md(s.end)}`} days={s.days} rows={rows} filename="믿집-예상-공정표.png" />
      </div>
      <p className="mj-notice mj-notice-warn"><span><b>예상 일정이에요.</b> 표준 공정 순서와 공정별 예상 기간으로 믿집이 만들었어요. 실제 일정은 업체를 확정하고 업체가 공사기간을 등록하면 확정 공정표로 따로 보여 드려요.</span></p>

      <Gantt caption="작업별 예상 일정" days={s.days} rows={rows} />
      <div className="mj-legend"><span><i style={{ background: "var(--accent)" }} />목공 · 공통</span><span><i style={{ background: "var(--accent-pastel)" }} />도배</span><span><i style={{ background: "var(--gantt-off)" }} />휴무 (일요일 · 공휴일)</span></div>

      <div className="mj-split">
        <section className="mj-col mj-panel" aria-labelledby="why-h">
          <h2 id="why-h" className="mj-h3">이렇게 잡은 이유</h2>
          <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            {s.tasks.map((t) => <li key={t.k}><b>{t.label}</b> · {t.why}</li>)}
          </ul>
          <p className="mj-tiny">목공(몰딩 · 걸레받이)을 먼저 하고 도배를 해요. 순서를 바꾸면 벽지가 상해요.</p>
        </section>
        <section className="mj-aside mj-panel" aria-labelledby="todo-h">
          <h2 id="todo-h" className="mj-h3">참고사항 · 할 일</h2>
          <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 8 }}>
            {s.todos.map((t) => <li key={t.t}><span className="mj-num" style={{ fontWeight: 700 }}>{md(t.when)}</span> {t.who} · {t.t}<br /><span className="mj-small">{t.d}</span></li>)}
          </ol>
        </section>
      </div>
      <div className="mj-btn-row"><Link href={`/projects/${id}/standard`} className="mj-btn mj-btn-pri">다음 · 표준견적서 보기</Link></div>
      <p className="mj-tiny">믿집 에이전트가 만든 일정이에요. 날짜와 기간은 계산 엔진이 정하고, 에이전트는 순서와 참고사항을 정리했어요.</p>
    </main>
  );
}

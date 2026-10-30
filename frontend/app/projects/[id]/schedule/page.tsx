import Link from "next/link";
import { NotConnected } from "@/components/project/RealProjectHub";
import { isDemoProject } from "@/lib/api/project";
import { getConfirmedSchedule, getExpectedSchedule } from "@/lib/api/schedule";
import { listAllVendors } from "@/lib/api/vendor";
import { Gantt, type GanttRow } from "@/components/project/Gantt";
import { GanttDownload } from "@/components/project/GanttDownload";
import { TRADE_LABEL, type Trade } from "@/lib/types";
import { md } from "@/lib/format";

export const metadata = { title: "확정 공정표" };

export default async function SchedulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const [conf, exp, vendors] = await Promise.all([getConfirmedSchedule(id), getExpectedSchedule(id), listAllVendors()]);
  const name = (vid: string) => vendors.find((v) => v.id === vid)?.name ?? vid;
  const order: Trade[] = ["mokgong", "dobae"];
  const days = Array.from(new Set(order.flatMap((t) => conf[t].days))).sort();
  const rows: GanttRow[] = order.flatMap((t) => conf[t].tasks.map((k) => ({ label: k.label, sub: `${TRADE_LABEL[t]} · ${name(conf[t].vendorId)}`, from: k.from, to: k.to, tone: t === "dobae" ? ("b" as const) : ("a" as const) })));
  const first = conf.mokgong.start, last = conf.dobae.end;

  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "flex-end", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="mj-eyebrow">실제 공사 일정</span>
          <h1 className="mj-h1">확정 공정표</h1>
          <p className="mj-sub mj-num">{md(first)} ~ {md(last)} · 확정 업체가 등록한 공사기간으로 만들었어요</p>
        </div>
        <GanttDownload title={`확정 공정표 · ${md(first)} ~ ${md(last)}`} days={days} rows={rows} filename="믿집-확정-공정표.png" />
      </div>

      <div className="mj-table-box">
        <table className="mj-table">
          <caption>공정별 확정 업체 · 공사기간</caption>
          <thead><tr><th scope="col">공정</th><th scope="col">확정 업체</th><th scope="col">시작일</th><th scope="col">종료 예정일</th><th scope="col">일하는 날</th></tr></thead>
          <tbody>
            {order.map((t) => (
              <tr key={t}><th scope="row">{TRADE_LABEL[t]}</th><td>{name(conf[t].vendorId)}</td><td className="mj-num">{md(conf[t].start)}</td><td className="mj-num">{md(conf[t].end)}</td><td className="mj-num">{conf[t].days.length}일</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <Gantt caption="작업별 확정 일정" days={days} rows={rows} />
      <div className="mj-legend"><span><i style={{ background: "var(--accent)" }} />목공</span><span><i style={{ background: "var(--accent-pastel)" }} />도배</span><span><i style={{ background: "var(--gantt-off)" }} />휴무 (일요일 · 공휴일)</span></div>

      <div className="mj-split">
        <section className="mj-col mj-panel" aria-labelledby="dif-h">
          <h2 id="dif-h" className="mj-h3">예상 공정표와 비교</h2>
          <p className="mj-num">예상 {md(exp.start)} ~ {md(exp.end)} → 확정 {md(first)} ~ {md(last)}</p>
          <p className="mj-small">공사기간은 확정 업체가 고객과 합의해 등록하고, 바뀌면 업체가 고쳐요. 바뀌면 이 공정표에 바로 반영돼요.</p>
        </section>
        <section className="mj-aside mj-panel" aria-labelledby="nx-h">
          <h2 id="nx-h" className="mj-h3">공사 전에 할 일</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>{exp.todos.slice(0, 4).map((t) => <li key={t.t}>{t.t}</li>)}</ul>
          <Link href={`/projects/${id}/plan`}>예상 공정표 다시 보기</Link>
        </section>
      </div>
    </main>
  );
}

import { notFound } from "next/navigation";
import { SiteHeader } from "@/components/site/SiteHeader";
import { ProjectNav } from "@/components/project/ProjectNav";
import { getMyProject, getProject, isDemoProject } from "@/lib/api/project";
import { requireRole } from "@/lib/session";
import { STAGE_LABEL } from "@/lib/types";
import { sizeLabel } from "@/lib/labels";

export default async function ProjectLayout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  await requireRole("customer", `/projects/${id}`);

  let head: React.ReactNode;
  if (isDemoProject(id)) {
    const p = await getProject(id);
    if (!p) notFound();
    head = (
      <>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 14px" }}>
          <span className="mj-h3">{p.title}</span>
          <span className="mj-badge">예시</span>
          <span className="mj-small">{p.complex.sgg} {p.complex.dong} · 공급 {p.area.supply}㎡ / 전용 {p.area.jeon}㎡</span>
          <span className="mj-badge mj-b-in">{STAGE_LABEL[p.stage]}</span>
        </div>
        <ProjectNav id={p.id} stage={p.stage} />
      </>
    );
  } else {
    const p = await getMyProject(id);
    if (!p) notFound();
    head = (
      <>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 14px" }}>
          <span className="mj-h3">{p.region} · {sizeLabel(p.size)}</span>
        </div>
        {/* 예상 공정표 · 표준견적서 탭은 상담으로 잇는 안내를 보인다 */}
        <ProjectNav id={p.id} stage="draft" ready={false} live={["plan", "standard", "vendors"]} />
      </>
    );
  }

  return (
    <>
      <SiteHeader />
      <div style={{ background: "var(--bg)", borderBottom: "1px solid var(--line)" }}>
        <div className="mj-wrap" style={{ paddingBlock: 16, display: "flex", flexDirection: "column", gap: 12 }}>{head}</div>
      </div>
      {children}
    </>
  );
}

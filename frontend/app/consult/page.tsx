import { ConsultChat } from "@/components/consult/ConsultChat";
import { requireRole } from "@/lib/session";

export const metadata = { title: "도배 상담" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ConsultPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const { project } = await searchParams;
  const projectId = project && UUID.test(project) ? project : null;
  await requireRole("customer", projectId ? `/consult?project=${projectId}` : "/consult");
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="mj-eyebrow">도배 상담</span>
        <h1 className="mj-h1">우리 집 도배, 물어보면서 정해요</h1>
        <p className="mj-sub">몇 가지만 답하면 공공 기준으로 계산한 표준견적서와 도배 전문가 의견을 보여 드려요.</p>
      </div>
      <ConsultChat projectId={projectId} />
    </main>
  );
}

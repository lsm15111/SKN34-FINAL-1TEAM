// 실측 일정 요청서(C13 req · D08 d_req). 담은 업체(3곳까지)에 희망 기간 · 사진을 같이 보내요.
// 희망 기간 초안 · 가견적은 GET /projects/{id}/visits/draft(계산 엔진) 값이에요. 보낼 업체가 없으면 업체 보기로 길을 줘요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { AiSlot } from "@/components/visit/AiSlot";
import { RequestForm } from "@/components/visit/RequestForm";
import { getVisitDraft, getVisitProject, visitToday } from "@/lib/api/visit";

export const metadata = { title: "실측 일정 요청" };

export default async function VisitRequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [draft, project, today] = await Promise.all([getVisitDraft(id), getVisitProject(id), visitToday()]);
  if (!draft || !project) notFound();
  const pid = encodeURIComponent(project.id);
  const header = <AppHeader only="phone" phone={{ title: "실측 일정 요청", back: `/projects/${pid}/vendors`, action: <AsideOpenButton /> }} />;
  if (!draft.vendors.length) {
    return (
      <>
        {header}
        <Main>
          <PageHead title="실측 일정 요청" crumbs={[{ label: "내 공사", href: "/my" }, { label: project.name, href: `/projects/${pid}` }, { label: "실측 일정 요청" }]} />
          <EmptyState icon="store" title="실측을 요청할 업체를 먼저 담아요" action={<Button variant="text" arrow href={`/projects/${pid}/vendors`}>업체 보기</Button>}>가견적을 비교하고 3곳까지 담을 수 있어요</EmptyState>
        </Main>
      </>
    );
  }
  return (
    <>
      {header}
      <RequestForm projectId={project.id} projectName={project.name} draft={draft} today={today} aside={<AiSlot screen="visit_request" projectId={project.id} />} />
    </>
  );
}

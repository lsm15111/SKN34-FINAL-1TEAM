// 실측 일정 요청서(C13 req · D08 d_req). 담은 업체(3곳까지)에 희망 기간 · 사진을 같이 보내요.
// 희망 기간 초안 · 가견적은 GET /projects/{id}/visits/draft(계산 엔진) 값이에요.
// 보낼 업체가 없으면 단계에 맞는 한 곳으로 길을 줘요(QA r6 M5): 업체를 확정했으면 다음 할 일 · 담은 업체에 모두 요청했으면
// 실측 일정 · 아무도 안 담았으면 업체 보기. 업체 보기 담기 띠와 같은 기준(담은 업체의 요청 상태)이라 서로를 가리키며 돌지 않아요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { AiSlot } from "@/components/visit/AiSlot";
import { RequestForm } from "@/components/visit/RequestForm";
import { getProjectShell } from "@/lib/api/project";
import { getShortlist } from "@/lib/api/shortlist";
import { getVisitDraft, getVisitProject, visitToday } from "@/lib/api/visit";
import { euro } from "@/lib/format";
import { ASKED_VISIT } from "@/lib/labels";

export const metadata = { title: "실측 일정 요청" };

export default async function VisitRequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [draft, project, today] = await Promise.all([getVisitDraft(id), getVisitProject(id), visitToday()]);
  if (!draft || !project) notFound();
  const pid = encodeURIComponent(project.id);
  const header = <AppHeader only="phone" phone={{ title: "실측 일정 요청", back: `/projects/${pid}/vendors`, action: <AsideOpenButton /> }} />;
  if (!draft.vendors.length) {
    const [shortlist, shell] = await Promise.all([getShortlist(project.id).catch(() => null), getProjectShell(project.id)]);
    const items = shortlist?.items ?? [];
    const chosen = items.find((it) => it.visit_status === "chosen");
    const todo = shell?.todo.find((t) => t.href);
    const empty = chosen
      ? { title: `${euro(chosen.name)} 확정했어요`, label: todo?.label ?? "공사 날짜 보기", href: todo?.href ?? `/projects/${pid}/schedule`, body: null }
      : items.some((it) => it.visit_status != null && ASKED_VISIT.has(it.visit_status))
        ? { title: "담은 업체에 모두 요청했어요", label: "실측 일정 보기", href: `/projects/${pid}/visits`, body: null }
        : { title: "실측을 요청할 업체를 먼저 담아요", label: "업체 보기", href: `/projects/${pid}/vendors`, body: "가견적을 비교하고 3곳까지 담을 수 있어요" };
    return (
      <>
        {header}
        <Main>
          <PageHead title="실측 일정 요청" crumbs={[{ label: "내 공사", href: "/my" }, { label: project.name, href: `/projects/${pid}` }, { label: "실측 일정 요청" }]} />
          <EmptyState icon="store" title={empty.title} action={<Button href={empty.href}>{empty.label}</Button>}>{empty.body}</EmptyState>
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

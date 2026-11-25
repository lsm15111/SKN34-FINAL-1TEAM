// 날짜 고르기 · 확정(C16 pick_on · C61 pick_ok · C17 done · C19 pick_off · C21 pick_prop · C22 nooverlap · D15 · D16 · D17).
// 알림 · 메일 링크가 이 주소로 와요(routes.md). 남의 요청 · 없는 요청은 404(C56).
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { AiSlot } from "@/components/visit/AiSlot";
import { PickBoard } from "@/components/visit/PickBoard";
import { pickTitle } from "@/components/visit/text";
import { getVisitPick, getVisitProject, visitToday } from "@/lib/api/visit";

export const metadata = { title: "실측 날짜 고르기" };

export default async function VisitPickPage({ params }: { params: Promise<{ id: string; visitId: string }> }) {
  const { id, visitId } = await params;
  const [pick, project, today] = await Promise.all([getVisitPick(id, visitId), getVisitProject(id), visitToday()]);
  if (!pick || !project) notFound();
  return (
    <>
      <AppHeader only="phone" phone={{ title: pickTitle(pick), back: `/projects/${encodeURIComponent(project.id)}/visits` }} />
      <PickBoard pick={pick} project={project} today={today} aside={<AiSlot screen="pick" projectId={project.id} ids={[pick.visit_id]} />} />
    </>
  );
}

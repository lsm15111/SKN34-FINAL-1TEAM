// 내 공사 한 건(/projects/{id}/**). 고객만 보고, 없거나 남의 공사면 404(C56, 있는지조차 알리지 않아요).
// 웹 머리 + 위쪽 공사 띠(W1 A · 6단계 · 지금 할 일)는 여기 한 곳에서 그려요. 폰 머리(‹ 제목 · 오른쪽 단추)는 화면마다
// <AppHeader only="phone" phone={{ … }} />로 그려요(ui-components 1장). 옆 AI 칸은 화면마다 WithAside에 둬요(dev-08).
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { ProjectBand } from "@/components/site/ProjectBand";
import { AFTER_VISIT_STEPS, PROJECT_STEPS } from "@/components/ui/Steps";
import { getProjectShell, stepLinks } from "@/lib/api/project";
import { mockKeyOf } from "@/lib/mock/v3a/mode";
import { currentPath, requireRole } from "@/lib/session";

export default async function ProjectLayout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  // 로그인 뒤 돌아갈 곳은 처음 들어온 주소(proxy 머리 x-mj-path, 예: /projects/{id}/vendors/{vid}). 머리가 없으면 공사 요약
  if (!mockKeyOf(id)) await requireRole("customer", await currentPath(`/projects/${encodeURIComponent(id)}`));
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const links = stepLinks(shell.id);
  const steps = PROJECT_STEPS.map((st, i) => ({ ...st, href: links[i] }));
  return (
    <>
      <AppHeader only="web" />
      <ProjectBand
        name={shell.name}
        href={`/projects/${shell.id}`}
        steps={steps}
        current={shell.current}
        sub={shell.current === 5 && shell.sub != null ? { steps: AFTER_VISIT_STEPS, current: shell.sub } : undefined}
        todo={shell.todo}
        waiting={shell.waiting}
      />
      {children}
    </>
  );
}

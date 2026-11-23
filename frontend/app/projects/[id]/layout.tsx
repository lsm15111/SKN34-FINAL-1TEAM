// 내 공사 한 건(/projects/{id}/**). 고객만 보고, 없거나 남의 공사면 404(C56, 있는지조차 알리지 않아요).
// 겉모양 스위치(components/assistant/mode): v4면 비서 대화 한 화면(Shell)을 그리고, 아래 경로 화면은 카드 자리에 들어와요.
// v3면 웹 머리 + 위쪽 공사 띠(W1 A · 6단계 · 지금 할 일)를 여기 한 곳에서 그려요. 폰 머리(‹ 제목 · 오른쪽 단추)는 화면마다
// <AppHeader only="phone" phone={{ … }} />로 그려요(ui-components 1장). 옆 AI 칸은 화면마다 WithAside에 둬요(dev-08).
import { notFound } from "next/navigation";
import { Shell } from "@/components/assistant/Shell";
import { UI_SWITCH_BAR, uiMode } from "@/components/assistant/mode";
import { UiSwitchBar } from "@/components/assistant/UiSwitch";
import { AppHeader } from "@/components/site/AppHeader";
import { ProjectBand } from "@/components/site/ProjectBand";
import { getShellData } from "@/components/site/who";
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
  if ((await uiMode()) === "v4") {
    const { session, unread } = await getShellData();
    // 비서 글의 '고객님'을 그릴 때만 이 이름으로 바꿔요(이름은 LLM에 보내지 않아요). locked: 처음 연 때 집 정보 잠김(실측 요청 뒤).
    // 웹 머리는 다른 화면과 같은 사이트 공통 머리예요(2026-11-23 사용자: 채팅에서 머리가 바뀌었어요). 폰은 비서 머리(‹ 공사 이름)
    return (
      <Shell projectId={shell.id} name={shell.name} me={session?.name ?? null} unread={unread} locked={shell.locked} siteHeader={<AppHeader only="web" />}>
        {children}
      </Shell>
    );
  }
  const links = stepLinks(shell.id);
  const steps = PROJECT_STEPS.map((st, i) => ({ ...st, href: links[i] }));
  return (
    <>
      {UI_SWITCH_BAR ? <UiSwitchBar /> : null}
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

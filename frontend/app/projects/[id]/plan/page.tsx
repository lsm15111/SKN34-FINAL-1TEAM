// /projects/{id}/plan — 공정표. 수락한 공사 날짜가 있으면 확정 공정표(C36 폰 · D19 웹), 없으면 예상 공정표(C08).
// 날짜 · 일수 · 인원 · 금액은 모두 API(계산 엔진) 값이에요. 화면은 나누거나 올리지 않아요.
// v4(비서 화면 카드 창)에서는 확정 공정표 옆 칸에 AI 채팅을 따로 두지 않아요(비서가 옆에 있어요).
// 예상 공정표 아래 단추는 공사 '지금 할 일'(단계마다 다름, 없으면 업체 보기)이에요.
import { notFound } from "next/navigation";
import { uiMode } from "@/components/assistant/mode";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { ExpectedPlan } from "@/components/plan/ExpectedPlan";
import { FinalPlanAside, FinalPlanBody, finalHead } from "@/components/plan/FinalPlanView";
import { Badge } from "@/components/ui/Badge";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { HelpTip } from "@/components/ui/HelpTip";
import { getChecks, getPlanView, getProjectShell } from "@/lib/api/project";

export const metadata = { title: "공정표" };

export default async function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const plan = await getPlanView(shell.id);
  if (!plan) notFound();
  const base = `/projects/${shell.id}`;
  const crumbs = (here: string) => [{ label: "내 공사", href: "/my" }, { label: shell.name, href: base }, { label: here }];

  if (plan.kind === "final") {
    const [checks, ui] = await Promise.all([getChecks(shell.id), uiMode()]);
    const h = finalHead(plan);
    return (
      <>
        <AppHeader only="phone" phone={{ title: "확정 공정표", back: base }} />
        <Main>
          <PageHead title="확정 공정표" crumbs={crumbs("확정 공정표")} desc={<span className="mj-num">{h.made}</span>} badge={<Badge tone="ok">{h.badge}</Badge>} />
          <WithAside label="공사 전 할 일" aside={<FinalPlanAside plan={plan} projectId={shell.id} checks={checks} mock={shell.mock} ai={ui !== "v4"} />}>
            <FinalPlanBody plan={plan} projectId={shell.id} checks={checks} mock={shell.mock} />
          </WithAside>
        </Main>
      </>
    );
  }

  const todo = shell.todo.find((t) => t.href);
  return (
    <>
      <AppHeader only="phone" phone={{ title: "예상 공정표", back: `${base}/standard` }} />
      <Main narrow>
        <PageHead title="예상 공정표" crumbs={crumbs("예상 공정표")}
          badge={<HelpTip only="web" label="확정 공정표 안내">확정 공정표는 업체를 확정하고 공사 날짜를 수락하면 만들어져요.</HelpTip>} />
        <ExpectedPlan plan={plan} />
      </Main>
      <BottomBar>
        <Button size="lg" href={todo?.href ?? `${base}/vendors`}>{todo?.label ?? "업체 보기"}</Button>
      </BottomBar>
    </>
  );
}

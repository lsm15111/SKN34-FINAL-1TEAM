// /projects/{id}/standard — 내 공사 표준견적서(C07 · C60 부분 공사 · D01 + 옆 AI 칸).
// 폰은 머리 'AI 채팅'으로 전체 화면 AI를 열어요(C09). 공급가 · 부가세를 나눠 보이는 곳은 이 합계 칸 하나예요.
// '조건 바꾸기'는 기본 정보 고치기(/start?edit=, 첫 요청 뒤에는 잠긴 화면 C50이라 이름도 '집 정보 보기')로 가요.
// 아래 주 단추는 공사 '지금 할 일'(없으면 업체 보기). 숫자는 모두 계산 엔진 값이에요.
import { notFound } from "next/navigation";
import { AiPanel } from "@/components/ai/AiPanel";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { StandardSheet } from "@/components/start/StandardSheet";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { getProjectShell } from "@/lib/api/project";
import { getStandardView } from "@/lib/api/quote";

export const metadata = { title: "표준견적서" };

export default async function StandardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const view = await getStandardView(shell);
  if (!view) notFound();
  const base = `/projects/${shell.id}`;
  const todo = shell.todo.find((t) => t.href);
  return (
    <>
      <AppHeader only="phone" phone={{ title: "표준견적서", back: base, action: <AsideOpenButton /> }} />
      <Main>
        <PageHead title="표준견적서" crumbs={[{ label: "내 공사", href: "/my" }, { label: shell.name, href: base }, { label: "표준견적서" }]} />
        <WithAside aside={<AiPanel screen="standard" projectId={shell.id} />}>
          <StandardSheet view={view} changeHref={`/start?edit=${shell.id}`} changeLabel={shell.locked ? "집 정보 보기" : undefined} />
        </WithAside>
      </Main>
      <BottomBar>
        {view.scope === "partial" ? null : <Button variant="secondary" size="lg" href={`${base}/plan`}>예상 공정표</Button>}
        <Button size="lg" href={todo?.href ?? `${base}/vendors`}>{todo?.label ?? "업체 보기"}</Button>
      </BottomBar>
    </>
  );
}

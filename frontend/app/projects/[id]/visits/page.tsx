// 실측 일정 상태판(C14 board1 · C15 reqview · C18 board_exp · C20 board_prop · C32 visited · D03 d_visit).
// 업체 답 기한(보낸 때 + 48시간) · 고르기 기한(업체 답 + 7일) · 지남은 계산 엔진 값(api.md 5장)을 그대로 보여요.
// 웹 머리 · 공사 띠는 레이아웃(B2a), 폰 머리 · 본문 · 옆 AI 칸은 이 화면이 그려요(ui-components 1장).
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { AiSlot } from "@/components/visit/AiSlot";
import { Board } from "@/components/visit/Board";
import { BoardLive } from "@/components/visit/BoardActions";
import { getShortlist } from "@/lib/api/shortlist";
import { getVisitBoard, getVisitProject } from "@/lib/api/visit";

export const metadata = { title: "실측 일정" };

export default async function VisitsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [board, project] = await Promise.all([getVisitBoard(id), getVisitProject(id)]);
  if (!board || !project) notFound();
  const home = `/projects/${encodeURIComponent(project.id)}`;
  // 요청 전 상태판은 담은 업체 수(담기 표)로 '요청할 차례' · '먼저 담아요'를 갈라요(slots_left는 요청만 세요)
  const short = !board.head || !board.board.length ? await getShortlist(project.id).catch(() => null) : null;
  return (
    <>
      <AppHeader only="phone" phone={{ title: "실측 일정", back: home, action: <AsideOpenButton /> }} />
      <Main>
        <PageHead title="실측 일정" crumbs={[{ label: "내 공사", href: "/my" }, { label: project.name, href: home }, { label: "실측 일정" }]} />
        <WithAside aside={<AiSlot screen="visits" projectId={project.id} />}>
          <Board board={board} project={project} shortlisted={short?.count ?? null} />
        </WithAside>
      </Main>
      <BoardLive projectId={project.id} />
    </>
  );
}

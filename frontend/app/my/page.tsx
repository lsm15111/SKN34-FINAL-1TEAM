// /my — 내 공사(C42 폰 · D09 웹 2열). 고객만. 서버가 최근에 바뀐 순으로 준 공사를 카드 하나씩 보여요.
// 카드: 공사 이름 · 면적 · 벽지 · 마지막 소식 · 6단계 · 지금 할 일 · [할 일 단추] + 업체 상태 꼬리표. 이 고객 소식이 오면 다시 읽어요.
// 알림은 머리 종(웹 · 모두 읽음 · 모두 보기)과 알림 화면(/notifications)에서 봐요. 이 화면에는 알림 칸을 두지 않아요.
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { TabBar } from "@/components/site/TabBar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProjectCards, type MyCard } from "@/components/my/ProjectCards";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { listMyProjectsV3 } from "@/lib/api/schedule";
import { getVisitBoard } from "@/lib/api/visit";
import { projectName } from "@/lib/guest/info";
import { requireRoleV3b as requireRole } from "@/lib/mock/v3b/session";

export const metadata = { title: "내 공사" };

export default async function MyPage() {
  await requireRole("customer", "/my");
  const mine = await listMyProjectsV3();
  const cards: MyCard[] = await Promise.all(
    mine.map(async (p) => {
      // 상태판은 실측 확정 업체가 있을 때만 읽어요(실측 시각이 지났으면 꼬리표가 '실측 시각 지남')
      const booked = p.vendors.find((v) => v.status === "booked");
      const board = booked ? await getVisitBoard(p.id, booked.trade === "mokgong" ? "mokgong" : "dobae").catch(() => null) : null;
      return { p, name: projectName(p.emd, p.region, p.trades), rows: board?.board ?? null };
    }),
  );

  return (
    <>
      <AppHeader phone={{ title: "내 공사" }} />
      <Main>
        <PageHead
          title="내 공사"
          desc={mine.length ? `${mine.length}건 · 최근에 바뀐 순서` : undefined}
          action={mine.length ? <Button variant="text" arrow href="/start">인테리어 새로 받기</Button> : undefined}
        />
        {cards.length ? (
          <ProjectCards items={cards} />
        ) : (
          <EmptyState icon="home" title="아직 만든 공사가 없어요" action={<Button href="/start">인테리어 받기</Button>}>
            집 정보와 공정을 넣으면 표준견적서와 예상 공정표를 받아요
          </EmptyState>
        )}
      </Main>
      <TabBar />
      <LiveRefresh />
    </>
  );
}

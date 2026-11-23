// /my — 내 공사(C42 폰 · D09 웹 2열). 고객만. 서버가 최근에 바뀐 순으로 준 공사를 카드 하나씩 보여요.
// 카드: 공사 이름 · 면적 · 벽지 · 마지막 소식 · 6단계 · 지금 할 일 · 업체 줄(실측 일정 상태판 값). 이 고객 소식이 오면 다시 읽어요.
// 웹(≥1024)은 오른쪽 열에 최근 알림 5개 · 모두 읽음(D09). 폰 · 태블릿은 알림 탭에서 봐요.
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { TabBar } from "@/components/site/TabBar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProjectCards, type MyCard } from "@/components/my/ProjectCards";
import { NotifyFeed, ReadAllAction, type FeedItem } from "@/components/notify/NotifyFeed";
import { listNotifications } from "@/lib/api/notify";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { listMyProjectsV3 } from "@/lib/api/schedule";
import { getVisitBoard } from "@/lib/api/visit";
import { projectName } from "@/lib/guest/info";
import { requireRoleV3b as requireRole } from "@/lib/mock/v3b/session";
import m from "@/components/my/myPage.module.css";

export const metadata = { title: "내 공사" };

export default async function MyPage() {
  await requireRole("customer", "/my");
  const [mine, notes] = await Promise.all([listMyProjectsV3(), listNotifications().catch(() => null)]);
  const names = new Map(mine.map((p) => [p.id, projectName(p.emd, p.region, p.trades)]));
  const feed: FeedItem[] = (notes?.items ?? []).slice(0, 5).map((n) => ({
    id: n.id, body: n.body, link: n.link, at: n.created_at, read: n.read,
    sub: n.project_id ? names.get(n.project_id) : undefined,
  }));
  const cards: MyCard[] = await Promise.all(
    mine.map(async (p) => {
      const trade = p.vendors[0]?.trade === "mokgong" ? "mokgong" : "dobae";
      const board = p.vendors.length ? await getVisitBoard(p.id, trade).catch(() => null) : null;
      return { p, name: names.get(p.id) ?? projectName(p.emd, p.region, p.trades), rows: board?.board ?? null };
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
        <div className={m.cols}>
          <div className={m.main}>
            {cards.length ? (
              <ProjectCards items={cards} />
            ) : (
              <EmptyState icon="home" title="아직 만든 공사가 없어요" action={<Button href="/start">인테리어 받기</Button>}>
                집 정보와 공정을 넣으면 표준견적서와 예상 공정표를 받아요
              </EmptyState>
            )}
          </div>
          {feed.length && notes ? (
            <aside className={m.side} aria-labelledby="my-notif">
              <div className={m.sideHead}>
                <h2 id="my-notif" className={m.sideTitle}>알림</h2>
                {notes.unread ? <ReadAllAction /> : null}
              </div>
              <NotifyFeed items={feed} unread={notes.unread} />
            </aside>
          ) : null}
        </div>
      </Main>
      <TabBar />
      <LiveRefresh />
    </>
  );
}

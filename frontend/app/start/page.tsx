// /start — 기본 정보(C02 · C03 · D11). ?edit={id}면 그 공사를 고쳐요(만든 고객만, 남의 것은 404). 첫 실측 요청 뒤면 잠김(C50).
// 손님은 답을 이 기기에 두고 가입 없이 표준견적서로 가요(N1 A). 로그인한 고객은 같은 답으로 내 공사를 만들어요.
// v4(겉모양 스위치): 새로 시작은 첫 대화(StartChat: 주소 · 단지 이름 → 집 정보 확인 카드 → 표준견적서 → 직접 할 일). 고치기(?edit=)는 v3 화면 그대로예요.
import { notFound } from "next/navigation";
import { uiMode } from "@/components/assistant/mode";
import { StartChat } from "@/components/assistant/start/StartChat";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { InfoForm } from "@/components/start/InfoForm";
import { InfoLocked } from "@/components/start/InfoLocked";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { getDiy, getMyProject, getProjectShell, getRegions, getRoomRule, getStartWishes } from "@/lib/api/project";
import { todaySeoul } from "@/lib/format";
import { EMPTY_DRAFT, draftOfProject, fromSaved, placeText, roomsOf } from "@/lib/guest/info";
import { MOCK_V3A, mockKeyOf } from "@/lib/mock/v3a/mode";
import { getSession, requireRole } from "@/lib/session";

export const metadata = { title: "기본 정보" };

export default async function StartPage({ searchParams }: { searchParams: Promise<{ edit?: string }> }) {
  const { edit } = await searchParams;
  const today = todaySeoul();
  const [session, regions, roomRule] = await Promise.all([getSession(), getRegions(), getRoomRule()]);

  if (edit) {
    if (!mockKeyOf(edit)) await requireRole("customer", `/start?edit=${encodeURIComponent(edit)}`);
    const [shell, diy] = await Promise.all([getProjectShell(edit), getDiy(edit)]);
    if (!shell) notFound();
    const p = shell.mock ? null : await getMyProject(edit);
    // 직접 할 일은 기본 정보에 없어서 모은 조건에서 따로 읽어요(고치기 칸 · 잠긴 뒤 고치기)
    const draft = { ...(shell.home ? fromSaved(shell.home) : p ? draftOfProject(p) : EMPTY_DRAFT), diy };
    const crumbs = [{ label: "내 공사", href: "/my" }, { label: shell.name, href: `/projects/${shell.id}` }, { label: "기본 정보" }];
    if (shell.locked) {
      return (
        <>
          <AppHeader phone={{ title: "기본 정보", back: `/projects/${shell.id}` }} />
          <Main narrow>
            <PageHead title="기본 정보" crumbs={crumbs} />
            <InfoLocked draft={draft} region={placeText(regions, draft)} today={today} rooms={roomsOf(draft, roomRule)} diy={{ projectId: shell.id, mock: shell.mock }} />
          </Main>
          <BottomBar>
            <Button variant="secondary" size="lg" href="/start">다른 조건으로 새로 받기</Button>
          </BottomBar>
        </>
      );
    }
    return (
      <>
        <AppHeader phone={{ title: "기본 정보", back: `/projects/${shell.id}/standard` }} />
        <InfoForm key={shell.id} regions={regions} roomRule={roomRule} today={today} mode="edit" projectId={shell.id} initial={draft} mock={shell.mock} crumbs={crumbs} />
      </>
    );
  }

  if ((await uiMode()) === "v4") {
    const wishes = await getStartWishes();
    return <StartChat regions={regions} roomRule={roomRule} wishes={wishes} today={today} mode={session?.role === "customer" ? "member" : "guest"} mock={MOCK_V3A} />;
  }
  return (
    <>
      <AppHeader phone={{ title: "기본 정보", back: "/" }} />
      <InfoForm regions={regions} roomRule={roomRule} today={today} mode={session?.role === "customer" ? "member" : "guest"} mock={MOCK_V3A}
        crumbs={[{ label: "인테리어 받기", href: "/start" }, { label: "기본 정보" }]} />
    </>
  );
}

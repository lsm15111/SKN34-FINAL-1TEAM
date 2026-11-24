// /start — 기본 정보(C02 · C03 · D11). ?edit={id}면 그 공사를 고쳐요(만든 고객만, 남의 것은 404). 첫 실측 요청 뒤면 잠김(C50).
// 손님은 답을 이 기기에 두고 가입 없이 표준견적서로 가요(N1 A). 로그인한 고객은 같은 답으로 내 공사를 만들어요.
// v4(겉모양 스위치): 새로 시작은 첫 대화(StartChat: 우리 집 → 원하는 공사 → 표준견적서, [다음]으로 한 걸음씩). 고치기(?edit=)는 v3 화면 그대로예요.
//   머리는 다른 화면과 같은 사이트 머리(웹 메뉴 · 폰 ‹)를 여기서 그려 넘겨요(2026-11-24 사용자: 백과 같은 곳으로 갈 수 있게).
//   칸 옆 '?'의 풀이는 백과 용어 사전 글이고, '자세히'는 ?term=으로 이 화면 위에 용어 칸을 열어요(OpenTerm).
import Link from "next/link";
import { notFound } from "next/navigation";
import { uiMode } from "@/components/assistant/mode";
import { StartChat } from "@/components/assistant/start/StartChat";
import type { StartTip } from "@/components/assistant/start/TermHelp";
import t from "@/components/assistant/start/start.module.css";
import { OpenTerm } from "@/components/guide/TermDetail";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { InfoForm } from "@/components/start/InfoForm";
import { InfoLocked } from "@/components/start/InfoLocked";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { getDiy, getMyProject, getProjectShell, getRegions, getRoomRule, getStartWishes } from "@/lib/api/project";
import { todaySeoul } from "@/lib/format";
import { EMPTY_DRAFT, draftOfProject, fromSaved, placeText, roomsOf } from "@/lib/guest/info";
import { termById } from "@/lib/guide";
import { MOCK_V3A, mockKeyOf } from "@/lib/mock/v3a/mode";
import { getSession, requireRole } from "@/lib/session";

export const metadata = { title: "기본 정보" };

/** 첫 대화 칸 옆 '?' 풀이(백과 용어 사전 글): 면적은 쉬운 말, 벽지는 고르는 법. 사전에 없는 용어는 빼요 */
function tipsOf(ids: string[], pick: "easy" | "tip"): StartTip[] {
  return ids.flatMap((id) => {
    const x = termById(id);
    return x ? [{ id: x.id, term: x.term, text: x[pick] }] : [];
  });
}

export default async function StartPage({ searchParams }: { searchParams: Promise<{ edit?: string; term?: string }> }) {
  const { edit, term } = await searchParams;
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
    const member = session?.role === "customer";
    const tips = { area: tipsOf(["공급면적", "전용면적"], "easy"), grade: tipsOf(["실크-벽지", "합지"], "tip") };
    // 폰 머리 오른쪽: 손님은 로그인(돌아올 곳 /start), 고객은 내 공사. 웹은 사이트 머리 메뉴 · 로그인 · 이름 ▾ 그대로예요
    const action = member
      ? <Link className={t.headLink} href="/my">내 공사</Link>
      : <Link className={t.headLink} href="/login?next=%2Fstart">로그인</Link>;
    return (
      <>
        <StartChat regions={regions} roomRule={roomRule} wishes={wishes} today={today} mode={member ? "member" : "guest"} mock={MOCK_V3A} tips={tips}
          siteHeader={<AppHeader phone={{ title: "새 공사 시작", back: "/", action }} />} />
        <OpenTerm id={term} />
      </>
    );
  }
  return (
    <>
      <AppHeader phone={{ title: "기본 정보", back: "/" }} />
      <InfoForm regions={regions} roomRule={roomRule} today={today} mode={session?.role === "customer" ? "member" : "guest"} mock={MOCK_V3A}
        crumbs={[{ label: "인테리어 받기", href: "/start" }, { label: "기본 정보" }]} />
    </>
  );
}

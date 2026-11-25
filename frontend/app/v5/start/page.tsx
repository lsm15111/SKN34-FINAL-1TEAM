// /v5/start — 인테리어 받기. 새로 시작은 첫 대화(StartChat: 우리 집 → 원하는 공사 → 표준견적서, [다음]으로 한 걸음씩)예요.
// 손님은 답을 이 기기에 두고 가입 없이 표준견적서로 가요(N1 A). 로그인한 고객은 같은 답으로 내 공사를 만들어요.
// ?edit={id}면 그 공사 기본 정보를 고쳐요(C02 · C03 · D11 InfoForm, 만든 고객만, 남의 것은 404). 첫 실측 요청 뒤면 잠김(C50).
//   첫 대화 머리는 다른 화면과 같은 사이트 머리(웹 메뉴 · 폰 ‹)를 여기서 그려 넘겨요(2026-11-24 사용자: 백과 같은 곳으로 갈 수 있게).
//   칸 옆 '?'의 풀이는 백과 용어 사전 글이고, '자세히'는 ?term=으로 이 화면 위에 용어 칸을 열어요(OpenTerm).
// v5: 기능 확인(getCaps)이 꺼져 있으면(dev 백엔드) 방 개수 · 철거 범위 · 직접 할 일을 묻지 않아요.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { OpenTerm } from "@/components/v5/guide/TermDetail";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { InfoForm } from "@/components/v5/start/InfoForm";
import { InfoLocked } from "@/components/v5/start/InfoLocked";
import { StartChat } from "@/components/v5/start/StartChat";
import type { StartTip } from "@/components/v5/start/TermHelp";
import t from "@/components/v5/start/start.module.css";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { getDiy, getMyProject, getProjectShell, getRegions, getRoomRule, getStartWishes } from "@/lib/v5/api/project";
import { todaySeoul } from "@/lib/v5/format";
import { EMPTY_DRAFT, draftOfProject, fromSaved, placeText, roomsOf } from "@/lib/v5/guest/info";
import { termById } from "@/lib/guide";
import { MOCK_V3A, mockKeyOf } from "@/lib/mock/v3a/mode";
import { getSession, requireRole } from "@/lib/session";
import { getCaps } from "@/lib/v5/caps";

/** 탭 제목: 새로 시작은 사이트 메뉴 이름 '인테리어 받기'(QA r9 U5), 고치기는 화면 제목 '기본 정보' */
export async function generateMetadata({ searchParams }: { searchParams: Promise<{ edit?: string }> }): Promise<Metadata> {
  const { edit } = await searchParams;
  return { title: edit ? "기본 정보" : "인테리어 받기" };
}

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
  const [session, regions, roomRule, { v4 }] = await Promise.all([getSession(), getRegions(), getRoomRule(), getCaps()]);
  const caps = { v4 };

  if (edit) {
    if (!mockKeyOf(edit)) await requireRole("customer", `/v5/start?edit=${encodeURIComponent(edit)}`);
    const [shell, diy] = await Promise.all([getProjectShell(edit), getDiy(edit)]);
    if (!shell) notFound();
    const p = shell.mock ? null : await getMyProject(edit);
    // 직접 할 일은 기본 정보에 없어서 모은 조건에서 따로 읽어요(고치기 칸 · 잠긴 뒤 고치기)
    const draft = { ...(shell.home ? fromSaved(shell.home) : p ? draftOfProject(p) : EMPTY_DRAFT), diy };
    const crumbs = [{ label: "내 공사", href: "/v5/my" }, { label: shell.name, href: `/v5/projects/${shell.id}` }, { label: "기본 정보" }];
    if (shell.locked) {
      return (
        <>
          <AppHeader phone={{ title: "기본 정보", back: `/v5/projects/${shell.id}` }} />
          <Main narrow>
            <PageHead title="기본 정보" crumbs={crumbs} />
            <InfoLocked draft={draft} region={placeText(regions, draft)} today={today} rooms={v4 ? roomsOf(draft, roomRule) : undefined} diy={{ projectId: shell.id, mock: shell.mock }} caps={caps} />
          </Main>
          <BottomBar>
            <Button variant="secondary" size="lg" href="/v5/start">다른 조건으로 새로 받기</Button>
          </BottomBar>
        </>
      );
    }
    return (
      <>
        <AppHeader phone={{ title: "기본 정보", back: `/v5/projects/${shell.id}/standard` }} />
        <InfoForm key={shell.id} regions={regions} roomRule={roomRule} today={today} mode="edit" projectId={shell.id} initial={draft} mock={shell.mock} crumbs={crumbs} caps={caps} />
      </>
    );
  }

  const wishes = await getStartWishes();
  const member = session?.role === "customer";
  const tips = { area: tipsOf(["공급면적", "전용면적"], "easy"), grade: tipsOf(["실크-벽지", "합지"], "tip") };
  // 폰 머리 오른쪽: 손님은 로그인(돌아올 곳 /start), 고객은 내 공사. 웹은 사이트 머리 메뉴 · 로그인 · 이름 ▾ 그대로예요
  const action = member
    ? <Link className={t.headLink} href="/v5/my">내 공사</Link>
    : <Link className={t.headLink} href="/login?next=%2Fv5%2Fstart">로그인</Link>;
  return (
    <>
      <StartChat regions={regions} roomRule={roomRule} wishes={wishes} today={today} mode={member ? "member" : "guest"} mock={MOCK_V3A} tips={tips} caps={caps}
        siteHeader={<AppHeader phone={{ title: "새 공사 시작", back: "/v5", action }} />} />
      <OpenTerm id={term} />
    </>
  );
}

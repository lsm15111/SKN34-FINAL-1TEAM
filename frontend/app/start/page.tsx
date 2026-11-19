// /start — 도배 기본 정보(C02 · C03 · D11). ?edit={id}면 그 공사를 고쳐요(만든 고객만, 남의 것은 404). 첫 실측 요청 뒤면 잠김(C50).
// 손님은 답을 이 기기에 두고 가입 없이 표준견적서로 가요(N1 A). 로그인한 고객은 같은 답으로 내 공사를 만들어요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { InfoForm } from "@/components/start/InfoForm";
import { InfoLocked } from "@/components/start/InfoLocked";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { getMyProject, getProjectShell, getRegions, getRoomRule, type ApiProject } from "@/lib/api/project";
import { decText, todaySeoul } from "@/lib/format";
import { EMPTY_DRAFT, fromSaved, placeText, roomsOf, type InfoDraft } from "@/lib/guest/info";
import { MOCK_V3A, mockKeyOf } from "@/lib/mock/v3a/mode";
import { getSession, requireRole } from "@/lib/session";

export const metadata = { title: "도배 기본 정보" };

/** v2로 만든 공사(기본 정보 v3 칸이 비었음)는 옛 칸에서 모아요 */
function draftOfProject(p: ApiProject): InfoDraft {
  if (p.home) return fromSaved(p.home);
  return {
    ...EMPTY_DRAFT,
    sido: p.sido, sgg: p.sgg, emd: p.emd ?? "",
    area: p.size.m2 ? decText(String(p.size.m2)) : "",
    basis: p.size.basis === "exclusive" ? "exclusive" : "supply",
    occupied: p.occupied, grade: p.trades.dobae?.grade ?? null,
    budget: p.budget_won ? String(Math.round(p.budget_won / 10000)) : "",
    start: p.when.kind === "date" ? p.when.start ?? null : null,
  };
}

export default async function StartPage({ searchParams }: { searchParams: Promise<{ edit?: string }> }) {
  const { edit } = await searchParams;
  const today = todaySeoul();
  const [session, regions, roomRule] = await Promise.all([getSession(), getRegions(), getRoomRule()]);

  if (edit) {
    if (!mockKeyOf(edit)) await requireRole("customer", `/start?edit=${encodeURIComponent(edit)}`);
    const shell = await getProjectShell(edit);
    if (!shell) notFound();
    const p = shell.mock ? null : await getMyProject(edit);
    const draft = shell.home ? fromSaved(shell.home) : p ? draftOfProject(p) : EMPTY_DRAFT;
    const crumbs = [{ label: "내 공사", href: "/my" }, { label: shell.name, href: `/projects/${shell.id}` }, { label: "도배 기본 정보" }];
    if (shell.locked) {
      return (
        <>
          <AppHeader phone={{ title: "도배 기본 정보", back: `/projects/${shell.id}` }} />
          <Main narrow>
            <PageHead title="도배 기본 정보" crumbs={crumbs} />
            <InfoLocked draft={draft} region={placeText(regions, draft)} today={today} rooms={roomsOf(draft, roomRule)} />
          </Main>
          <BottomBar>
            <Button variant="secondary" size="lg" href="/start">다른 조건으로 새로 받기</Button>
          </BottomBar>
        </>
      );
    }
    return (
      <>
        <AppHeader phone={{ title: "도배 기본 정보", back: `/projects/${shell.id}/standard` }} />
        <InfoForm key={shell.id} regions={regions} roomRule={roomRule} today={today} mode="edit" projectId={shell.id} initial={draft} mock={shell.mock} crumbs={crumbs} />
      </>
    );
  }

  return (
    <>
      <AppHeader phone={{ title: "도배 기본 정보", back: "/" }} />
      <InfoForm regions={regions} roomRule={roomRule} today={today} mode={session?.role === "customer" ? "member" : "guest"} mock={MOCK_V3A}
        crumbs={[{ label: "표준견적서 받기", href: "/start" }, { label: "도배 기본 정보" }]} />
    </>
  );
}

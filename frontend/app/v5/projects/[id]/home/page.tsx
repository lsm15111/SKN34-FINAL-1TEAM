// /v5/projects/{id}/home — 우리 집 정보 고치기. 기본 정보 고치기(/start?edit=)와 같은 폼 · 같은 PATCH예요.
// 저장하면 공사 화면(/projects/{id})으로 가요. ?field=면 그 칸에 처음 초점을 줘요(철거 범위 · 직접 할 일도). 첫 실측 요청 뒤면
// 잠긴 화면(C50)이고, 직접 할 일만 그 화면에서 고쳐요(PUT /projects/{id}/diy).
// v5: 기능 확인(getCaps)이 꺼져 있으면(dev 백엔드) 방 개수 · 철거 범위 · 직접 할 일 칸이 없어요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { InfoForm, type InfoFocus } from "@/components/v5/start/InfoForm";
import { InfoLocked } from "@/components/v5/start/InfoLocked";
import { getDiy, getMyProject, getProjectShell, getRegions, getRoomRule } from "@/lib/v5/api/project";
import { todaySeoul } from "@/lib/v5/format";
import { EMPTY_DRAFT, draftOfProject, fromSaved, placeText, roomsOf } from "@/lib/v5/guest/info";
import { getCaps } from "@/lib/v5/caps";

export const metadata = { title: "우리 집 정보" };

const FOCUS: readonly InfoFocus[] = ["region", "area", "rooms", "occupied", "spaces", "faces", "demolition", "grade", "budget", "start", "diy"];

export default async function HomeInfoPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ field?: string }>;
}) {
  const [{ id }, { field }] = await Promise.all([params, searchParams]);
  const today = todaySeoul();
  const [shell, regions, roomRule, diy, { v4 }] = await Promise.all([getProjectShell(id), getRegions(), getRoomRule(), getDiy(id), getCaps()]);
  const caps = { v4 };
  if (!shell) notFound();
  const p = shell.home || shell.mock ? null : await getMyProject(id);
  const draft = { ...(shell.home ? fromSaved(shell.home) : p ? draftOfProject(p) : EMPTY_DRAFT), diy };
  const base = `/v5/projects/${shell.id}`;
  const crumbs = [{ label: "내 공사", href: "/v5/my" }, { label: shell.name, href: base }, { label: "우리 집 정보" }];
  const focus = FOCUS.find((x) => x === field);
  if (shell.locked) {
    return (
      <>
        <AppHeader only="phone" phone={{ title: "우리 집 정보", back: base }} />
        <Main narrow>
          <PageHead title="우리 집 정보" crumbs={crumbs} />
          <InfoLocked draft={draft} region={placeText(regions, draft)} today={today} rooms={v4 ? roomsOf(draft, roomRule) : undefined}
            diy={{ projectId: shell.id, after: base, focus: focus === "diy", mock: shell.mock }} caps={caps} />
        </Main>
      </>
    );
  }
  return (
    <>
      <AppHeader only="phone" phone={{ title: "우리 집 정보", back: base }} />
      <InfoForm key={shell.id} regions={regions} roomRule={roomRule} today={today} mode="edit" projectId={shell.id} initial={draft} mock={shell.mock}
        crumbs={crumbs} after={base} focus={focus} caps={caps} />
    </>
  );
}

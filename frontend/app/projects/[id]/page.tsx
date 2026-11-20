// /projects/{id} — 한 공사 화면(C43 요약 · C63 기록 ?tab=log). 없거나 남의 공사면 404.
// 요약: 지금 할 일 · 단계 · 업체 · 서류 · 기본 정보(요청 뒤 잠김). 기록: 실측 일정 · 견적서 · 공사 이력 시간 순.
// 읽기: GET /projects/{id}/overview · /log · /quotes(업체 줄 금액 · 표준견적서 합계). 이 공사 소식이 오면 다시 읽어요.
// v4(비서 화면)에서는 레이아웃의 대화가 이 주소의 화면이라 카드 자리를 비워요.
import { notFound } from "next/navigation";
import { uiMode } from "@/components/assistant/mode";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Tabs } from "@/components/project/Kit";
import { LogList } from "@/components/project/LogList";
import { Summary } from "@/components/project/Summary";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { getCompare, getOverview, getProjectLog } from "@/lib/api/schedule";
import { getVisitProject } from "@/lib/api/visit";

export const metadata = { title: "내 공사" };

export default async function ProjectHub({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string | string[] }> }) {
  if ((await uiMode()) === "v4") return null;
  const { id } = await params;
  const { tab } = await searchParams;
  const log = tab === "log";
  const [p, ov] = await Promise.all([getVisitProject(id), getOverview(id)]);
  if (!p || !ov) notFound();
  const base = `/projects/${encodeURIComponent(p.id)}`;
  const [compare, items] = await Promise.all([
    log ? null : getCompare(p.id).catch(() => null),
    log ? getProjectLog(p.id) : null,
  ]);

  return (
    <>
      <AppHeader only="phone" phone={{ title: p.name, back: "/my" }} />
      <Main narrow>
        <PageHead title={p.name} crumbs={[{ label: "내 공사", href: "/my" }, { label: p.name }]} />
        <Tabs
          label="공사 화면"
          items={[
            { label: "요약", href: base, on: !log },
            { label: "기록", href: `${base}?tab=log`, on: log },
          ]}
        />
        {log ? <LogList items={items ?? []} /> : <Summary p={p} ov={ov} compare={compare} />}
      </Main>
      <LiveRefresh projectId={p.id} />
    </>
  );
}

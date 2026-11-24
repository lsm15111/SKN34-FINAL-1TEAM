// /projects/{id}/schedule — 실측 뒤 공사(C35 공사 날짜 · C52 다른 날짜 요청 · C37 추가 금액 · C38 공사 끝 확인).
// ?view=dates|extra|done. 없으면 가장 급한 것(공사 끝 확인 > 추가 금액 답 > 공사 날짜)을 보여요.
// 읽기는 GET /projects/{id}/schedule 하나(도배 한 줄). 날 · 기한 · 금액은 API 값 그대로예요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Strip } from "@/components/project/Kit";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { datesView, doneView, extraView } from "@/components/schedule/views";
import { currentExtra, defaultView, VIEW_TITLE, type ScheduleView } from "@/components/schedule/v3text";
import { getSchedule } from "@/lib/api/schedule";
import { getVisitProject, visitToday } from "@/lib/api/visit";

export const metadata = { title: "공사" };

const VIEWS: ScheduleView[] = ["dates", "extra", "done"];

export default async function SchedulePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ view?: string | string[] }> }) {
  const { id } = await params;
  const raw = (await searchParams).view;
  const asked = Array.isArray(raw) ? raw[0] : raw;
  const [p, sch, today] = await Promise.all([getVisitProject(id), getSchedule(id), visitToday()]);
  if (!p || !sch) notFound();
  const base = `/projects/${encodeURIComponent(p.id)}`;
  const t = sch.trades.find((x) => x.deal.trade === "dobae") ?? sch.trades[0] ?? null;
  const view: ScheduleView = VIEWS.includes(asked as ScheduleView) ? (asked as ScheduleView) : defaultView(t);
  const title = VIEW_TITLE[view];

  let body: React.ReactNode;
  let bar: React.ReactNode = null;
  if (!t) {
    body = (
      <EmptyState icon="calendar" title="업체를 확정하면 공사 날짜가 여기에 와요" action={<Button variant="text" arrow href={`${base}/quotes`}>실측 견적서 보기</Button>}>
        확정한 업체가 공사할 날을 하나씩 골라 올려요
      </EmptyState>
    );
  } else {
    const ctx = { projectId: p.id, t, holidays: sch.holidays, finalVersion: sch.final_version, today, startDate: p.startDate, requestDue: sch.request_due_preview ?? null };
    const v = view === "extra" ? extraView(ctx) : view === "done" ? doneView(ctx) : datesView(ctx);
    body = v.body;
    bar = v.bar;
  }

  // 이 화면에서 다른 일로 가는 줄(공사 날짜 ↔ 추가 금액 ↔ 공사 끝)
  const others: { label: string; href: string }[] = [];
  if (t) {
    const x = currentExtra(t);
    if (view !== "dates") others.push({ label: "공사 날짜", href: `${base}/schedule?view=dates` });
    // 답을 기다리는 추가 금액은 고객이 답할 차례예요(누가 기다리는지 헷갈리지 않게)
    if (view !== "extra" && x) others.push({ label: x.answer === "pending" ? "추가 금액 · 답할 차례" : "추가 금액", href: `${base}/schedule?view=extra` });
    if (view !== "done" && ["checking", "fixing", "done"].includes(t.deal.status)) others.push({ label: "공사 끝 확인", href: `${base}/schedule?view=done` });
  }

  return (
    <>
      <AppHeader only="phone" phone={{ title, back: base }} />
      <Main narrow>
        <PageHead title={title} crumbs={[{ label: "내 공사", href: "/my" }, { label: p.name, href: base }, { label: title }]} />
        {body}
        {others.map((o) => <Strip key={o.href} label={o.label} href={o.href} />)}
      </Main>
      {bar}
      <LiveRefresh projectId={p.id} kinds={["deal", "extra"]} />
    </>
  );
}

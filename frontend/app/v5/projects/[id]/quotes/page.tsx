// /v5/projects/{id}/quotes — 실측 견적서 비교(C33 폰 · D18 웹 비교표 + 옆 AI 칸).
// 읽기: GET /projects/{id}/quotes(합계 · 차이 · 유효기간 지남은 계산 엔진) + 실측 일정 상태판(실측 반나절 · 대화 id).
// 확정은 업체마다 확정 화면(C34)으로 가요. 유효기간이 지나면 확정 대신 '견적서 다시 요청'(D20 A).
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QuoteBoard } from "@/components/v5/compare/QuoteBoard";
import { quotedRows } from "@/components/compare/v3";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { AiSlot } from "@/components/visit/AiSlot";
import { slotText } from "@/components/v5/visit/text";
import { getCompare } from "@/lib/api/schedule";
import { getVisitBoard, getVisitProject } from "@/lib/api/visit";

export const metadata = { title: "실측 견적서" };

export default async function QuotesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [p, compare, board] = await Promise.all([getVisitProject(id), getCompare(id), getVisitBoard(id)]);
  if (!p || !compare) notFound();
  const base = `/v5/projects/${encodeURIComponent(p.id)}`;
  const rows = quotedRows(compare);
  const slots: Record<string, string> = {};
  const threads: Record<string, string | null> = {};
  for (const r of board?.board ?? []) {
    if (r.booked) slots[r.visit_id] = slotText(r.booked);
    threads[r.visit_id] = r.thread_id;
  }

  return (
    <>
      <AppHeader only="phone" phone={{ title: "실측 견적서", back: base, action: <AsideOpenButton /> }} />
      <Main>
        <PageHead title="실측 견적서" crumbs={[{ label: "내 공사", href: "/v5/my" }, { label: p.name, href: base }, { label: "실측 견적서" }]} />
        <WithAside aside={<AiSlot screen="quotes" projectId={p.id} />}>
          {rows.length || compare.deal ? (
            <QuoteBoard projectId={p.id} compare={compare} slots={slots} threads={threads} />
          ) : (
            <EmptyState
              icon="doc"
              title="실측 견적서가 아직 없어요"
              action={<Button variant="text" arrow href={`${base}/visits`}>실측 일정 보기</Button>}
            >
              실측을 받으면 업체가 자기 양식 견적서를 보내요
            </EmptyState>
          )}
        </WithAside>
      </Main>
      <LiveRefresh projectId={p.id} kinds={["quote", "visit", "deal"]} />
    </>
  );
}

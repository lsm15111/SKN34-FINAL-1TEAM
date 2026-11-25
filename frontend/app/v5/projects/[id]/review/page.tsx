// /v5/projects/{id}/review — 리뷰 쓰기(C39). 공사 끝을 확인한 고객만 써요(review_open). 올리면 업체 상세 리뷰에 보여요.
// 리뷰 게시 기준 공개(전자상거래법 제21조의4)는 팀 · 법무 확인(팀 확인 8). 별 · 칩 · 글 · 기준 줄(C49)은 B2a components/review/ReviewFields예요.
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { warrantyText } from "@/components/compare/v3";
import { Small, Strip, Sub } from "@/components/project/Kit";
import { ReviewForm } from "@/components/v5/schedule/ReviewForm";
import { getCompare, getSchedule } from "@/lib/api/schedule";
import { getVisitProject } from "@/lib/api/visit";
import { dateLong } from "@/lib/v5/format";

export const metadata = { title: "리뷰 쓰기" };

export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [p, sch, compare] = await Promise.all([getVisitProject(id), getSchedule(id), getCompare(id)]);
  if (!p || !sch) notFound();
  const base = `/v5/projects/${encodeURIComponent(p.id)}`;
  const deal = sch.trades.find((t) => t.deal.trade === "dobae")?.deal ?? sch.trades[0]?.deal ?? null;
  const months = deal ? compare?.vendors.find((r) => r.visit_id === deal.visit_id)?.latest?.warranty_months ?? null : null;
  const head = <PageHead title="리뷰 쓰기" crumbs={[{ label: "내 공사", href: "/v5/my" }, { label: p.name, href: base }, { label: "리뷰 쓰기" }]} />;
  const phone = <AppHeader only="phone" phone={{ title: "리뷰 쓰기", back: base }} />;

  if (deal?.review_open) {
    return (
      <>
        {phone}
        <ReviewForm
          projectId={p.id}
          dealId={deal.id}
          vendorId={deal.vendor_id}
          top={
            <>
              {head}
              <Sub>{deal.vendor_name} · {p.name}</Sub>
              {deal.work_done_on ? <Small>{dateLong(deal.work_done_on)} 공사 끝</Small> : null}
            </>
          }
          after={
            <Strip
              label="하자가 보이면"
              sub={months ? `견적서의 하자 보수 기간(${warrantyText(months)}) 안에 채팅으로 접수해요` : "견적서의 하자 보수 기간 안에 채팅으로 접수해요"}
              action={deal.thread_id ? <Button variant="text" arrow href={`/chat/${encodeURIComponent(deal.thread_id)}`}>하자 접수</Button> : undefined}
            />
          }
        />
      </>
    );
  }

  return (
    <>
      {phone}
      <Main narrow>
        {head}
        {deal?.review_id ? (
          <EmptyState icon="star" title="리뷰를 썼어요" action={deal.vendor_id ? <Button variant="text" arrow href={`${base}/vendors/${encodeURIComponent(deal.vendor_id)}`}>업체 리뷰 보기</Button> : undefined}>
            공사마다 리뷰는 한 번 써요
          </EmptyState>
        ) : (
          <EmptyState icon="star" title="공사 끝을 확인하면 리뷰를 쓸 수 있어요" action={<Button variant="text" arrow href={`${base}/schedule?view=done`}>공사 끝 확인</Button>}>
            믿집에서 공사를 끝낸 고객만 써요
          </EmptyState>
        )}
      </Main>
    </>
  );
}

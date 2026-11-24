// /projects/{id}/quotes/{visitId}/confirm — 업체 확정 확인(C34). 폰 화면 · 웹 가운데 카드 모양.
// 확정한 견적서 버전은 바뀌지 않아요. 확정하면 다른 업체 견적서는 닫히고 공사 날짜는 확정 업체가 올려요(서버).
// 업체가 견적서를 다시 올리면(실시간 소식) 화면을 다시 읽어 새 금액 · 판으로 확정해요.
import { notFound } from "next/navigation";
import { LiveRefresh } from "@/components/schedule/LiveRefresh";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { Money } from "@/components/ui/Money";
import { ConfirmCard } from "@/components/confirm/ConfirmCard";
import { RequoteButton } from "@/components/compare/RequoteButton";
import { quotedRows } from "@/components/compare/v3";
import { Notice, Row, Rows } from "@/components/project/Kit";
import { iGa } from "@/components/visit/text";
import { getCompare } from "@/lib/api/schedule";
import { getVisitProject } from "@/lib/api/visit";
import { dateLong, euro } from "@/lib/format";
import s from "@/components/confirm/card.module.css";

export const metadata = { title: "업체 확정" };

export default async function ConfirmPage({ params }: { params: Promise<{ id: string; visitId: string }> }) {
  const { id, visitId } = await params;
  const [p, compare] = await Promise.all([getVisitProject(id), getCompare(id)]);
  if (!p || !compare) notFound();
  const row = compare.vendors.find((r) => r.visit_id === visitId);
  if (!row) notFound();
  const base = `/projects/${encodeURIComponent(p.id)}`;
  const back = `${base}/quotes`;
  const q = row.latest;
  const others = quotedRows(compare).filter((r) => r.visit_id !== visitId).map((r) => r.vendor_name);
  const deal = compare.deal;

  let body: React.ReactNode;
  if (deal) {
    body = (
      <section className={`${s.card} ${s.done}`} aria-labelledby="cf-d">
        <h2 id="cf-d" className={s.title}>{deal.visit_id === visitId ? `${euro(deal.vendor_name)} 확정했어요` : `이미 ${euro(deal.vendor_name)} 확정했어요`}</h2>
        <p className={s.note}>확정한 견적서는 바뀌지 않아요.</p>
        <Button variant="text" arrow href={`${base}/schedule`}>공사 날짜 보기</Button>
      </section>
    );
  } else if (!q || q.total == null) {
    body = (
      <section className={`${s.card} ${s.done}`} aria-labelledby="cf-w">
        <h2 id="cf-w" className={s.title}>{row.vendor_name} 실측 견적서가 아직 없어요</h2>
        <Button variant="text" arrow href={back}>실측 견적서 보기</Button>
      </section>
    );
  } else if (row.expired) {
    body = (
      <section className={`${s.card} ${s.done}`} aria-labelledby="cf-x">
        <h2 id="cf-x" className={s.title}>유효기간이 지나 확정할 수 없어요</h2>
        <p className={s.note}>{row.vendor_name}에 견적서를 다시 요청하면 새 견적서로 확정해요.</p>
        <RequoteButton projectId={p.id} visitId={visitId} vendorName={row.vendor_name} />
      </section>
    );
  } else {
    body = (
      <ConfirmCard projectId={p.id} visitId={visitId} vendorName={row.vendor_name} seenVer={q.version} backHref={back}>
        <Rows>
          <Row label="확정 금액" sub="부가세 포함" value={<Money value={q.total} size="line" />} />
          <Row label="견적서" value={q.sent_at ? `${dateLong(q.sent_at)} 받은 것` : "—"} valueSub />
          <Row label="공사 기간" value={q.days != null ? `${q.days}일` : "—"} valueSub />
        </Rows>
        <p className={s.note}>
          이 견적서로 고정돼요. {others.length ? `${others.join(" · ")} 실측 견적서는 닫히고, ` : ""}공사 날짜는 {iGa(row.vendor_name)} 올려요.
        </p>
      </ConfirmCard>
    );
  }

  return (
    <>
      <AppHeader only="phone" phone={{ title: "실측 견적서", back }} />
      <Main narrow>
        <PageHead title="업체 확정" crumbs={[{ label: "내 공사", href: "/my" }, { label: p.name, href: base }, { label: "실측 견적서", href: back }, { label: "업체 확정" }]} />
        {row.valid_soon && !deal && !row.expired ? <Notice tone="warn">이 견적서는 유효기간이 곧 끝나요</Notice> : null}
        <div className={s.wrap}>{body}</div>
      </Main>
      <LiveRefresh projectId={p.id} kinds={["quote", "visit", "deal"]} />
    </>
  );
}

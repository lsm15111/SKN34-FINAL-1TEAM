// /v5/projects/{id}/vendors/{vid}/reviews — 리뷰 전체(C48) · 리뷰 기준 시트(C49).
// 최신순 · 낮은 별점부터(?sort=), 숨긴 리뷰는 API가 빼요. 업체가 연결한 외부 리뷰 링크는 우선 숨겨요(2026-11-24 사용자, 아래 주석).
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { RatingSummary } from "@/components/review/RatingSummary";
import { ReviewFeed } from "@/components/review/ReviewFeed";
import { ReviewRulesLine } from "@/components/review/RulesSheet";
import { Tabs } from "@/components/ui/Tabs";
import s from "@/components/v5/vendors/vendors3.module.css";
import { getProjectShell } from "@/lib/v5/api/project";
import { getVendorDetail, getVendorReviews } from "@/lib/v5/api/shortlist";

export const metadata = { title: "리뷰" };

export default async function VendorReviewsPage({ params, searchParams }: {
  params: Promise<{ id: string; vid: string }>;
  searchParams: Promise<{ sort?: string | string[] }>;
}) {
  const { id, vid } = await params;
  const { sort: asked } = await searchParams;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const sort = asked === "low" ? "low" : "latest";
  const [d, page] = await Promise.all([getVendorDetail(shell.id, vid), getVendorReviews(shell.id, vid, sort)]);
  if (!d || !page) notFound();

  const name = d.profile.biz_name ?? "업체";
  const base = `/v5/projects/${shell.id}`;
  const detail = `${base}/vendors/${encodeURIComponent(vid)}`;
  const here = `${detail}/reviews`;
  const title = `${name} 리뷰`;

  return (
    <>
      <AppHeader only="phone" phone={{ title, back: detail }} />
      <Main narrow>
        <PageHead title={title} crumbs={[{ label: "내 공사", href: "/v5/my" }, { label: shell.name, href: base }, { label: "업체 보기", href: `${base}/vendors` }, { label: name, href: detail }, { label: "리뷰" }]} />
        <section className={s.group} aria-label="별점 요약">
          <RatingSummary rating={page.rating} />
          {page.rating.count > 0 ? (
            <Tabs variant="pill" label="리뷰 순서" value={sort} items={[
              { key: "latest", label: "최신순", href: `${here}?sort=latest` },
              { key: "low", label: "낮은 별점부터", href: `${here}?sort=low` },
            ]} />
          ) : null}
          <ReviewRulesLine />
        </section>
        <section className={s.list} aria-label={`${name} 리뷰 목록`}>
          <ReviewFeed key={sort} projectId={shell.id} vendorId={vid} vendorName={name} first={page} sort={sort} />
        </section>
        {/* 외부 리뷰는 우선 숨김(11-24 사용자). 되살릴 때 ReviewLinks · safeLinks import와 links(safeLinks(page.links))를 다시 둬요
        {links.length ? (
          <section className={s.group} aria-label="업체가 연결한 외부 리뷰">
            <ReviewLinks vendorId={vid} links={links} />
          </section>
        ) : null} */}
      </Main>
    </>
  );
}

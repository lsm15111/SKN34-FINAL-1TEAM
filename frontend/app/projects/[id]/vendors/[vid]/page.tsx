// /projects/{id}/vendors/{vid} — 업체 자세히(C11 · D07 + 옆 AI 칸) · 시공 사례 크게 보기(C47, ?photo=n).
// 가견적 = 업체가 확인한 단가 × 믿집 수량(계산 엔진). 벽지를 바꿔 보면(?grade=) 그 벽지의 가견적을 API가 다시 계산해 줘요.
// 화면은 금액을 더하거나 빼지 않아요(다른 벽지 차이도 API grade_diff). 남의 공사 · 목록 밖 업체면 404예요.
// v4(비서 화면 서랍)에서는 표준견적서와 견준 %를 보이지 않아요(리드 결정 2026-11-21).
import { notFound } from "next/navigation";
import { uiMode } from "@/components/assistant/mode";
import { AiPanel } from "@/components/ai/AiPanel";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { Avatar } from "@/components/ui/Avatar";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { BigFigure } from "@/components/ui/Money";
import { QuoteLines } from "@/components/ui/QuoteLines";
import { Stars } from "@/components/ui/Stars";
import { SummaryRows } from "@/components/ui/Summary";
import { avgText } from "@/components/review/RatingSummary";
import { ReviewRulesLine } from "@/components/review/RulesSheet";
import { reviewDate, topTags } from "@/components/review/tags";
import { CasesBlock, type CasePhoto } from "@/components/vendors/CasesBlock";
import { DetailActions } from "@/components/vendors/DetailActions";
import { DetailTabs, type TabItem } from "@/components/vendors/DetailTabs";
import { GradeToggle } from "@/components/vendors/GradeToggle";
import { ReviewLinks } from "@/components/vendors/ReviewLinks";
import { FAQ_LABEL } from "@/components/vendors/text";
import { areasText, caseLabel, compareText, estimateLines, feeText, monthText, replyText, safeLinks } from "@/components/vendors/v3text";
import { VendorMenu } from "@/components/vendors/VendorMenu";
import s from "@/components/vendors/vendors3.module.css";
import { getProjectShell } from "@/lib/api/project";
import { getShortlist, getVendorDetail, photoSrc, type Grade } from "@/lib/api/shortlist";
import { areaText } from "@/lib/format";
import { bizNoText } from "@/lib/labels";

export const metadata = { title: "업체 자세히" };

const isGrade = (v: unknown): v is Grade => v === "basic" || v === "economy";

export default async function VendorDetailPage({ params, searchParams }: {
  params: Promise<{ id: string; vid: string }>;
  searchParams: Promise<{ grade?: string | string[] }>;
}) {
  const { id, vid } = await params;
  const { grade: asked } = await searchParams;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const want = isGrade(asked) ? asked : null;
  const [d, short] = await Promise.all([getVendorDetail(shell.id, vid, want), getShortlist(shell.id).catch(() => null)]);
  if (!d) notFound();

  const pr = d.profile;
  const name = pr.biz_name ?? "업체";
  const base = `/projects/${shell.id}`;
  const listHref = `${base}/vendors`;
  const est = d.estimate_v3 ?? null;
  // 보여 준 벽지는 API 값(?grade= 또는 공사 벽지). 고른 벽지를 업체가 안 하면 paper_ok false · state paper_unsupported
  const grade: Grade = d.grade ?? est?.grade ?? want ?? (shell.cond?.grade === "economy" ? "economy" : "basic");
  const state = est && est.paper_ok === false ? "paper_unsupported" : d.state ?? (est ? "ok" : "no_estimate");
  const r = d.rating ?? null;
  const avg = avgText(r);
  const reviewCount = r?.count ?? 0;
  const tags = topTags(r?.tags, 2);
  const links = safeLinks(d.review_links);
  const photos: CasePhoto[] = pr.portfolio.map((p, i) => ({
    key: p.id,
    src: photoSrc(shell.id, vid, p.file_id, i),
    label: caseLabel(p),
    title: caseLabel(p, true),
    alt: [`${caseLabel(p, true)} 시공 사진`, monthText(p.taken_on)].filter(Boolean).join(" · "),
    sub: [p.area_text || (p.area_m2 ? areaText(p.area_m2, p.area_basis) : null), monthText(p.taken_on), name].filter(Boolean).join(" · "),
  }));
  const area = areasText(pr.areas.map((a) => a.label || a.sgg));
  const line1 = [area, d.in_area ? null : "출장 여부는 업체가 답해요", d.verified_on ? "사업자 확인함" : null].filter(Boolean).join(" · ");
  const fee = feeText(pr.visit_fee);
  const reply = replyText(d.reply_hours);
  const lines = est ? estimateLines(est.lines, grade) : null;
  const count = short?.count ?? (d.shortlisted ? 1 : 0);
  const v4 = (await uiMode()) === "v4";
  // 업체가 적은 자주 묻는 답(업체 정보 화면과 같은 순서 · 이름, QA r6 M12). 업체 글은 글 그대로 보여요
  const faqs = FAQ_LABEL.flatMap(({ key, label }) => { const answer = pr.faqs.find((f) => f.key === key)?.answer?.trim(); return answer ? [{ key, label, answer }] : []; });

  const tabs: TabItem[] = [
    { id: "est", label: "가견적" },
    ...(photos.length ? [{ id: "cases", label: <><span className={s.webWord}>시공 </span>사례 <span className="mj-num">{photos.length}</span></> }] : []),
    { id: "reviews", label: <>리뷰 <span className="mj-num">{reviewCount}</span></> },
    { id: "biz", label: "사업자 정보", webOnly: true },
  ];

  const opened = pr.opened_on ? [monthText(pr.opened_on), d.years_open != null ? `업력 ${d.years_open}년` : null].filter(Boolean).join(" · ") : null;
  const biz = [
    { key: "name", label: "상호 · 대표자", value: [name, pr.owner_name].filter(Boolean).join(" · ") },
    ...(pr.biz_no ? [{ key: "no", label: "사업자등록번호", value: bizNoText(pr.biz_no), num: true }] : []),
    ...(opened ? [{ key: "open", label: "개업", value: opened }] : []),
    ...(pr.address_area ? [{ key: "addr", label: "사업장", value: pr.address_area }] : []),
    ...(d.verified_on ? [{ key: "ok", label: "믿집 사업자 확인", value: reviewDate(d.verified_on), num: true }] : []),
    ...(pr.interior_license ? [{ key: "lic", label: "실내건축공사업 등록", sub: "업체가 적었어요", value: pr.interior_license }] : []),
    ...(pr.insurance ? [{ key: "ins", label: "보험", sub: "업체가 적었어요", value: pr.insurance }] : []),
  ];

  return (
    <>
      <AppHeader only="phone" phone={{ title: name, back: listHref, action: <VendorMenu vendorId={vid} name={name} /> }} />
      <Main>
        <PageHead title={name} crumbs={[{ label: "내 공사", href: "/my" }, { label: shell.name, href: base }, { label: "업체 보기", href: listHref }, { label: name }]} />
        <WithAside aside={<AiPanel screen="vendor" projectId={shell.id} ids={[vid]} context={`${name} 보는 중`} />}>
          <section className={s.group} aria-label={`${name} 요약`}>
            <div className={s.vhead}>
              <Avatar name={name} size="l" warm />
              <div className={s.vtext}>
                <p className={`${s.vname} ${s.phoneWord}`} aria-hidden="true">{name}</p>
                <p className={s.vmeta}>{line1}</p>
                <p className={`${s.vmeta} mj-num`}>
                  {avg ? <><Stars value={Number(avg)} count={reviewCount} size="sm" /> · </> : null}
                  믿집 공사 {r?.done_count ?? 0}건{reply ? ` · ${reply}` : null}{fee ? <span className={s.webWord}> · {fee}</span> : null}
                </p>
              </div>
              <VendorMenu vendorId={vid} name={name} className={s.headMenu} />
            </div>
            <DetailTabs items={tabs} />
          </section>

          <section id="est" className={s.group} aria-labelledby="est-t">
            <h2 id="est-t" className="mj-sr">가견적</h2>
            {state === "ok" && est ? (
              <BigFigure label="가견적 · 부가세 포함" value={est.total} caption={["업체 단가 × 믿집 수량", v4 ? null : compareText(est.vs_standard_pct)].filter(Boolean).join(" · ")} />
            ) : (
              <div>
                <p className={s.eb}>가견적</p>
                <p className={s.none}>{state === "paper_unsupported" ? "이 벽지는 안 해요" : "가견적 준비 중"}</p>
                {state === "no_estimate" ? <p className={s.help}>업체가 단가를 확인하면 보여요</p> : null}
              </div>
            )}
            {state === "no_estimate" ? null : (
              <>
                <GradeToggle grade={grade} diff={state === "ok" ? d.grade_diff ?? null : null} />
                <p className={s.help}>요청할 때 고른 벽지로 가견적이 고정돼요</p>
              </>
            )}
          </section>
          {state === "ok" && est && lines ? (
            <section className={s.group} aria-label="가견적 줄">
              {lines.outside.length ? (
                <>
                  <QuoteLines lines={lines.inside} caption={`${name} 가견적 줄 · 표준견적서와 같은 일`} />
                  {/* 퍼티 · 식대 · 운송비처럼 표준견적서 합계에 같은 일이 없는 줄은 따로 보여요. 표준견적서와 견준 %에서는 빠져요(API in_standard).
                      그중 '선택' 줄(퍼티 · 운송비, API optional)은 표준견적서처럼 괄호 금액 · 합계 밖이에요(아래 합계도 API가 빼고 셌어요) */}
                  <p className={s.eb}>표준견적서 합계에 없는 줄 · 표준견적서와 비교할 때는 빼요</p>
                  <QuoteLines lines={lines.outside} totals={{ supply: est.supply, vat: est.vat, total: est.total }} vatSplit caption={`${name} 가견적 줄 · 표준견적서 합계에 없는 일`} />
                </>
              ) : (
                <QuoteLines lines={lines.inside} totals={{ supply: est.supply, vat: est.vat, total: est.total }} vatSplit caption={`${name} 가견적 줄`} />
              )}
            </section>
          ) : null}

          {photos.length ? <CasesBlock id="cases" photos={photos} /> : null}

          {faqs.length ? (
            <section id="faq" className={s.group} aria-labelledby="faq-t">
              <h2 id="faq-t" className={s.hs}>자주 묻는 답</h2>
              <dl className={s.faq}>
                {faqs.map((f) => <div key={f.key}><dt>{f.label}</dt><dd>{f.answer}</dd></div>)}
              </dl>
            </section>
          ) : null}

          <section id="reviews" className={s.group} aria-labelledby="rv-t">
            <div className={s.gh}>
              <h2 id="rv-t">리뷰 <span className="mj-num">{reviewCount}</span>{avg ? <> · <Stars value={Number(avg)} /></> : null}</h2>
              {reviewCount ? <Button variant="text" arrow href={`${listHref}/${encodeURIComponent(vid)}/reviews`}>모두 보기</Button> : null}
            </div>
            {tags.length ? <p className={s.quote}>{tags.map((t) => `"${t}"`).join(" · ")}</p> : reviewCount ? null : <p className={s.sub}>아직 리뷰가 없어요</p>}
            <ReviewRulesLine />
            <ReviewLinks vendorId={vid} links={links} />
          </section>

          <section id="biz" className={`${s.group} ${s.webGroup}`} aria-labelledby="biz-t">
            <h2 id="biz-t" className={s.hs}>사업자 정보</h2>
            <SummaryRows size="sm" items={biz} />
          </section>
        </WithAside>
      </Main>
      <BottomBar>
        <DetailActions projectId={shell.id} vendorId={vid} name={name} grade={grade} canPick={state === "ok"} shortlisted={!!d.shortlisted} count={count} mock={shell.mock} />
      </BottomBar>
    </>
  );
}

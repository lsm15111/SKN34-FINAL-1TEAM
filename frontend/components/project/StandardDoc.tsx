// 표준견적서 한 장 (시안 WStandard · 서류형). 숫자는 모두 API(계산 엔진)가 준 값을 그대로 보이고,
// 화면에서 더하거나 나누지 않는다. 공급가와 부가세를 나눠 보이는 곳은 맨 아래 합계 칸 하나다.
import Link from "next/link";
import type { ApiProject } from "@/lib/api/project";
import type { ApiStandard } from "@/lib/api/quote";
import { budgetLabel, gradeLabel, lineStateLabel, mokLabel, outsideTotal, sizeLabel, tradeLabel } from "@/lib/labels";
import { dateSeoul, decText, dotDate, numText, won } from "@/lib/format";
import { shareText } from "@/lib/range";
import { RangeCard } from "./RangeCard";
import { RegradeButton } from "./RegradeButton";
import s from "./StandardDoc.module.css";

type Line = ApiStandard["trades"][number]["lines"][number];

function None({ what }: { what: string }) {
  return <><span aria-hidden="true">—</span><span className="mj-sr">{what} 없음</span></>;
}

function LineState({ state }: { state: string }) {
  const label = lineStateLabel(state);
  if (state === "after_visit") {
    return (
      <>
        <span className="mj-st mj-st-wait">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="7" cy="7" r="5.5" /><path d="M7 4v3.2l2 1.3" /></svg>
          {label}
        </span>
        <br /><span className="mj-small">합계 밖</span>
      </>
    );
  }
  if (state === "optional") return <><span className="mj-st mj-st-off">{label}</span><br /><span className="mj-small">합계 밖</span></>;
  if (state === "excluded") return <span className="mj-st mj-st-off">{label}</span>;
  return <>{label}</>;
}

function Amount({ l }: { l: Line }) {
  if (l.amount == null) return <None what="금액" />;
  if (outsideTotal(l.state)) return <>({numText(l.amount)})<span className="mj-sr"> 참고 금액</span></>;
  return <>{numText(l.amount)}</>;
}

export function StandardDoc({ p, q, title }: { p: ApiProject; q: ApiStandard; title: string }) {
  const used = new Set([...(p.trades.dobae?.spaces ?? []), ...(p.trades.mokgong?.spaces ?? [])]);
  const spaces = p.spaces.filter((sp) => used.has(sp.id)).map((sp) => sp.name).join(" · ");
  const items = (p.trades.mokgong?.items ?? []).map(mokLabel).join(" · ");
  const tradeName = (t: ApiStandard["trades"][number]) => (t.trade === "dobae" ? `도배 · ${gradeLabel(t.grade)}` : tradeLabel(t.trade));
  const works = q.trades.map((t) => (t.trade === "dobae" ? `도배 ${gradeLabel(t.grade)}` : items ? `목공(${items})` : tradeLabel(t.trade))).join(" · ");
  const area = `${q.area_basis === "exclusive" ? "전용" : "공급"} ${decText(q.area_m2)}㎡ · ${decText(q.pyeong)}평형${p.size.band ? ` (${sizeLabel(p.size)} 대표 평형)` : ""}`;
  const b = q.budget;
  const canEdit = !p.locked;
  const areaHref = canEdit ? `/start?edit=${p.id}` : undefined;
  const vendorsHref = `/projects/${p.id}/vendors`;
  const one = q.trades.length === 1;

  return (
    <article className={`mj-paper ${s.paper}`} aria-labelledby="doc-t">
      <header className={s.docHead}>
        <div className={s.docName}>
          <p className="mj-small">{title}</p>
          <h1 id="doc-t" className={s.docTitle}>표준견적서</h1>
        </div>
        <dl className={s.meta}>
          <dt>공사 번호</dt><dd className="mj-code">{q.code}</dd>
          <dt>계산</dt><dd className="mj-code">{dotDate(dateSeoul(q.computed_at))}</dd>
        </dl>
      </header>

      <section aria-labelledby="site-t">
        <h2 id="site-t" className="mj-sr">현장 정보</h2>
        <dl className={s.info}>
          <div><dt>현장</dt><dd>{p.region}</dd></div>
          <div><dt>집 종류</dt><dd>아파트 · {p.occupied ? "살면서 공사" : "빈 집(이사 전 공사)"}</dd></div>
          <div><dt>면적</dt><dd className="mj-num">{area}{p.balcony_ext ? " · 발코니 확장" : ""}</dd></div>
          {p.built_year ? <div><dt>준공</dt><dd className="mj-num">{p.built_year}년</dd></div> : null}
          <div><dt>공정</dt><dd>{works}</dd></div>
          <div><dt>공간</dt><dd>{spaces}</dd></div>
        </dl>
      </section>

      <div className={s.sum}>
        <div className={s.sumRow}>
          <p className={s.sumLab}>합계 금액</p>
          <p className={`mj-num ${s.sumVal}`}>{won(q.total)} <span className="mj-small">부가세 포함</span></p>
          <p className={s.ref}>참고 금액 · 업체 견적 아님</p>
        </div>
        {b && b.status === "within" ? <p className="mj-small">넣은 예산({budgetLabel(b.band)}) 안이에요.</p> : null}
        {b && b.status === "over" && b.over_by != null ? (
          <>
            <p className={`mj-num ${s.over}`}>넣은 예산({budgetLabel(b.band)})보다 {won(b.over_by)} 많아요</p>
            {canEdit ? (
              <div className={s.overActs}>
                {p.trades.dobae && p.trades.dobae.grade !== "economy" ? <RegradeButton p={p} /> : null}
                <Link className="mj-lnk" href={`/start?edit=${p.id}`}>공정 · 공간 고치기</Link>
              </div>
            ) : null}
            <p className="mj-small">그대로 가려면 &lsquo;업체 고르기&rsquo;를 눌러요.</p>
          </>
        ) : null}
      </div>

      {/* 공정이 하나면 그 공정 카드(폭의 이유 포함)를 여기 두고, 둘이면 합계 범위만 둔다 */}
      {one ? (
        <RangeCard id="rg-one" r={q.trades[0].range} title="예상 범위" point={{ label: "표준견적서", amount: q.total }} areaHref={areaHref} vendorsHref={`${vendorsHref}?trade=${q.trades[0].trade}`} />
      ) : (
        <RangeCard id="rg-total" r={q.range} title="합계 예상 범위" point={{ label: "표준견적서", amount: q.total }} compact />
      )}

      {q.trades.map((t, i) => {
        const name = tradeLabel(t.trade);
        return (
          <section key={t.trade} className={s.trade} aria-labelledby={`t-${t.trade}`}>
            <h2 id={`t-${t.trade}`} className={`mj-h3 ${s.tradeH}`}>
              {i + 1}. {tradeName(t)}
              {t.trade === "mokgong" && items ? <span className={s.tradeSub}>{items}</span> : null}
            </h2>
            <div className="mj-table-box" role="region" tabIndex={0} aria-label={`${name} 표준견적서 표, 옆으로 넘겨 볼 수 있어요`}>
              <table className={`mj-table mj-num ${s.tbl}`}>
                <caption className="mj-sr">{name} 표준견적서. 줄마다 수량, 단가, 금액, 포함 상태</caption>
                <thead>
                  <tr><th scope="col">줄</th><th scope="col" className="r">수량</th><th scope="col" className="r">단가(원)</th><th scope="col" className="r">금액(원)</th><th scope="col">포함 상태</th></tr>
                </thead>
                <tbody>
                  {t.lines.map((l) => (
                    <tr key={l.key}>
                      <th scope="row">{l.name}</th>
                      <td className="r">{l.qty != null ? `${decText(l.qty)}${l.unit}` : <None what="수량" />}</td>
                      <td className="r">{l.unit_price != null ? numText(l.unit_price) : <None what="단가" />}</td>
                      <td className={`r${outsideTotal(l.state) ? ` ${s.paren}` : ""}`}><Amount l={l} /></td>
                      <td><LineState state={l.state} /></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={3}>{name} 소계</th>
                    <td className="r">{numText(t.supply)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
            {/* 계산할 때 잡은 것(notes)은 저장만 하고, 화면에는 한 줄로 알린다 */}
            <p className={`mj-small ${s.est}`}>
              {Number(t.space_share) < 1 ? `고른 공간만 집 전체의 약 ${shareText(t.space_share)}로 잡았어요. ` : ""}수량은 평형으로 어림했어요. 실측 때 다시 재요.
            </p>
            {one ? null : (
              <RangeCard id={`rg-${t.trade}`} r={t.range} title={`${name} 예상 범위`} point={{ label: "표준견적서", amount: t.total }} areaHref={areaHref} vendorsHref={`${vendorsHref}?trade=${t.trade}`} />
            )}
          </section>
        );
      })}

      <section className={s.totWrap} aria-labelledby="tot-t">
        <div className={s.totBox}>
          <h2 id="tot-t" className="mj-sr">합계</h2>
          <p className="mj-small">단위 원</p>
          <dl className={`mj-num ${s.tot}`}>
            <dt>공급가 <span className="mj-small">{q.trades.map((t) => tradeLabel(t.trade)).join(" + ")}</span></dt><dd>{numText(q.supply)}</dd>
            <dt>부가세 <span className="mj-small">10%</span></dt><dd>{numText(q.vat)}</dd>
            <dt className={s.tt}>낼 금액 <span className="mj-small">부가세 포함</span></dt><dd className={s.tt}>{numText(q.total)}</dd>
          </dl>
          <p className="mj-small">공공 기준: 표준시장단가 · 시중노임단가 · 조달청 가격정보</p>
        </div>
      </section>

    </article>
  );
}

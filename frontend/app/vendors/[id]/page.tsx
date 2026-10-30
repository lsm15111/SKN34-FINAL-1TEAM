import Link from "next/link";
import { notFound } from "next/navigation";
import { SiteHeader } from "@/components/site/SiteHeader";
import { AddToBasket } from "@/components/vendors/AddToBasket";
import { getVendor } from "@/lib/api/vendor";
import { TRADE_LABEL, type Trade } from "@/lib/types";
import { md, won } from "@/lib/format";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const v = await getVendor((await params).id);
  return { title: v ? v.name : "업체" };
}

// 업체 상세 (FFW-09). 가장 강한 근거인 시공 사례를 맨 위에 두고, 정보는 출처별로 나눈다:
// 믿집이 확인한 것(배지) / 업체가 적은 정보 / 믿집 기록 / 사업자 정보(접힘). 전화번호는 보이지 않는다.
export default async function VendorDetail({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ from?: string; trade?: string }> }) {
  const { id } = await params;
  const { from, trade } = await searchParams;
  const v = await getVendor(id);
  if (!v) notFound();
  const t: Trade | null = trade === "dobae" || trade === "mokgong" ? trade : null;
  const fee = v.visitFee ? `실측 방문비 ${won(v.visitFee)}` : "실측 방문비 없음";
  const sat = v.weekend === "sat" ? "토요일에도 작업해요" : "토요일은 쉬어요";
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main">
        {from ? <Link href={`/projects/${from}/vendors${t ? `?trade=${t}` : ""}`}>← 업체 고르기로 돌아가기</Link> : null}
        <div className="mj-split">
          <div className="mj-col">
            <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h1 className="mj-h1">{v.name}</h1>
              <p className="mj-sub">{v.trades.map((x) => TRADE_LABEL[x]).join(" · ")} · {v.areas.slice(0, 3).join(" · ")}{v.areas.length > 3 ? ` 외 ${v.areas.length - 3}곳` : ""}에서 시공해요</p>
              <div className="mj-chips">
                <span className="mj-badge mj-b-ok">사업자 확인 {md(v.registeredAt)}</span>
                {v.license ? <span className="mj-badge mj-b-ok">실내건축공사업 등록 확인</span> : null}
              </div>
              <p>{v.intro}</p>
            </section>

            <section className="mj-panel" aria-labelledby="pf-h">
              <h2 id="pf-h" className="mj-h3">시공 사례 <span className="mj-num" style={{ fontWeight: 500 }}>{v.portfolio.length}건</span></h2>
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))", gap: 12 }}>
                {v.portfolio.map((p) => (
                  <li key={p.title} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div role="img" aria-label={`${p.title} 사진 자리`} style={{ aspectRatio: "4 / 3", maxWidth: "100%", background: "var(--surface-2)", borderRadius: "var(--radius)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--ink-mute)", fontSize: "var(--fs-sm)" }}>사진</div>
                    <b>{p.title}</b>
                    <span className="mj-tiny">{p.caption}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="mj-panel" aria-labelledby="self-h">
              <h2 id="self-h" className="mj-h3">업체가 적은 정보</h2>
              <p className="mj-tiny">믿집이 확인하지 않은 정보예요.</p>
              <dl className="mj-kv">
                <dt>팀</dt><dd className="mj-num">{Object.entries(v.crew).map(([k, n]) => `${TRADE_LABEL[k as Trade]} ${n}명`).join(" · ")}</dd>
                <dt>경력</dt><dd className="mj-num">{v.years}년 ({v.since}년부터)</dd>
                <dt>A/S</dt><dd>{Object.entries(v.as).map(([k, val]) => `${TRADE_LABEL[k as Trade]} ${val}`).join(" · ") || "적지 않았어요"}</dd>
                <dt>토요일</dt><dd>{sat}</dd>
                <dt>실측</dt><dd>{fee}</dd>
              </dl>
              {v.notes.map((n) => <p key={n} className="mj-small">{n}</p>)}
            </section>

            <section className="mj-panel" aria-labelledby="rec-h">
              <h2 id="rec-h" className="mj-h3">믿집 기록</h2>
              <dl className="mj-kv">
                <dt>평점 · 후기</dt><dd className="mj-num">{v.rating.toFixed(1)} · {v.reviews}개</dd>
                <dt>응답</dt><dd>{v.response}</dd>
                <dt>승인일</dt><dd className="mj-num">{md(v.registeredAt)}</dd>
              </dl>
            </section>

            <details className="mj-panel mj-fold">
              <summary>사업자 정보</summary>
              <dl className="mj-kv">
                <dt>상호</dt><dd>{v.name}</dd>
                <dt>대표자</dt><dd>{v.owner}</dd>
                <dt>사업자등록번호</dt><dd className="mj-num">{v.bizNo}</dd>
                <dt>확인한 날</dt><dd className="mj-num">{md(v.registeredAt)}</dd>
              </dl>
              <p className="mj-small">믿집은 거래 당사자가 아니에요. 계약과 대금은 업체와 직접 해요.</p>
            </details>
          </div>

          <aside className="mj-aside mj-panel" aria-labelledby="ct-h">
            <h2 id="ct-h" className="mj-h3">{t ? `이 프로젝트 · ${TRADE_LABEL[t]}` : "시공 지역 · 공정"}</h2>
            <dl className="mj-kv">
              <dt>시공 지역</dt><dd>{v.areas.join(", ")}</dd>
              <dt>가능 공정</dt><dd>{v.trades.map((x) => TRADE_LABEL[x]).join(", ")}</dd>
              <dt>실측</dt><dd>{fee}</dd>
              <dt>토요일</dt><dd>{sat}</dd>
            </dl>
            {from && t && v.trades.includes(t) ? <AddToBasket projectId={from} trade={t} vendorId={v.id} vendorName={v.name} /> : null}
          </aside>
        </div>
      </main>
    </>
  );
}

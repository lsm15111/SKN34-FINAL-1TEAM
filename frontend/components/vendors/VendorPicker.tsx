"use client";
// 업체 고르기 (FFW-06 전체 목록, FFW-07 추천 3곳, FFW-08 검색·필터, FFW-10 공정별 여러 곳 담기)
// 업체 정보는 출처별로 나눠 보인다: 믿집이 확인한 것(배지) / 업체가 적은 정보 / 믿집 기록.
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { Recommendation, Trade, Vendor } from "@/lib/types";
import { TRADE_LABEL } from "@/lib/types";
import { eulReul, won } from "@/lib/format";
import { emptyBasket, readBasket, writeBasket, type Basket } from "./basket";

type Props = {
  projectId: string; region: string; trades: Trade[]; initialTrade: Trade;
  recs: Record<Trade, Recommendation[]>; vendors: Record<Trade, Vendor[]>; requested: Record<Trade, string[]>; stdTotals: Record<Trade, number>;
};

export function VendorPicker({ projectId, region, trades, initialTrade, recs, vendors, requested, stdTotals }: Props) {
  const [trade, setTrade] = useState<Trade>(trades.includes(initialTrade) ? initialTrade : trades[0]);
  const [basket, setBasket] = useState<Basket>(emptyBasket());
  const [q, setQ] = useState("");
  const [onlyArea, setOnlyArea] = useState(true);
  const [onlySat, setOnlySat] = useState(false);
  const [onlyLicense, setOnlyLicense] = useState(false);
  const [sort, setSort] = useState<"reviews" | "rating" | "cases">("reviews");
  const [live, setLive] = useState("");
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => { setBasket(readBasket(projectId)); }, [projectId]);
  const byId = useMemo(() => Object.fromEntries([...vendors.dobae, ...vendors.mokgong].map((v) => [v.id, v])), [vendors]);
  const recIds = recs[trade].map((r) => r.vendorId);

  const list = useMemo(() => {
    let l = vendors[trade];
    if (onlyArea) l = l.filter((v) => v.areas.includes(region));
    if (onlySat) l = l.filter((v) => v.weekend === "sat");
    if (onlyLicense) l = l.filter((v) => v.license);
    if (q.trim()) l = l.filter((v) => v.name.includes(q.trim()));
    const k = { reviews: (v: Vendor) => v.reviews, rating: (v: Vendor) => v.rating, cases: (v: Vendor) => v.portfolio.length }[sort];
    return [...l].sort((a, b) => k(b) - k(a));
  }, [vendors, trade, onlyArea, onlySat, onlyLicense, q, sort, region]);

  function toggle(t: Trade, id: string) {
    const has = basket[t].includes(id);
    const next = { ...basket, [t]: has ? basket[t].filter((x) => x !== id) : [...basket[t], id] };
    setBasket(next);
    writeBasket(projectId, next);
    setLive(`${eulReul(byId[id]?.name ?? "")} ${TRADE_LABEL[t]} ${has ? "요청함에서 뺐어요" : "요청함에 담았어요"}. ${TRADE_LABEL[t]} ${next[t].length}곳`);
  }
  function onTabKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const j = (i + (e.key === "ArrowRight" ? 1 : trades.length - 1)) % trades.length;
    setTrade(trades[j]);
    tabRefs.current[trades[j]]?.focus();
  }
  const total = basket.dobae.length + basket.mokgong.length;

  const addBtn = (id: string) => {
    const on = basket[trade].includes(id);
    return (
      <button type="button" className={`mj-btn mj-btn-sm ${on ? "mj-btn-pri" : "mj-btn-sec"}`} aria-pressed={on} onClick={() => toggle(trade, id)}>
        {on ? "담았어요" : "요청함에 담기"}<span className="mj-sr"> · {byId[id]?.name}</span>
      </button>
    );
  };
  const facts = (v: Vendor) => (
    <>
      <span className="mj-chips">
        <span className="mj-badge mj-b-ok">사업자 확인</span>
        {v.license ? <span className="mj-badge mj-b-ok">실내건축공사업 등록 확인</span> : null}
      </span>
      <span className="mj-small"><span className="mj-src">업체가 적은 정보</span> {v.weekend === "sat" ? "토요일에도 작업해요" : "토요일은 쉬어요"} · {v.visitFee ? `실측 방문비 ${won(v.visitFee)}` : "실측 방문비 없음"} · 경력 {v.years}년</span>
      <span className="mj-small mj-num"><span className="mj-src">믿집 기록</span> 평점 {v.rating.toFixed(1)} · 후기 {v.reviews}개 · 응답 {v.response}</span>
    </>
  );
  const checks = (v: Vendor) => (
    <span className="mj-chips">
      {requested[trade].includes(v.id) ? <span className="mj-badge mj-b-dark">이미 요청함</span> : null}
    </span>
  );

  return (
    <div className="mj-split">
      <div className="mj-col">
        <div role="tablist" aria-label="공정" className="mj-tabs">
          {trades.map((t, i) => (
            <button key={t} ref={(el) => { tabRefs.current[t] = el; }} role="tab" id={`tab-${t}`} aria-controls={`panel-${t}`} aria-selected={trade === t} tabIndex={trade === t ? 0 : -1} onClick={() => setTrade(t)} onKeyDown={(e) => onTabKey(e, i)}>
              {TRADE_LABEL[t]} <span className="mj-badge mj-b-in mj-num">{basket[t].length}곳 담음</span>
            </button>
          ))}
        </div>

        <div role="tabpanel" id={`panel-${trade}`} aria-labelledby={`tab-${trade}`} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <section className="mj-panel" aria-labelledby="rec-h" style={{ borderColor: "var(--accent-pastel)" }}>
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
              <h2 id="rec-h" className="mj-h2">{TRADE_LABEL[trade]} 추천 3곳</h2>
              <span className="mj-tiny">믿집이 고른 이유를 함께 보여 드려요</span>
            </div>
            <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {recs[trade].map((r) => {
                const v = byId[r.vendorId];
                if (!v) return null;
                return (
                  <li key={r.vendorId} className="mj-vendor">
                    <div className="mj-vendor-main">
                      <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}><b style={{ fontSize: "var(--fs-lg)" }}>{v.name}</b><span className="mj-small">{v.areas.slice(0, 3).join(" · ")} 외 · 시공 사례 {v.portfolio.length}건</span></span>
                      {facts(v)}
                      {r.pros.length ? <div className="mj-small"><span className="mj-src">믿집이 고른 이유</span><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{r.pros.map((x) => <li key={x}>{x}</li>)}</ul></div> : null}
                      {r.cons.length ? <p className="mj-small" style={{ color: "var(--warn)" }}>살펴볼 점 · {r.cons.join(" · ")}</p> : null}
                      {checks(v)}
                    </div>
                    <div className="mj-vendor-act">{addBtn(v.id)}<Link href={`/vendors/${v.id}?from=${projectId}&trade=${trade}`} className="mj-btn mj-btn-ghost mj-btn-sm">업체 정보 보기</Link></div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="mj-panel" aria-labelledby="all-h">
            <h2 id="all-h" className="mj-h2">{TRADE_LABEL[trade]} 전체 업체 <span className="mj-num" style={{ fontWeight: 500 }}>{list.length}곳</span></h2>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
              <div className="mj-field" style={{ flex: "1 1 220px" }}>
                <label className="mj-label" htmlFor="vq">업체 이름으로 찾기</label>
                <input id="vq" className="mj-input" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <div className="mj-field" style={{ flex: "0 1 200px" }}>
                <label className="mj-label" htmlFor="vsort">정렬</label>
                <select id="vsort" className="mj-select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                  <option value="reviews">후기 많은 순</option><option value="rating">평점 높은 순</option><option value="cases">시공 사례 많은 순</option>
                </select>
              </div>
            </div>
            <div className="mj-choices mj-choices-2">
              <label className="mj-choice"><input type="checkbox" checked={onlyArea} onChange={(e) => setOnlyArea(e.target.checked)} /><span className="mj-choice-main"><span className="mj-choice-title">{region}에서 시공하는 업체만</span></span></label>
              <label className="mj-choice"><input type="checkbox" checked={onlySat} onChange={(e) => setOnlySat(e.target.checked)} /><span className="mj-choice-main"><span className="mj-choice-title">토요일에도 작업하는 업체만</span></span></label>
              <label className="mj-choice"><input type="checkbox" checked={onlyLicense} onChange={(e) => setOnlyLicense(e.target.checked)} /><span className="mj-choice-main"><span className="mj-choice-title">실내건축공사업 등록 확인 업체만</span></span></label>
            </div>
            <p className="mj-small" aria-live="polite">{list.length ? `조건에 맞는 업체 ${list.length}곳` : "조건에 맞는 업체가 없어요. 필터를 줄여 보세요."}</p>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {list.map((v) => (
                <li key={v.id} className="mj-vendor">
                  <div className="mj-vendor-main">
                    <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}><b style={{ fontSize: "var(--fs-lg)" }}>{v.name}</b>{recIds.includes(v.id) ? <span className="mj-badge mj-b-in">추천</span> : null}<span className="mj-small">{v.trades.map((t) => TRADE_LABEL[t]).join(" · ")} · 시공 사례 {v.portfolio.length}건</span></span>
                    {facts(v)}
                    <span className="mj-tiny">시공 지역 · {v.areas.join(" · ")}</span>
                    {checks(v)}
                  </div>
                  <div className="mj-vendor-act">{addBtn(v.id)}<Link href={`/vendors/${v.id}?from=${projectId}&trade=${trade}`} className="mj-btn mj-btn-ghost mj-btn-sm">업체 정보 보기</Link></div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      <aside className="mj-aside mj-panel" aria-labelledby="bk-h">
        <h2 id="bk-h" className="mj-h3">견적 요청함</h2>
        <p className="mj-sr" aria-live="polite">{live}</p>
        {trades.map((t) => (
          <div key={t} style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 10, borderBottom: "1px solid var(--line)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><b>{TRADE_LABEL[t]}</b><span className="mj-tiny mj-num">표준견적 {won(stdTotals[t])}</span></div>
            {basket[t].length ? (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {basket[t].map((id) => (
                  <li key={id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <span>{byId[id]?.name}</span>
                    <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" onClick={() => toggle(t, id)}>빼기<span className="mj-sr"> · {byId[id]?.name}</span></button>
                  </li>
                ))}
              </ul>
            ) : <span className="mj-small">아직 담은 업체가 없어요</span>}
          </div>
        ))}
        <p className="mj-tiny">같은 조건(우리 집 정보 · 공정 · 사진)으로 담은 업체 모두에 요청해요.</p>
        {total ? (
          <Link href={`/projects/${projectId}/request`} className="mj-btn mj-btn-pri">가견적 요청 확인하기 · {total}곳</Link>
        ) : (
          <button type="button" className="mj-btn mj-btn-pri" aria-disabled="true" disabled>가견적 요청 확인하기</button>
        )}
      </aside>
    </div>
  );
}

"use client";
// 업체 정보 관리: 상호 · 홈페이지, 맡는 공정(견적 받기와 같은 묶음 카드), 일하는 지역(시 · 도 → 시 · 군 · 구 여러 곳),
// 포트폴리오 링크. 저장은 PUT /vendor/profile로 통째로 바꾸고 API가 다시 검사한다.
// 공정 · 지역이 있어야 그 공정 · 시 · 군 · 구의 고객 가견적 후보에 나온다.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { TRADE_DESC, TRADE_GROUPS } from "@/lib/labels";
import { SIDO, regionLabel } from "@/lib/mock/regions";
import { TRADE_LABEL } from "@/lib/types";
import s from "./VendorProfileForm.module.css";

type Profile = Schemas["VendorProfileOut"];
type Area = Schemas["AreaIn"];
type Field = "name" | "site" | "trades" | "areas" | "links";

// API 한도와 같다 (API가 다시 검사한다)
const MAX_AREAS = 50;
const MAX_LINKS = 5;

const areaKey = (a: Area) => `${a.sido}|${a.sgg}`;
// 고른 지역을 보이는 순서: 시 · 도 목록 순서, 그 안에서는 시 · 군 · 구 순서
const ORDER = new Map(SIDO.flatMap((x) => x.groups.flatMap((g) => g.items.map((n) => `${x.id}|${n}`))).map((k, i) => [k, i]));
const sortAreas = (list: Area[]) => [...list].sort((a, b) => (ORDER.get(areaKey(a)) ?? 0) - (ORDER.get(areaKey(b)) ?? 0));
const rows = (urls: string[]) => (urls.length ? urls : [""]);

/** http · https 주소인지 */
function isLink(u: string) {
  if (/\s/.test(u)) return false;
  try {
    const x = new URL(u);
    return (x.protocol === "https:" || x.protocol === "http:") && !!x.hostname;
  } catch {
    return false;
  }
}

/** 고칠 칸으로 커서를 옮긴다 (묶음이면 그 안의 첫 칸) */
function focusField(id: string) {
  const el = document.getElementById(id);
  (el instanceof HTMLInputElement ? el : el?.querySelector("input"))?.focus();
}

export function VendorProfileForm({ initial }: { initial: Profile }) {
  const router = useRouter();
  const [name, setName] = useState(initial.biz_name ?? "");
  const [site, setSite] = useState(initial.site_url ?? "");
  const [trades, setTrades] = useState<string[]>(initial.trades);
  const [areas, setAreas] = useState<Area[]>(() => sortAreas(initial.areas));
  const [links, setLinks] = useState<string[]>(rows(initial.portfolio_urls));
  const [sidoId, setSidoId] = useState(() => sortAreas(initial.areas)[0]?.sido ?? "");
  const [areaMsg, setAreaMsg] = useState("");
  const [err, setErr] = useState<{ field?: Field; text: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const sido = SIDO.find((x) => x.id === sidoId);
  const picked = new Set(areas.map(areaKey));
  const sidoAll = sido ? sido.groups.flatMap((g) => g.items).map((sgg) => ({ sido: sido.id, sgg })) : [];
  const sidoPicked = sidoAll.filter((a) => picked.has(areaKey(a))).length;

  // 고치기 시작하면 지난 저장 결과 · 오류 글을 지운다 (저장할 때 다시 검사한다)
  const changed = () => { setMsg(""); setErr(null); };
  const errAt = (f: Field) => (err?.field === f ? <p id={`vp-${f}-err`} className="mj-error" role="alert">{err.text}</p> : null);
  const invalid = (f: Field) => (err?.field === f ? { "aria-invalid": true, "aria-describedby": `vp-${f}-err` } : {});

  function toggleTrade(t: string, on: boolean) {
    changed();
    setTrades((old) => (on ? [...old, t] : old.filter((x) => x !== t)));
  }

  function toggleArea(a: Area, on: boolean) {
    changed();
    setAreaMsg("");
    if (!on) { setAreas((old) => old.filter((x) => areaKey(x) !== areaKey(a))); return; }
    if (areas.length >= MAX_AREAS) { setAreaMsg(`지역은 ${MAX_AREAS}곳까지 고를 수 있어요.`); return; }
    setAreas((old) => sortAreas([...old, a]));
  }

  function pickAll(on: boolean) {
    if (!sido) return;
    changed();
    setAreaMsg("");
    if (!on) { setAreas((old) => old.filter((x) => x.sido !== sido.id)); return; }
    const add = sidoAll.filter((a) => !picked.has(areaKey(a)));
    if (areas.length + add.length > MAX_AREAS) { setAreaMsg(`모두 고르면 ${MAX_AREAS}곳이 넘어요. 실제로 가는 곳만 골라 주세요.`); return; }
    setAreas((old) => sortAreas([...old, ...add]));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    const urls = links.map((u) => u.trim()).filter(Boolean);
    const badLink = links.findIndex((u) => u.trim() && !isLink(u.trim()));
    const problem: { field: Field; text: string } | null =
      !name.trim() ? { field: "name", text: "상호를 적어 주세요." }
      : site.trim() && !isLink(site.trim()) ? { field: "site", text: "홈페이지 주소는 http:// 또는 https://로 시작해야 해요." }
      : !trades.length ? { field: "trades", text: "맡는 공정을 하나 이상 골라 주세요." }
      : !areas.length ? { field: "areas", text: "일하는 지역을 하나 이상 골라 주세요." }
      : badLink >= 0 ? { field: "links", text: "포트폴리오 링크는 http:// 또는 https://로 시작해야 해요." }
      : null;
    if (problem) {
      setErr(problem);
      focusField(problem.field === "links" ? `vp-link-${badLink}` : `vp-${problem.field}`);
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const got = await call<Profile>("PUT", "/vendor/profile", { biz_name: name.trim(), site_url: site.trim() || null, trades, areas, portfolio_urls: urls });
      setName(got.biz_name ?? "");
      setSite(got.site_url ?? "");
      setTrades(got.trades);
      setAreas(sortAreas(got.areas));
      setLinks(rows(got.portfolio_urls));
      setMsg("저장했어요. 이제 고른 공정 · 지역의 고객에게 가견적 후보로 보여요.");
      router.refresh();
    } catch (er) {
      setErr({ text: errorText(er) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={s.form} onSubmit={save} noValidate aria-label="업체 정보">
      <section className="mj-panel" aria-labelledby="vp-basic-h">
        <h2 id="vp-basic-h" className="mj-h3">기본 정보</h2>
        <div className="mj-field">
          <label className="mj-label" htmlFor="vp-name">상호</label>
          <input id="vp-name" className="mj-input" maxLength={100} autoComplete="organization" value={name} onChange={(e) => { changed(); setName(e.target.value); }} {...invalid("name")} />
          <p className="mj-hint">가견적 후보에 이 이름으로 보여요.</p>
          {errAt("name")}
        </div>
        <div className="mj-field">
          <label className="mj-label" htmlFor="vp-site">홈페이지 <span className="mj-opt">(선택)</span></label>
          <input id="vp-site" type="url" inputMode="url" className="mj-input" maxLength={300} placeholder="https://" autoComplete="url" value={site} onChange={(e) => { changed(); setSite(e.target.value); }} {...invalid("site")} />
          {errAt("site")}
        </div>
      </section>

      <div className="mj-panel">
        <fieldset id="vp-trades" className="mj-fieldset" aria-describedby="vp-trades-hint">
          <legend className={`mj-h3 ${s.legend}`}>맡는 공정</legend>
          <p id="vp-trades-hint" className="mj-small">고객이 견적 받기에서 고르는 공정과 같아요. 하는 공정을 모두 골라 주세요.</p>
          {errAt("trades")}
          {TRADE_GROUPS.map((g) => (
            <fieldset key={g.label} className="mj-fieldset">
              <legend className="mj-label">{g.label}</legend>
              <div className="mj-choices mj-choices-2">
                {g.keys.map((t) => (
                  <label key={t} className="mj-choice">
                    <input type="checkbox" checked={trades.includes(t)} onChange={(e) => toggleTrade(t, e.target.checked)} />
                    <span className="mj-choice-main"><span className="mj-choice-title">{TRADE_LABEL[t]}</span><span className="mj-choice-desc">{TRADE_DESC[t]}</span></span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </fieldset>
      </div>

      <div className="mj-panel">
        <fieldset id="vp-areas" className="mj-fieldset" aria-describedby="vp-areas-hint">
          <legend className={`mj-h3 ${s.legend}`}>일하는 지역</legend>
          <p id="vp-areas-hint" className="mj-small">실제로 가는 시 · 군 · 구만 골라 주세요. {MAX_AREAS}곳까지 고를 수 있고, 이 지역 고객에게만 후보로 보여요.</p>
          <div className={s.picked}>
            <p className="mj-label">고른 지역 <span className="mj-num">{areas.length}</span>곳</p>
            {areas.length ? (
              <ul className={s.chips}>
                {areas.map((a) => (
                  <li key={areaKey(a)}>
                    <button type="button" className={s.chip} onClick={() => toggleArea(a, false)}>
                      {regionLabel(a.sido, a.sgg)}<span className="mj-sr"> 빼기</span>
                      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="mj-small">아직 고른 지역이 없어요. 아래에서 시 · 도를 먼저 골라 주세요.</p>}
            {errAt("areas")}
          </div>
          <fieldset className="mj-fieldset">
            <legend className="mj-label">시 · 도</legend>
            <div className="mj-pick">
              {SIDO.map((x) => {
                const n = areas.filter((a) => a.sido === x.id).length;
                return (
                  <label key={x.id} className="mj-pick-i">
                    <input type="radio" name="vp-sido" checked={sidoId === x.id} onChange={() => { setSidoId(x.id); setAreaMsg(""); }} />
                    <span>{x.name}{n ? <>{" "}<span className={s.count}>{n}<span className="mj-sr">곳 고름</span></span></> : null}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
          {sido ? (
            <fieldset className="mj-fieldset">
              <legend className="mj-label">{sido.name} 시 · 군 · 구</legend>
              {sido.id === "jeonnam-gwangju" ? <p className="mj-small">2026년 7월 광주와 전남이 전남광주통합특별시로 합쳐졌어요.</p> : null}
              <div className="mj-btn-row">
                {sidoPicked < sidoAll.length ? <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => pickAll(true)}>{sido.name} 모두 고르기</button> : null}
                {sidoPicked ? <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => pickAll(false)}>{sido.name} 모두 빼기</button> : null}
              </div>
              <p className="mj-small" role="status">{areaMsg}</p>
              {sido.groups.map((g, gi) => (
                <div key={g.prefix || gi} className={s.group}>
                  {g.label ? <span className={s.groupLabel}>{g.label}</span> : null}
                  <div className="mj-pick">
                    {g.items.map((sgg) => (
                      <label key={sgg} className="mj-pick-i">
                        <input type="checkbox" checked={picked.has(`${sido.id}|${sgg}`)} onChange={(e) => toggleArea({ sido: sido.id, sgg }, e.target.checked)} />
                        <span>{sgg}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </fieldset>
          ) : null}
        </fieldset>
      </div>

      <div className="mj-panel">
        <fieldset id="vp-links" className="mj-fieldset" aria-describedby="vp-links-hint">
          <legend className={`mj-h3 ${s.legend}`}>포트폴리오 링크 <span className="mj-opt">(선택)</span></legend>
          <p id="vp-links-hint" className="mj-small">블로그 · 인스타그램 · 홈페이지에 올린 시공 사례 주소를 넣어 주세요. 고객이 가견적 후보에서 눌러 볼 수 있어요. {MAX_LINKS}개까지예요.</p>
          <ul className={s.links}>
            {links.map((u, i) => (
              <li key={i} className={s.linkRow}>
                <label className="mj-sr" htmlFor={`vp-link-${i}`}>포트폴리오 링크 {i + 1}</label>
                <input id={`vp-link-${i}`} type="url" inputMode="url" className="mj-input" maxLength={300} placeholder="https://" value={u} onChange={(e) => { changed(); setLinks((old) => old.map((x, j) => (j === i ? e.target.value : x))); }} {...(err?.field === "links" && u.trim() && !isLink(u.trim()) ? invalid("links") : {})} />
                <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => { changed(); setLinks((old) => rows(old.filter((_, j) => j !== i))); }}>빼기<span className="mj-sr"> · 링크 {i + 1}</span></button>
              </li>
            ))}
          </ul>
          <div className="mj-btn-row">
            <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" disabled={links.length >= MAX_LINKS} onClick={() => setLinks((old) => [...old, ""])}>+ 링크 더하기</button>
          </div>
          {errAt("links")}
        </fieldset>
      </div>

      <div className={s.save}>
        {err && !err.field ? <p className="mj-error" role="alert">{err.text}</p> : null}
        <p className="mj-small" role="status">{msg}</p>
        <div className="mj-btn-row">
          <button type="submit" className="mj-btn mj-btn-pri" disabled={busy}>{busy ? "저장하는 중이에요" : "저장하기"}</button>
        </div>
      </div>
    </form>
  );
}

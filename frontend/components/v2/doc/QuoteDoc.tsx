"use client";
// 표준견적서 문서 (v10 quoteDocEl + 2494 덧씌움 · customerGuide · vendorGuide · preciseTable · refTable · bandLine(v5) · gapList · marketTable
// · vendorQuoteForm · customerCompare). 금액은 모두 API 응답(quote · estimate · entered)을 보이기만 한다.
import { useEffect, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { CAT, manwon } from "../data";
import { todaySeoul } from "../dates";
import { F, toast } from "../engine";
import { scopeCats } from "../flow";
import { S, touch, V3 } from "../store";
import { type Band, type Entered, type Estimate, fetchEntered, fetchEstimate, fetchQuote, materials, type Precise, type Quote, type RefTrade, type VatMode } from "./api";
import { QuoteCheck } from "./QuoteCheck";
import { BASIS_KO, DateField, Fld, fmt, log, signWon, STATE_KO } from "./shared";

/* 업체 단가 · 확인 상태 · 받은 실측 견적서 (V3에 둔다) */
type Prices = Record<string, number | undefined>;
export type VqEntry = Entered & { mode: VatMode; days: number | null; valid: string | null; file: string; ver: number; at: string };
const vpOf = (trade: string) => ((V3.vp as Record<string, Prices>)[trade] ??= {});
/** 확인 상태. resetState가 V3 칸을 새 객체로 바꾸므로 매번 V3에서 읽는다 */
const vps = () => V3.vpState as Record<string, "draft" | "confirmed" | undefined>;
const vq = () => V3.vq as Record<string, VqEntry>;
/** 확인한 단가로 받은 가견적 (공정별) */
const EST: Record<string, Estimate> = {};
const priceKey = (t: Precise, key: string) => (key === "paper" ? `paper_${t.grade || "basic"}` : key);

/** 견적을 다시 받는다 (v10 buildQuote). 확인한 단가의 가견적도 새 수량으로 다시 받는다 */
export async function loadQuote() {
  const q = await fetchQuote();
  V3.quote = q;
  await Promise.all(
    q.precise
      .filter((t) => vps()[t.trade] === "confirmed")
      .map((t) =>
        fetchEstimate(t, vpOf(t.trade))
          .then((e) => {
            EST[t.trade] = e;
          })
          .catch(() => {
            delete EST[t.trade];
          }),
      ),
  );
  return q;
}

/** 문서 겹창 안 본문 (v10 openQuoteDoc의 body.refresh · rerenderDoc) */
export function QuoteDocBody() {
  const [q, setQ] = useState<Quote | null>((V3.quote as Quote | null) ?? null);
  const [err, setErr] = useState("");
  const [, setN] = useState(0);
  const bump = () => setN((n) => n + 1);
  const reload = async () => {
    try {
      setQ(await loadQuote());
      setErr("");
    } catch (e) {
      setErr(errorText(e));
    }
  };
  useEffect(() => {
    reload();
  }, []);
  if (!q) return <p className="muted">{err || "견적서를 계산하는 중이에요…"}</p>;
  return (
    <>
      {err ? <p className="warn-line">{err}</p> : null}
      <QuoteDocEl q={q} reload={reload} bump={bump} />
    </>
  );
}

/** 목공 상태 (v10 mok10St). 없으면 B(F.mok10Sync)가 만들고, 그래도 없으면 등급 처음 값(GET /mvp/materials)으로 만든다 */
async function ensureMok() {
  if (!S.mok10) F.mok10Sync?.();
  if (!S.mok10) {
    const m = await materials();
    const i = m.grades[S.tier] || m.grades.basic;
    S.mok10 = {
      door: { mode: "none", pick: null, count: null },
      slide: { n: 0, pick: "door-yerim-hidden-sliding-set" },
      hidden: { n: 0, pick: "door-yerim-hidden-set" },
      molding: { type: i.molding_type as "flat" | "step" | "minus" | "none", pick: i.molding },
      base: { pick: i.base },
      extras: {},
    };
  }
  return S.mok10;
}
/** 방문 교체를 켜면 그 방식에 맞는 처음 자재 (v10 mok10DefaultPick · MOK10.prod kind 확인) */
async function doorPickFor(mode: string, pick: string | null) {
  const m = await materials().catch(() => null);
  if (!m) return pick;
  const want = mode === "replace" ? "door_set" : "door_leaf";
  if (m.products.find((p) => p.id === pick)?.kind === want) return pick;
  const g = m.grades[S.tier] || m.grades.basic;
  return g ? (mode === "replace" ? g.door_set : g.leaf) : pick;
}
/** 목공 칸을 바꾼 뒤: 보드 · 저장 · 견적 다시 받기 */
async function mokSet(fn: (s: NonNullable<typeof S.mok10>) => void | Promise<void>, reload: () => void) {
  try {
    const s = await ensureMok();
    await fn(s);
  } catch (e) {
    toast(errorText(e));
    return;
  }
  F.mok10Sync?.();
  touch();
  reload();
}

function QuoteDocEl({ q, reload, bump }: { q: Quote; reload: () => void; bump: () => void }) {
  const vendor = V3.role === "vendor";
  const inp = q.inp;
  const carp = !!S.scope.kind && scopeCats().some((c) => c.id === "carpentry");
  const head = (
    <div className="doc-meta">
      <dl>
        <dt>견적 번호</dt>
        <dd>{q.code}</dd>
        <dt>계산한 날</dt>
        <dd>{q.at}</dd>
        <dt>현장</dt>
        <dd>{`아파트 · ${inp.occupied ? "살면서 공사" : "빈 집(이사 전 공사)"}`}</dd>
        <dt>면적</dt>
        <dd>{`공급 ${inp.area_m2}㎡ · ${inp.py}평${inp.balcony ? " · 발코니 확장" : ""}`}</dd>
        {vendor ? (
          <>
            <dt>산식 · 단가 버전</dt>
            <dd>{`${q.formula_version ?? "2026.11.1"} · ${(q.price_ver ?? "2026H2") === "2026H2" ? "2026 하반기" : q.price_ver}`}</dd>
          </>
        ) : null}
      </dl>
      <div className="doc-opts">
        <label className="chk">
          <input
            type="checkbox"
            defaultChecked={inp.balcony}
            onChange={(e) => {
              if (S.plan?.kind === "apt") {
                S.plan.expanded = e.target.checked;
                touch();
              } else V3.balcony = e.target.checked;
              reload();
            }}
          />
          발코니 확장
        </label>
        {carp ? (
          <>
            <label className="chk">
              <input
                type="checkbox"
                defaultChecked={inp.mok.includes("door")}
                onChange={(e) => {
                  const on = e.target.checked;
                  mokSet(async (s) => {
                    s.door.mode = on ? (s.door.mode !== "none" ? s.door.mode : "replace") : "none";
                    if (s.door.mode !== "none") s.door.pick = await doorPickFor(s.door.mode, s.door.pick);
                  }, reload);
                }}
              />
              방문 교체
            </label>
            {inp.mok.includes("door") ? (
              <label className="chk">
                방문
                <input
                  className="inp sm"
                  type="number"
                  min="1"
                  max="8"
                  defaultValue={inp.doors}
                  onChange={(e) => {
                    const v = Math.max(1, Math.min(8, +e.target.value || 1));
                    mokSet((s) => {
                      s.door.count = v;
                    }, reload);
                  }}
                />
                개
              </label>
            ) : null}
            <label className="chk">
              <input
                type="checkbox"
                defaultChecked={S.mok10?.extras.flatten_overlay != null}
                onChange={(e) => {
                  const on = e.target.checked;
                  mokSet((s) => {
                    if (on) s.extras.flatten_overlay = true;
                    else delete s.extras.flatten_overlay;
                  }, reload);
                }}
              />
              천장 평탄화
            </label>
          </>
        ) : null}
      </div>
    </div>
  );
  const budget = S.budget ? S.budget * 10000 : null;
  const pko = q.precise.map((t) => t.ko);
  const sumBox = (
    <div className="doc-sum">
      {q.precise.length ? (
        <>
          <div className="rowsum">
            <span>{`공급가 · 부가세 빼기 전 (${pko.join(" + ")})`}</span>
            <b className="num">{fmt(q.supply) + "원"}</b>
          </div>
          <div className="rowsum">
            <span>부가세 10%</span>
            <b className="num">{fmt(q.vat) + "원"}</b>
          </div>
          <div className="rowsum big">
            <span>낼 금액 (부가세 포함)</span>
            <b className="num">{fmt(q.total) + "원"}</b>
          </div>
        </>
      ) : null}
      {q.band ? (
        <div className="rowsum band">
          <span>{`업체 견적 보통 범위 (${pko.join(" · ")}, 부가세 별도)`}</span>
          <b className="num">{`${fmt(q.band.lo)} ~ ${fmt(q.band.hi)}원`}</b>
        </div>
      ) : null}
      {q.ref.length ? (
        <div className="rowsum">
          <span>참고 공정 (부가세 포함 범위)</span>
          <b className="num">{`${fmt(q.rlo)} ~ ${fmt(q.rhi)}원`}</b>
        </div>
      ) : null}
      {q.band ? <p className="muted">업체 실측 견적서가 오면 그 금액으로 다시 비교해요.</p> : null}
      {budget && S.budget ? (
        <p className={q.all_hi > budget ? "warn-line" : "ok-line"}>
          {q.all_lo > budget
            ? `넣은 예산(${manwon(S.budget)})보다 많아요. 등급을 낮추거나 공정을 줄여 보세요.`
            : q.all_hi > budget
              ? `넣은 예산(${manwon(S.budget)}) 근처예요. 참고 공정 금액에 따라 넘을 수 있어요.`
              : `넣은 예산(${manwon(S.budget)}) 안이에요.`}
        </p>
      ) : null}
      <p className="muted">
        {`공공 기준: 표준시장단가 · 시중노임단가 · 조달청 가격정보 (2026 하반기). 참고 금액 · 업체 견적 아님. ${inp.measured ? `벽 · 천장 · 몰딩 · 걸레받이 수량은 도면 ${inp.measured.name}에서 방마다 재서 어림했어요` : "수량은 평형으로 어림했어요"}. 실측 때 다시 재요.`}
      </p>
    </div>
  );
  return (
    <div>
      {head}
      {vendor ? <VendorGuide /> : <CustomerGuide q={q} />}
      {q.precise.map((t) => <PreciseTable key={t.trade} t={t} vendor={vendor} bump={bump} />)}
      {q.ref.length ? (
        <h4 className="doc-sec">
          참고 공정<small>시장 근거 범위 · 업체 실측 견적서에서 정해져요</small>
        </h4>
      ) : null}
      {q.ref.map((t) => <RefTable key={t.cat} t={t} vendor={vendor} />)}
      {q.missing.length ? <p className="muted">{`${q.missing.map((c) => CAT[c]?.ko ?? c).join(" · ")}는 아직 참고 산식이 없어 업체 견적에서 정해요.`}</p> : null}
      {sumBox}
      {vendor ? (
        <VendorQuoteForm q={q} />
      ) : (
        <>
          <QuoteCheck q={q} />
          <CustomerCompare q={q} />
        </>
      )}
    </div>
  );
}

function CustomerGuide({ q }: { q: Quote }) {
  return (
    <div className="doc-guide">
      <b>이렇게 읽어요</b>
      <ul>
        <li>{"'포함' 줄만 합계에 들어가요. '실측 후' 줄은 집을 본 뒤 업체가 정해요."}</li>
        <li>도배 · 목공은 공공 단가로 계산했고, 나머지는 시장 가격 범위예요.</li>
        {q.band ? <li>{"업체 견적은 공공 단가와 달라서 도배 · 목공 아래에 '업체 견적은 보통' 범위를 같이 적었어요. 받은 견적은 맨 아래 [받은 견적 맞춰 보기]에 넣어 보세요."}</li> : null}
        <li>업체 견적이 이 금액과 많이 다르면 어느 줄이 다른지 물어보세요.</li>
      </ul>
      <dl className="gloss">
        <dt>품</dt>
        <dd>기능공 1명이 하루에 하는 일의 양이에요. 품 3.5면 1명이 3.5일 하는 일이에요.</dd>
        <dt>식</dt>
        <dd>수량을 세지 않고 한 묶음으로 계산하는 줄이에요.</dd>
        <dt>공급가</dt>
        <dd>부가세를 빼기 전 금액이에요.</dd>
      </dl>
    </div>
  );
}

function VendorGuide() {
  return (
    <div className="doc-guide vendor">
      <b>업체 확인용</b>
      <ul>
        <li>줄마다 산식 · 근거 · 단가 버전을 보여 줘요. 수량은 평형 어림이라 실측 값으로 바꿔 견적서를 내요.</li>
        <li>{"'내 단가'를 넣고 [확인했어요]를 누르면 그 단가 × 이 집 수량으로 가견적이 고객에게 보여요. 확인 전에는 안 보여요."}</li>
        <li>{"수량이 '식'인 줄(짐 있는 집 할증 등)은 단가를 받지 않아요. 가견적에서 빠지고 실측 견적서에서 정해요."}</li>
        <li>실측 뒤에는 내 양식 파일과 요약 칸(낼 금액 · 부가세 방식 · 기간 · 유효기간)으로 실측 견적서를 보내요.</li>
      </ul>
    </div>
  );
}

/** 고객 보기: 줄 표는 접어 두고 소계만 먼저 (2494 덧씌움) */
function Tbl({ collapse, n, sub, children }: { collapse: boolean; n: number; sub: string; children: React.ReactNode }) {
  const tbl = <div className="tbl">{children}</div>;
  if (!collapse) return tbl;
  return (
    <details>
      <summary>{(sub ? `소계 ${sub} (부가세 빼기 전) · ` : "") + `줄 ${n}개 자세히 보기`}</summary>
      {tbl}
    </details>
  );
}

function PreciseTable({ t, vendor, bump }: { t: Precise; vendor: boolean; bump: () => void }) {
  const vp = vpOf(t.trade);
  const est = EST[t.trade];
  const rows = t.lines.map((l) => {
    const counted = l.state === "included" || l.state === "separate";
    const pk = priceKey(t, l.key);
    return (
      <tr key={l.key} className={counted ? "" : "dim"}>
        <td>
          <b>{l.name}</b>
          {vendor && l.calc ? <div className="calc">{l.calc}</div> : null}
          {vendor ? (
            <div className="src">
              <span className={"basis b-" + l.basis}>{BASIS_KO[l.basis]}</span> {l.source}
            </div>
          ) : null}
        </td>
        <td className="num" data-l="수량">{l.qty != null ? `${fmt(l.qty)} ${l.unit}` : l.unit}</td>
        <td className="num" data-l="단가(원)">{l.unit_price != null ? fmt(l.unit_price) : "—"}</td>
        <td className="num amt" data-l="금액(원)">{l.amount != null ? (counted ? fmt(l.amount) : `(${fmt(l.amount)})`) : "—"}</td>
        <td className="stc">
          <span className={"st st-" + l.state}>{STATE_KO[l.state]}</span>
          {!counted && l.amount != null ? <small className="muted"> 합계 밖</small> : null}
        </td>
        {vendor ? (
          <td className="vin" data-l="내 단가">
            {counted && l.qty != null ? (
              <input
                className="inp sm"
                type="number"
                min="0"
                step="1"
                aria-label={`${l.name} 내 단가`}
                defaultValue={vp[pk] ?? ""}
                placeholder={fmt(l.unit_price)}
                onInput={(e) => {
                  const v = e.currentTarget.value;
                  vp[pk] = v === "" ? undefined : Math.max(0, Math.min(1e7, +v));
                  vps()[t.trade] = "draft";
                }}
              />
            ) : null}
          </td>
        ) : null}
      </tr>
    );
  });
  return (
    <section className="doc-trade">
      <h4 className="doc-sec">
        {t.ko}
        <small>{`품 ${t.man_days} · ${t.ko === "도배" ? "도배공" : "목수"} ${t.crew}명 · ${t.days}일`}</small>
      </h4>
      <Tbl collapse={!vendor} n={t.lines.length} sub={`${fmt(t.supply)}원`}>
        <table>
          <thead>
            <tr>
              <th>줄</th>
              <th>수량</th>
              <th>단가(원)</th>
              <th>금액(원)</th>
              <th>포함 상태</th>
              {vendor ? <th>내 단가</th> : null}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
          <tfoot>
            <tr>
              <td>{`${t.ko} 소계`}</td>
              <td className="hide-m" />
              <td className="hide-m" />
              <td className="num amt">{fmt(t.supply) + "원"}</td>
              <td className="stc">공급가</td>
              {vendor ? <td className="hide-m" /> : null}
            </tr>
          </tfoot>
        </table>
      </Tbl>
      <ul className="notes">
        {t.notes.map((n) => <li key={n}>{n}</li>)}
      </ul>
      {vendor ? (
        <div className="row">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              vps()[t.trade] = "draft";
              toast("단가를 저장했어요 · 아직 고객에게 안 보여요");
              bump();
            }}
          >
            단가 저장
          </button>
          <button
            type="button"
            className="btn btn-pri btn-sm"
            onClick={async () => {
              let e: Estimate;
              try {
                e = await fetchEstimate(t, vp);
              } catch (x) {
                toast(errorText(x));
                return;
              }
              if (!e.ok) {
                toast(e.why);
                return;
              }
              EST[t.trade] = e;
              vps()[t.trade] = "confirmed";
              log(`업체가 ${t.ko} 단가를 확인했어요`);
              toast("확인했어요 · 고객에게 가견적이 보여요");
              bump();
            }}
          >
            확인했어요
          </button>
          <span className="muted">{vps()[t.trade] === "confirmed" ? "확인함 · 고객에게 보임" : vps()[t.trade] === "draft" ? "고치는 중 · 고객에게 안 보임" : "단가 없음"}</span>
        </div>
      ) : null}
      <BandLine t={t} vendor={vendor} />
      {!vendor && est?.ok && vps()[t.trade] === "confirmed" ? (
        <p className="est-line">
          {`업체 가견적 ${fmt(est.total)}원 · 표준견적서보다 ${Math.abs(est.pct ?? 0)}% ${(est.pct ?? 0) < 0 ? "적어요" : (est.pct ?? 0) > 0 ? "많아요" : "같아요"}` +
            (t.lines.some((l) => l.key === "occupied") ? " · 짐 있는 집 할증은 가견적에서 빠지고 실측 견적서에서 정해요" : "")}
        </p>
      ) : null}
    </section>
  );
}

/* ---------- 시장 기준 (v5 bandLine · gapList · marketTable). band · gap은 quote 응답 ---------- */
function GapList({ t }: { t: Precise }) {
  const g = t.gap;
  if (!g) return null;
  const max = Math.max(...g.steps.map((s) => Math.abs(s.d)), 1);
  return (
    <div className="gap">
      <div className="gap-row end">
        <span>표준견적서 (공공 기준 · 부가세 포함)</span>
        <b className="num">{fmt(g.from) + "원"}</b>
      </div>
      {g.steps.map((s) => (
        <div key={s.key} className={"gap-row" + (s.d < 0 ? " down" : " up")}>
          <span>
            <b>{s.name}</b>
            <small>{s.why}</small>
          </span>
          <b className="num">{signWon(s.d)}</b>
          <i className="gap-bar" style={{ width: `${Math.max(4, Math.round((Math.abs(s.d) / max) * 100))}%` }} />
        </div>
      ))}
      <div className="gap-row end">
        <span>시장 기준 (부가세 별도)</span>
        <b className="num">{fmt(g.to) + "원"}</b>
      </div>
    </div>
  );
}

function MarketTable({ m, vendor }: { m: Band["mk"]; vendor: boolean }) {
  return (
    <div className="tbl">
      <table>
        <thead>
          <tr>
            <th>줄</th>
            <th>수량</th>
            <th>단가(원)</th>
            <th>금액(원)</th>
          </tr>
        </thead>
        <tbody>
          {m.lines.map((l) => (
            <tr key={l.key}>
              <td>
                <b>{l.name}</b>
                {vendor && l.note ? <div className="calc">{l.note}</div> : null}
              </td>
              <td className="num" data-l="수량">{l.qty != null ? `${fmt(l.qty)} ${l.unit}` : l.unit}</td>
              <td className="num" data-l="단가(원)">{l.unit_price != null ? fmt(l.unit_price) : "—"}</td>
              <td className="num amt" data-l="금액(원)">{fmt(l.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>시장 기준 (부가세 별도)</td>
            <td className="hide-m" />
            <td className="hide-m" />
            <td className="num amt">{fmt(m.supply) + "원"}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function BandLine({ t, vendor }: { t: Precise; vendor: boolean }) {
  const b = t.band;
  if (!b) return null;
  const m = b.mk;
  return (
    <div className="band-line mk">
      <b>{`업체 견적은 보통 ${fmt(b.lo)} ~ ${fmt(b.hi)}원 (부가세 별도)`}</b>
      <span>
        {`시장 기준 ${fmt(m.supply)}원 · ${t.trade === "dobae" ? (m.band.n ? `도면과 크기가 비슷한 2025~2026 실견적 ${fmt(b.n)}건` : `2025~2026 실견적 ${fmt(b.n)}건`) : `계산 항목만 있는 목공 실견적 ${b.n}건`}으로 맞춰 봤어요. 부가세를 받는 업체면 10%가 더해져요.`}
      </span>
      <details className="mk-more" open={vendor || undefined}>
        <summary>공공 기준과 다른 이유 · 시장 기준 줄 보기</summary>
        <GapList t={t} />
        <MarketTable m={m} vendor={vendor} />
        {vendor ? <p className="muted">{`시장 기준 값 버전 ${m.version}. 범위 = 시장 기준 × ${b.p[0]} ~ ${b.p[1]} (실견적과 시장 기준 차이의 중간 50%)`}</p> : null}
      </details>
    </div>
  );
}

function RefTable({ t, vendor }: { t: RefTrade; vendor: boolean }) {
  return (
    <section className="doc-trade ref">
      <h4 className="doc-sec">
        {t.ko}
        <small>{`참고 · ${t.days}일 어림`}</small>
      </h4>
      <Tbl collapse={!vendor} n={t.lines.length} sub={`${fmt(t.lo)} ~ ${fmt(t.hi)}원`}>
        <table>
          <thead>
            <tr>
              <th>줄</th>
              <th>수량</th>
              <th>금액 범위(원)</th>
              <th>포함 상태</th>
            </tr>
          </thead>
          <tbody>
            {t.lines.map((l) => (
              <tr key={l.key} className={l.state === "included" ? "" : "dim"}>
                <td>
                  <b>{l.name}</b>
                  {vendor ? <div className="calc">{l.calc}</div> : null}
                  {vendor && l.source ? (
                    <div className="src">
                      <span className={"basis b-" + l.basis}>{BASIS_KO[l.basis] || "시장 근거"}</span> {l.source}
                    </div>
                  ) : null}
                  {vendor && l.pub ? (
                    <div className="src">
                      <span className="basis b-public">공공 기준</span>
                      {` ${fmt(l.pub.unit_price)}원/${l.unit} → ${fmt(l.pub.amount)}원 · ${l.pub.source}`}
                    </div>
                  ) : null}
                </td>
                <td className="num" data-l="수량">{`${fmt(l.qty)} ${l.unit}`}</td>
                <td className="num amt" data-l="금액(원)">
                  {l.lo == null
                    ? "—"
                    : l.lo === l.hi
                      ? l.state === "included"
                        ? fmt(l.lo)
                        : `(${fmt(l.lo)})`
                      : l.state === "included"
                        ? `${fmt(l.lo)} ~ ${fmt(l.hi)}`
                        : `(${fmt(l.lo)} ~ ${fmt(l.hi)})`}
                </td>
                <td className="stc">
                  <span className={"st st-" + l.state}>{STATE_KO[l.state]}</span>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>{`${t.ko} 소계`}</td>
              <td className="hide-m" />
              <td className="num amt">{`${fmt(t.lo)} ~ ${fmt(t.hi)}원`}</td>
              <td className="stc">공급가</td>
            </tr>
          </tfoot>
        </table>
      </Tbl>
      {t.notes.length ? (
        <ul className="notes">
          {t.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}
    </section>
  );
}

/* ---------- 업체: 실측 견적서 보내기 (공급가 · 부가세 · 합계는 API entered) ---------- */
function VendorQuoteForm({ q }: { q: Quote }) {
  const trades: [string, string, number | null][] = [...q.precise.map((t) => [t.trade, t.ko, t.total] as [string, string, number]), ...q.ref.map((t) => [t.cat, t.ko, null] as [string, string, null])];
  const [sel, setSel] = useState(trades[0]?.[0] ?? "");
  const [amt, setAmt] = useState("");
  const [mode, setMode] = useState<VatMode>("excluded");
  const [days, setDays] = useState("");
  const [valid, setValid] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [out, setOut] = useState("");
  const send = async () => {
    if (!file) return setOut("견적서 파일을 하나 이상 올려 주세요.");
    if (amt === "") return setOut("낼 금액을 넣어 주세요.");
    const std = trades.find((x) => x[0] === sel)?.[2] ?? null;
    let r: Entered;
    try {
      r = await fetchEntered(Math.max(0, Math.min(1e9, Math.round(+amt))), mode, std);
    } catch (e) {
      return setOut(errorText(e));
    }
    const prev = vq()[sel];
    const ver = prev ? prev.ver + 1 : 1;
    vq()[sel] = { ...r, mode, days: days ? +days : null, valid: valid || null, file: file.name, ver, at: todaySeoul() };
    setOut(
      `보냈어요 · 버전 ${ver} · 공급가 ${fmt(r.supply)}원 · 부가세 ${fmt(r.vat)}원 · 합계 ${fmt(r.total)}원` +
        (std && r.pct != null ? ` · 표준견적서보다 ${Math.abs(r.pct)}% ${r.pct < 0 ? "적어요" : "많아요"}` : ""),
    );
    log(`업체가 ${CAT[sel]?.ko || (sel === "dobae" ? "도배" : "목공")} 실측 견적서 버전 ${ver}을 보냈어요`);
  };
  return (
    <section className="doc-trade">
      <h4 className="doc-sec">
        실측 견적서 보내기<small>업체 양식 파일 + 요약 칸</small>
      </h4>
      <div className="form-grid">
        <Fld label="공정">
          <select className="sort" aria-label="공정" value={sel} onChange={(e) => setSel(e.target.value)}>
            {trades.map(([k, ko]) => <option key={k} value={k}>{ko}</option>)}
          </select>
        </Fld>
        <Fld label="낼 금액(원)">
          <input className="inp" type="number" min="0" placeholder="낼 금액(원)" aria-label="낼 금액" value={amt} onChange={(e) => setAmt(e.target.value)} />
        </Fld>
        <Fld label="부가세">
          <select className="sort" aria-label="부가세 방식" value={mode} onChange={(e) => setMode(e.target.value as VatMode)}>
            <option value="excluded">부가세 빼고</option>
            <option value="included">부가세 포함</option>
            <option value="exempt">면세(간이과세 등)</option>
          </select>
        </Fld>
        <Fld label="공사 기간(일)">
          <input className="inp sm" type="number" min="1" max="120" placeholder="기간(일)" aria-label="공사 기간" value={days} onChange={(e) => setDays(e.target.value)} />
        </Fld>
        <div className="fld">
          <span id="vq8-valid-l">유효기간</span>
          <DateField id="vq8-valid" labelId="vq8-valid-l" label="유효기간" tail="까지" value={valid} onChange={setValid} />
        </div>
        <Fld label="견적서 파일">
          <input type="file" accept=".pdf,.xlsx,.xls,image/*" aria-label="견적서 파일" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Fld>
      </div>
      <div className="row">
        <button type="button" className="btn btn-pri btn-sm" onClick={send}>보내기</button>
        <p className="muted">{out}</p>
      </div>
    </section>
  );
}

function CustomerCompare({ q }: { q: Quote }) {
  const got = Object.entries(vq());
  if (!got.length) return null;
  return (
    <section className="doc-trade">
      <h4 className="doc-sec">받은 실측 견적서</h4>
      <ul className="notes">
        {got.map(([k, v]) => {
          const std = q.precise.find((t) => t.trade === k);
          const p = std ? v.pct : null;
          return (
            <li key={k}>
              {`${std?.ko || CAT[k]?.ko} · 버전 ${v.ver} · ${fmt(v.total)}원(부가세 포함)${v.days ? ` · ${v.days}일` : ""}${v.valid ? ` · ${v.valid}까지` : ""}${p != null ? ` · 표준견적서보다 ${Math.abs(p)}% ${p < 0 ? "적어요" : p > 0 ? "많아요" : "같아요"}` : ""} · 파일 ${v.file}`}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

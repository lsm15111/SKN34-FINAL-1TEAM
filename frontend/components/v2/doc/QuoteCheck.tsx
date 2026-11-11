"use client";
// 받은 견적 맞춰 보기 (v5 quoteCheck + 2816 덧씌움: 범위 위치 막대 · 견적서에 적혀 있나요 점검표).
// 받은 금액의 부가세 빼기 · 시장 기준 범위 · 추가 항목 범위 · 판정 · 안내 · 막대 위치는 API check가 만든다. 화면은 칸 값을 보내고 보이기만 한다.
import { useEffect, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { type CheckReq, type CheckRes, fetchCheck, type MarketExtra, marketExtras, type Quote, quoteBody } from "./api";
import { Fld, fmt } from "./shared";

const QC_ITEMS: Record<string, string[]> = {
  dobae: ["벽지 브랜드 · 모델 · 종류(합지 · 실크)", "초배 · 부직포 · 퍼티 같은 바탕 작업", "기존 벽지 철거 · 폐기물 처리", "몰딩 · 걸레받이 주변 마감", "가구 이동 · 바닥 보양", "부가세 포함 여부", "하자 보수 기간", "견적 유효기간"],
  mokgong: ["문 종류 · 문틀 포함 여부", "몰딩 · 걸레받이 길이(m)나 개수", "철거 · 폐기물 · 양중", "천장 평탄화 범위", "부가세 포함 여부", "하자 보수 기간", "대금 나눠 내는 시점"],
};
/** 맞춰 본 기록 (v10 V5.checks) */
export const V5 = { checks: [] as { trade: string; supply: number; lo: number; hi: number; where: string }[] };

type Out = { warn: string } | { res: CheckRes } | null;

export function QuoteCheck({ q }: { q: Quote }) {
  const [sel, setSel] = useState(q.precise[0]?.trade ?? "");
  const [amt, setAmt] = useState("");
  const [mode, setMode] = useState<CheckReq["mode"]>("unknown");
  const [on, setOn] = useState<Record<string, boolean>>({ ceiling: true });
  const [cnt, setCnt] = useState<Record<string, string>>({});
  const [out, setOut] = useState<Out>(null);
  const [extras, setExtras] = useState<MarketExtra[]>([]);
  useEffect(() => {
    marketExtras().then(setExtras, () => setExtras([]));
  }, []);
  if (!q.precise.length) return null;
  const pick = (v: string) => {
    setSel(v);
    setOn(v === "dobae" ? { ceiling: true } : {});
    setCnt({});
    setOut(null);
  };
  const chk = (key: string, label: string) => (
    <label className="chk" key={key}>
      <input type="checkbox" data-k={key} checked={!!on[key]} onChange={(e) => setOn({ ...on, [key]: e.target.checked })} />
      {label}
    </label>
  );
  const go = async () => {
    const ex: Record<string, number> = {};
    for (const e of extras) if (on["x-" + e.key]) ex[e.key] = Math.max(1, Math.min(9, Math.round(+(cnt["x-" + e.key] || 1))));
    const scope = sel === "dobae" ? { ceiling: !!on.ceiling, removal: !!on.removal, moving: !!on.moving } : { casing9: !!on.casing9, removal: !!on.removal, etc: !!on.etc, extras: ex };
    try {
      const res = await fetchCheck({ quote: quoteBody(), trade: sel, amount: +amt || 0, mode, scope });
      if (res.warn) return setOut({ warn: res.warn });
      if (res.supply != null && res.lo != null && res.hi != null && res.where) V5.checks.push({ trade: res.trade, supply: res.supply, lo: res.lo, hi: res.hi, where: res.where });
      setOut({ res });
    } catch (e) {
      setOut({ warn: errorText(e) });
    }
  };
  return (
    <section className="doc-trade qc">
      <h4 className="doc-sec">
        받은 견적 맞춰 보기<small>업체 금액과 포함 범위를 넣으면 같은 범위의 시장 기준과 비교해요</small>
      </h4>
      <div className="form-grid">
        <Fld label="공정">
          <select className="sort" aria-label="공정" value={sel} onChange={(e) => pick(e.target.value)}>
            {q.precise.map((t) => <option key={t.trade} value={t.trade}>{t.ko}</option>)}
          </select>
        </Fld>
        <Fld label="받은 금액(원)">
          <input className="inp" type="number" min="0" inputMode="numeric" placeholder="예: 2500000" aria-label="받은 견적 금액" value={amt} onChange={(e) => setAmt(e.target.value)} />
        </Fld>
        <Fld label="부가세">
          <select className="sort" aria-label="부가세" value={mode} onChange={(e) => setMode(e.target.value as CheckReq["mode"])}>
            <option value="unknown">부가세 말이 없음</option>
            <option value="excluded">부가세 별도</option>
            <option value="included">부가세 포함</option>
          </select>
        </Fld>
      </div>
      <div className="doc-opts">
        {sel === "dobae"
          ? [chk("ceiling", "천장 포함"), chk("removal", "기존 벽지 철거 포함"), chk("moving", "짐 이동 · 정리 포함")]
          : [
              chk("casing9", "9mm 문선으로"),
              chk("removal", "철거 · 폐기물 포함"),
              ...extras.map((e) =>
                e.per === "곳" ? (
                  <label className="chk" key={"x-" + e.key}>
                    <input type="checkbox" data-k={"x-" + e.key} checked={!!on["x-" + e.key]} onChange={(x) => setOn({ ...on, ["x-" + e.key]: x.target.checked })} />
                    {e.name}
                    <input
                      className="inp cnt"
                      type="number"
                      min="1"
                      max="9"
                      value={cnt["x-" + e.key] ?? "1"}
                      data-c={"x-" + e.key}
                      aria-label={e.name + " 곳 수"}
                      onChange={(x) => setCnt({ ...cnt, ["x-" + e.key]: x.target.value })}
                    />
                    곳
                  </label>
                ) : (
                  chk("x-" + e.key, e.name)
                ),
              ),
              chk("etc", "그 밖의 목공(수납장 · 붙박이 · 천장 전체 등) 포함"),
            ]}
      </div>
      <div className="row">
        <button type="button" className="btn btn-pri btn-sm" onClick={go}>맞춰 보기</button>
      </div>
      <div className="qc-out" aria-live="polite">
        {out && "warn" in out ? <p className="warn-line">{out.warn}</p> : out ? <Result res={out.res} /> : null}
      </div>
      <Items key={sel} list={QC_ITEMS[sel] || QC_ITEMS.dobae} />
    </section>
  );
}

function Result({ res }: { res: CheckRes }) {
  const bar = res.bar;
  return (
    <div className={"qc-res qc-" + res.where}>
      <b>{res.head}</b>
      {bar ? (
        <div className="qc-bar" aria-hidden="true">
          <i className="qc-band" style={{ left: `${bar.band_left}%`, width: `${bar.band_width}%` }} />
          <i className="qc-me" style={{ left: `${bar.me}%` }} />
          <em className="qc-me-l" style={{ left: `${bar.me}%` }}>받은 금액</em>
          <span className="l">낮음</span>
          <span className="r">높음</span>
        </div>
      ) : null}
      <p>{`받은 금액(부가세 뺀 값) ${fmt(res.supply)}원 · 같은 범위 시장 기준 보통 ${fmt(res.lo)} ~ ${fmt(res.hi)}원`}</p>
      {res.notes?.length ? (
        <ul className="notes">
          {res.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}
      {res.why?.length ? (
        <ul className="notes">
          {res.why.map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}
      {res.vat_unknown ? <p className="muted">부가세 말이 없으면 부가세 별도 금액으로 보고 비교했어요.</p> : null}
    </div>
  );
}

function Items({ list }: { list: string[] }) {
  const [checked, setChecked] = useState<boolean[]>(() => list.map(() => false));
  const n = checked.filter((c) => !c).length;
  return (
    <div className="qc-items">
      <b>견적서에 적혀 있나요?</b>
      <ul className="c7-list">
        {list.map((t, i) => (
          <li key={t}>
            <label className="chk">
              <input type="checkbox" checked={checked[i]} onChange={(e) => setChecked(checked.map((c, k) => (k === i ? e.target.checked : c)))} />
              {t}
            </label>
          </li>
        ))}
      </ul>
      <p className="muted">{n ? `적혀 있지 않은 항목 ${n}개 · 업체에 물어보세요` : "다 적혀 있어요"}</p>
    </div>
  );
}

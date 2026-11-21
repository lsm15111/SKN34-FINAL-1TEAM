"use client";
// 도배 단가(D02 d_price 웹 표 · 폰은 같은 줄을 카드로, research F01). 줄마다 받는 법(단가 · 다른 줄에 포함 · 빼기)을 골라요.
// L01: 줄마다 무엇 1단위당인지 분명히 쓰고(PRICE_UNIT), 기준 단가와 10배쯤 다르면 경고해요(저장은 한 번 더 물어요). 빈 단가는 저장을 막아요.
// '공급 69.4㎡ 집이면' 금액 · 아래 가견적 합계는 계산 엔진 값이에요: 저장한 값 그대로일 때만 보이고, 바꾼 줄은 '수량 × 단가' 식만 보여요(화면은 곱하지 않아요).
// 예시 가견적에서 '선택'인 줄(퍼티 · 운송비)은 괄호 금액 · '선택 · 합계 밖'으로 보여요(아래 합계에 안 들어가요, ADR 0006).
// 벽지별 줄(API grade: 도배지 · 부자재 1205 실크 · 1209 합지)은 같은 벽지 줄이나 모든 집 줄에만 '다른 줄에 포함'할 수 있어요.
// 확인한 묶음에 없던 새 줄(1209를 더하기 전에 확인한 묶음)은 받는 법이 비어 와서 위에 알려요.
// 저장 → POST /vendor/prices/dobae/confirm {base_version, lines}(멱등 키). 본 판이 아니면 409(다른 곳에서 먼저 저장).
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Field, SelectField } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import type { PriceRowV3, PricesV3 } from "@/lib/api/vendor";
import { ApiError, errorText } from "@/lib/backend/client";
import { decText, numText, won } from "@/lib/format";
import { LINE_STATES } from "@/lib/labels";
import { newKey, send } from "../send";
import { PRICE_UNIT } from "../text";
import { Notice } from "@/components/ui/Notice";
import { Small } from "../ui/parts";
import { Segmented } from "@/components/ui/Segmented";
import s from "./prices.module.css";

type Mode = "price" | "included" | "excluded";
type Line = { mode: Mode; price: string; included_in: string | null };
const MODES: { value: Mode; label: string }[] = [{ value: "price", label: "단가" }, { value: "included", label: "다른 줄에 포함" }, { value: "excluded", label: "빼기" }];
const digits = (v: string) => v.replace(/\D/g, "").slice(0, 9);
const PAPER = new Set(["paper_hapji", "paper_silk"]);
const OPTIONAL_WORD = `${LINE_STATES.optional} · 합계 밖`; // 표준견적서 · 고객 가견적의 선택 줄과 같은 말(QuoteLines)

/** 한 집 가견적에 같이 나오는 줄인지: 벽지별 줄끼리는 같은 벽지만(API grade, 서버도 같은 규칙으로 막아요) */
const sameHome = (a: PriceRowV3, b: PriceRowV3) => !a.grade || !b.grade || a.grade === b.grade;

function warnOf(r: PriceRowV3, l: Line): "high" | "low" | null {
  if (l.mode !== "price" || !l.price) return null;
  const n = Number(l.price);
  if (r.warn_high != null || r.warn_low != null) return r.warn_high != null && n > r.warn_high ? "high" : r.warn_low != null && n < r.warn_low ? "low" : null;
  // 기준 값이 아직 안 오면 저장한 값에 붙은 서버 경고만 보여요
  return r.unit_price === n && r.warn ? (r.warn === "too_high" ? "high" : "low") : null;
}

export function PriceForm({ prices, taxKind, homeLabel }: { prices: PricesV3; taxKind: string; /** 예시 집 이름: '공급 69.4㎡ 집' */ homeLabel: string }) {
  const router = useRouter();
  const toast = useToast();
  const init = useMemo(() => Object.fromEntries(prices.lines.map((r) => [r.key, {
    mode: (r.mode ?? "price") as Mode,
    price: r.unit_price != null ? String(r.unit_price) : "",
    included_in: r.included_in ?? (r.key === "meal" ? "labor" : null),
  }])) as Record<string, Line>, [prices.lines]);
  const [lines, setLines] = useState<Record<string, Line>>(init);
  const [err, setErr] = useState<Record<string, string | undefined>>({});
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState(false);
  const [idem] = useState(newKey);
  const simplified = taxKind === "simplified";
  const set = (key: string, patch: Partial<Line>) => { setLines((x) => ({ ...x, [key]: { ...x[key], ...patch } })); setErr((e) => ({ ...e, [key]: undefined, form: undefined })); };
  const changed = (r: PriceRowV3) => {
    const l = lines[r.key];
    const m0 = (r.mode ?? "price") as Mode;
    return l.mode !== m0 || (l.mode === "price" && l.price !== (r.unit_price != null ? String(r.unit_price) : "")) || (l.mode === "included" && l.included_in !== (r.included_in ?? null));
  };
  const anyChanged = prices.lines.some(changed) || prices.needs_setup;
  const priceRows = prices.lines.filter((r) => lines[r.key].mode === "price");
  /** '다른 줄에 포함'으로 고를 수 있는 줄: 단가를 넣은 다른 줄 중 같은 집 가견적에 같이 나오는 줄 */
  const targets = (r: PriceRowV3) => priceRows.filter((x) => x.key !== r.key && sameHome(x, r));
  // 확인한 묶음에 없던 새 줄(받는 법이 비어 와요). 넣고 확인하기 전에는 고객 가견적이 앞 줄 값을 써요
  const fresh = prices.needs_setup ? [] : prices.lines.filter((r) => r.mode == null);
  const nameOf = (key: string | null) => { const r = prices.lines.find((x) => x.key === key); return r ? `${r.code} ${r.name}` : "다른 줄"; };
  const warns = prices.lines.filter((r) => warnOf(r, lines[r.key]));
  // 예시 가견적의 '선택' 줄 키(API optional, 판 2026.11b)
  const optional = new Set((prices.example?.lines ?? []).filter((x) => x.optional).map((x) => x.key));

  function check(): boolean {
    const e: Record<string, string> = {};
    for (const r of prices.lines) {
      const l = lines[r.key];
      if (l.mode === "price" && !(Number(l.price) > 0)) e[r.key] = "단가를 넣어 주세요";
      if (l.mode === "included") {
        const host = prices.lines.find((x) => x.key === l.included_in);
        if (!host || lines[host.key]?.mode !== "price") e[r.key] = "포함할 줄을 골라 주세요(단가를 넣은 줄만)";
        else if (!sameHome(host, r)) e[r.key] = "같은 벽지 집에 쓰는 줄로 골라 주세요";
      }
    }
    setErr(e);
    const first = prices.lines.find((r) => e[r.key]);
    if (first) document.getElementById(`price-${first.key}`)?.focus();
    return !Object.keys(e).length;
  }
  function onSave() {
    if (busy || !check()) return;
    if (warns.length) { setAsk(true); return; }
    void save();
  }
  async function save() {
    setAsk(false);
    setBusy(true);
    try {
      await send("POST", "/vendor/prices/dobae/confirm", {
        base_version: prices.version,
        lines: prices.lines.map((r) => { const l = lines[r.key]; return { key: r.key, mode: l.mode, unit_price: l.mode === "price" ? Number(l.price) : null, included_in: l.mode === "included" ? l.included_in : null }; }),
      }, { idem });
      toast.show("단가를 확인하고 저장했어요. 고객에게 바로 보여요.");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.code === "stale") { setErr({ form: "다른 곳에서 먼저 저장했어요. 새로 불러왔으니 다시 확인해 주세요." }); router.refresh(); }
      else if (e instanceof ApiError && e.fields?.length) {
        const got: Record<string, string> = {};
        e.fields.forEach((f) => { const k = String(f.loc[f.loc.length - 1] ?? "form"); got[prices.lines.find((r) => r.key === k) ? k : "form"] ??= f.msg; });
        setErr(got);
      } else setErr({ form: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  const hasErr = Object.values(err).some(Boolean);
  const total = !anyChanged && !hasErr && prices.example ? won(prices.example.total) : hasErr || warns.length ? "빈 칸 · 경고를 고치면 보여요" : "저장하면 다시 계산해요";

  return (
    <>
      <Main>
        <PageHead
          title="도배 단가"
          crumbs={[{ label: "업체 정보", href: "/vendor/profile" }, { label: "도배 단가" }]}
          desc={simplified ? "받을 금액 그대로 원 단위로 넣어요 · 간이과세라 부가세를 따로 붙이지 않아요" : "부가세 빼고 원 단위로 넣어요 · 고객에게는 집마다 업체 단가 × 믿집 수량으로 보여요"}
        />
        {prices.needs_setup ? <Notice tone="info">단가표가 새 줄(1201~1209)로 바뀌었어요. 줄마다 받는 법과 단가를 넣고 확인해 주세요.</Notice> : null}
        {fresh.length ? <Notice tone="info">새 줄이 생겼어요({fresh.map((r) => `${r.code} ${r.name}`).join(" · ")}). 받는 법과 단가를 넣고 확인해 주세요.</Notice> : null}
        <div className={s.box}>
          <div className={s.head} aria-hidden="true"><span>코드 · 줄</span><span>받는 법</span><span>단가(원)</span><span className={s.r}>{homeLabel}이면</span></div>
          <ul className={s.rows} aria-label="도배 단가 줄">
            {prices.lines.map((r) => {
              const l = lines[r.key];
              const w = warnOf(r, l);
              const e = err[r.key];
              const unitText = PRICE_UNIT[r.key] ?? `${r.unit}당`;
              const qty = `${decText(r.example_qty)}${r.unit}`;
              return (
                <li key={r.key} className={`${s.row} ${e ? s.bad : w ? s.warn : ""}`}>
                  <div className={s.cName}>
                    <span className={`${s.code} mj-num`}>{r.code}</span>
                    <span className={s.nm}><b>{r.name}</b><span>{unitText}</span></span>
                  </div>
                  <div className={s.cMode}><Segmented legend={`${r.code} ${r.name} 받는 법`} hideLegend full options={MODES} value={l.mode} onChange={(v) => { const m = v as Mode; set(r.key, { mode: m, included_in: m === "included" ? l.included_in ?? (r.key === "meal" ? "labor" : targets(r)[0]?.key ?? null) : l.included_in }); }} /></div>
                  <div className={s.cPrice}>
                    {l.mode === "price" ? (
                      <Field
                        id={`price-${r.key}`}
                        label={`${r.code} ${r.name} 단가 · ${unitText}`}
                        hideLabel
                        unit="원"
                        num
                        inputMode="numeric"
                        placeholder="단가를 넣어 주세요"
                        value={l.price ? Number(l.price).toLocaleString("ko-KR") : ""}
                        error={e ?? (w === "high" ? "기준 단가의 10배쯤이에요. 0을 더 넣지 않았나요?" : w === "low" ? "기준 단가의 10분의 1쯤이에요. 0을 빼먹지 않았나요?" : null)}
                        onChange={(ev) => set(r.key, { price: digits(ev.target.value) })}
                      />
                    ) : l.mode === "included" ? (
                      <SelectField
                        id={`price-${r.key}`}
                        label={`${r.code} ${r.name} · 어느 줄에 포함`}
                        hideLabel
                        options={[{ value: "", label: "포함할 줄 고르기" }, ...targets(r).map((x) => ({ value: x.key, label: `→ ${x.code} ${x.name}` }))]}
                        value={l.included_in ?? ""}
                        error={e}
                        onChange={(ev) => set(r.key, { included_in: ev.target.value || null })}
                      />
                    ) : <span className={s.dash}>—</span>}
                  </div>
                  <div className={`${s.cAmt} mj-num`}>
                    <span className={s.amtLabel}>{homeLabel}이면</span>
                    {l.mode === "excluded" ? <span className={s.mute}>{PAPER.has(r.key) ? "고객에게 '이 벽지는 안 해요'로 보여요" : "가견적에 넣지 않아요"}</span>
                      : l.mode === "included" ? <span className={s.mute}>{l.included_in ? `${nameOf(l.included_in).replace(/^\d+ /, "")}에 포함` : "—"}</span>
                      : changed(r) || !l.price ? <span className={s.mute}>{l.price ? `${qty} × ${numText(Number(l.price))}원${optional.has(r.key) ? ` · ${OPTIONAL_WORD}` : ""}` : "—"}</span>
                      : optional.has(r.key) ? <span className={s.mute}>{OPTIONAL_WORD} ({numText(r.example_amount)})</span>
                      : <b>{numText(r.example_amount)}</b>}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
        {err.form ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err.form}</p> : null}
        <Small>수량(평 · 품 · 대)은 믿집이 집마다 계산해요. 바꾼 줄의 금액과 아래 가견적은 저장하면 다시 계산해서 보여요.</Small>
      </Main>
      <BottomBar summary={{ label: `${homeLabel} 가견적 · ${simplified ? "받을 금액" : "부가세 포함"}`, value: total }} note="저장하면 고객에게 바로 보여요. 이미 요청한 고객 값은 그대로예요.">
        <Button size="lg" block onClick={onSave} busy={busy}>{busy ? "저장하는 중" : "확인하고 저장"}</Button>
      </BottomBar>
      <ConfirmDialog open={ask} onClose={() => setAsk(false)} title="기준 단가와 10배쯤 다른 줄이 있어요. 그대로 저장할까요?" confirmLabel="그대로 저장" onConfirm={() => void save()} busy={busy}>
        <ul className={s.askList}>{warns.map((r) => <li key={r.key}>{r.code} {r.name} · {numText(Number(lines[r.key].price))}원 · {PRICE_UNIT[r.key] ?? `${r.unit}당`}</li>)}</ul>
        <p>저장하면 고객에게 바로 보여요. 0을 더 넣었거나 빼먹었으면 닫고 고쳐 주세요.</p>
      </ConfirmDialog>
    </>
  );
}

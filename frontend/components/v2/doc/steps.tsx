"use client";
// 견적서 · 공정표 단계 (v10 quoteStep · openQuoteDoc · explainQuote · bandWhy(v5) · schedStep · openPlanDoc · schedAgent · quoteNumbersText · planNumbersText).
// 계산은 API(quote · plan)가 하고, AI 답은 작업자 D의 F.agentAnswer가 숫자 검사까지 맡는다.
import { useEffect, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { todaySeoul } from "../dates";
import { bot, F, me, openOverlay, quick } from "../engine";
import { setStep } from "../flow";
import { S, V3 } from "../store";
import type { Plan, Quote } from "./api";
import { ensureQuote, GanttEl, loadPlan, PlanDocBody } from "./PlanDoc";
import { QuoteCheck } from "./QuoteCheck";
import { loadQuote, QuoteDocBody } from "./QuoteDoc";
import { approxMan, DocShell, fmt, manRange, mdw, STATE_KO } from "./shared";

const FAIL = "설명을 만들지 못했어요. 계산 결과는 견적서에서 그대로 볼 수 있어요.";
const Spark = () => <span className="spark" aria-hidden="true">✦</span>;

/* ---------- 견적서 ---------- */
function QuoteSumCard({ q }: { q: Quote }) {
  const names = [...q.precise.map((t) => t.ko), ...q.ref.map((t) => t.ko)];
  return (
    <div className="card v3sum">
      <div>
        <h3>표준견적서</h3>
        <p className="muted">{`${q.inp.py}평${q.inp.measured ? ` · 도면 ${q.inp.measured.name} 수량` : ""} · ${names.join(" · ")}`}</p>
      </div>
      <div className="kpi main">
        <span>{`예상 공사비 (${q.precise.length + q.ref.length}개 공정)`}</span>
        <b className="num">{q.ref.length ? manRange(q.all_lo, q.all_hi) : approxMan(q.total)}</b>
        <small>부가세 포함 · 실측 뒤 달라질 수 있어요</small>
      </div>
      <details className="v3more">
        <summary>금액 자세히</summary>
        {q.precise.length ? (
          <div className="kpi">
            <span>{`공공 기준 (${q.precise.map((t) => t.ko).join(" · ")})`}</span>
            <b className="num">{approxMan(q.total)}</b>
            <small>{`${fmt(q.total)}원 · 부가세 포함 · 표준시장단가로 계산`}</small>
          </div>
        ) : null}
        {q.band ? (
          <div className="kpi band">
            <span>업체 견적은 보통 (부가세 별도)</span>
            <b className="num">{manRange(q.band.lo, q.band.hi)}</b>
            <small>{"2025~2026 실견적으로 맞춘 시장 기준 · '왜 달라요?'"}</small>
          </div>
        ) : null}
        {q.ref.length ? (
          <div className="kpi">
            <span>{`참고 금액 (${q.ref.length}개 공정)`}</span>
            <b className="num">{manRange(q.rlo, q.rhi)}</b>
            <small>부가세 포함 · 시장 근거 · 업체 견적 아님</small>
          </div>
        ) : null}
      </details>
      {q.inp.assumed.length ? <p className="muted">{q.inp.assumed.join(" · ")}</p> : null}
      <div className="row">
        <button type="button" className="btn btn-pri" onClick={() => openQuoteDoc()}>견적서 열기</button>
        <button type="button" className="btn-text" onClick={() => explainQuote()}>
          <Spark />
          금액 풀이 듣기
        </button>
      </div>
    </div>
  );
}

export async function quoteStep() {
  setStep("quote");
  let q: Quote;
  try {
    q = await loadQuote();
  } catch (e) {
    await bot(`표준견적서를 계산하지 못했어요. ${errorText(e)}`);
    quick([["다시 해 보기", () => quoteStep()]]);
    return;
  }
  await bot("표준견적서가 나왔어요.", <QuoteSumCard q={q} />);
  quick([
    ["공정표 보기", () => schedStep()],
    ["계약 전 점검", () => F.checkStep?.("contract")],
    ["왜 이 금액이에요?", () => explainQuote()],
    ...(q.band ? ([["왜 달라요?", () => bandWhy()]] as [string, () => void][]) : []),
  ]);
}

export function openQuoteDoc() {
  openOverlay((close) => <DocShell title="표준견적서" close={close}>{() => <QuoteDocBody />}</DocShell>);
}

/** 숫자 검사에 쓸 허용 글: 견적의 모든 수(금액 · 수량 · 단가 · 품 · 기간) */
export function quoteNumbersText(q: Quote) {
  const parts: (number | null | undefined)[] = [q.supply, q.vat, q.total, q.rlo, q.rhi, q.inp.py, q.inp.area_m2, q.inp.doors, q.band?.lo, q.band?.hi];
  for (const t of q.precise) {
    const b = t.band;
    if (b) parts.push(b.lo, b.hi, b.n, b.mk.supply);
    for (const st of t.gap?.steps ?? []) parts.push(Math.abs(st.d));
  }
  for (const t of q.precise) {
    parts.push(t.supply, t.vat, t.total, t.man_days, t.days, t.crew);
    for (const l of t.lines) parts.push(l.qty, l.unit_price, l.amount);
  }
  for (const t of q.ref) {
    parts.push(t.lo, t.hi, t.days);
    for (const l of t.lines) parts.push(l.qty, l.lo, l.hi);
  }
  return (
    parts.filter((x) => x != null).map((x) => `${x}원 ${x}㎡ ${x}일 ${x}m ${x}개 ${x}평 ${x}품 ${x}명`).join(" ") +
    " 10% 2.5 3.3058 1.2 0.25 0.8 1.08 0.85 0.96 2.4 1.8 1.1 1.04 10.2 0.3 2일 1일"
  );
}

/** 견적 설명 에이전트: 저장된 금액을 풀이만 한다 */
export async function explainQuote(question?: string) {
  let q: Quote;
  try {
    q = (V3.quote as Quote | null) ?? (await loadQuote());
  } catch (e) {
    await bot(`표준견적서를 계산하지 못했어요. ${errorText(e)}`);
    return;
  }
  const facts = JSON.stringify({
    면적: { 공급_m2: q.inp.area_m2, 평: q.inp.py },
    정밀: q.precise.map((t) => ({
      공정: t.ko, 공급가: t.supply, 부가세: t.vat, 합계: t.total, 품: t.man_days, 기간_일: t.days,
      줄: t.lines.map((l) => ({ 줄: l.name, 수량: l.qty, 단위: l.unit, 단가: l.unit_price, 금액: l.amount, 상태: STATE_KO[l.state], 근거: l.source, 산식: l.calc })),
      가정: t.notes,
    })),
    실견적_범위: q.precise.map((t) => (t.band ? { 공정: t.ko, 범위: [t.band.lo, t.band.hi], 실견적_건수: t.band.n } : null)).filter(Boolean),
    참고: q.ref.map((t) => ({ 공정: t.ko, 범위: [t.lo, t.hi], 기간_일: t.days, 줄: t.lines.map((l) => ({ 줄: l.name, 수량: l.qty, 단위: l.unit, 범위: [l.lo, l.hi], 근거: l.source })) })),
    합계: { 공급가: q.supply, 부가세: q.vat, 낼_금액: q.total, 참고_범위: [q.rlo, q.rhi] },
    예산_만원: S.budget || null,
  });
  const ask = question || "이 표준견적서 금액이 어떻게 나왔는지 쉽게 풀어 주세요. 가장 큰 줄 두세 개와 실측 뒤 바뀔 수 있는 것을 알려 주세요.";
  if (!F.agentAnswer) {
    if (!question) me("금액 풀이");
    await bot(FAIL);
    return;
  }
  await F.agentAnswer({
    label: question ? null : "금액 풀이",
    ask,
    system: [
      "너는 믿집의 '견적 설명' 에이전트야. 아래 표준견적서 데이터를 처음 인테리어하는 고객에게 해요체로 풀어 설명해. 3~6문장.",
      "규칙: 금액 · 수량 · 기간은 데이터에 있는 숫자만 그대로 써. 더하기 · 빼기 · 평당 금액 같은 새 계산을 하지 마. 금액을 보장하거나 확정된 것처럼 말하지 마.",
      "'실측 후' 줄은 합계 밖이고 업체가 집을 본 뒤 정한다고 알려 줘. 참고 공정은 시장 범위라고 밝혀. 업체에 물어볼 것 1~2개를 마지막에 줘.",
      "실견적_범위는 시장 기준(업체 견적에 보통 적히는 금액, 부가세 별도)이야. 표준견적서(공공 기준, 부가세 포함)와 다르다는 것을 한 문장으로 알려 줘. 범위 숫자는 그대로만 써.",
      "법규 · 시공 근거가 필요하면 search_knowledge를 쓰고 [K번호]를 붙여.",
      "## 표준견적서 데이터",
      facts,
    ].join("\n"),
    allowed: quoteNumbersText(q),
  });
}

/** '왜 달라요?' 대화 카드: 공정마다 가장 큰 이유 3개 (v5) */
export async function bandWhy() {
  let q: Quote;
  try {
    q = (V3.quote as Quote | null) ?? (await loadQuote());
  } catch {
    return;
  }
  if (!q.band) return;
  me("왜 달라요?");
  const cards = q.precise.map((t) => {
    const g = t.gap;
    if (!g) return null;
    const top = [...g.steps].sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 3);
    return (
      <li key={t.trade}>
        <b>{t.ko}</b>
        {` 표준견적서 ${approxMan(g.from)} → 시장 기준 ${approxMan(g.to)}(부가세 별도). 큰 이유: ` +
          top.map((s) => `${s.name} ${s.d > 0 ? "+" : "−"}${Math.round(Math.abs(s.d) / 10000).toLocaleString("ko-KR")}만 원`).join(" · ")}
      </li>
    );
  });
  await bot(
    "표준견적서는 공공 기준(표준시장단가 · 시중노임단가)으로 계산해서 업체 견적과 달라요. 그래서 같은 줄에 시장 값을 넣은 '시장 기준'을 같이 보여요.",
    <div className="card">
      <ul className="notes band-why">{cards}</ul>
      <p className="muted">시장 기준은 2025~2026년에 공개된 실견적(숨고 · 커뮤니티 · 블로그 · 업체 사이트)과 시장 조사로 맞췄어요. 지역 · 업체 · 자재마다 달라요.</p>
      <p className="muted">업체 견적을 받으면 견적서의 [받은 견적 맞춰 보기]에 넣어 보세요.</p>
    </div>,
  );
  quick([["견적서 열기", () => openQuoteDoc()], ["공정표 보기", () => schedStep()]]);
}

/** 받은 견적 맞춰 보기를 다른 곳(체크리스트 · 계산기)에서 열 때. 견적이 없으면 받아 온다 */
function QuoteCheckCard({ q: given }: { q?: Quote }) {
  const [q, setQ] = useState<Quote | null>(given ?? (V3.quote as Quote | null) ?? null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!q) loadQuote().then(setQ, (e) => setErr(errorText(e)));
  }, []);
  if (!q) return <p className="muted">{err || "견적서를 계산하는 중이에요…"}</p>;
  if (!q.precise.length) return <p className="muted">도배 · 목공을 고르면 받은 견적을 맞춰 볼 수 있어요.</p>;
  return (
    <div className="card">
      <QuoteCheck q={q} />
    </div>
  );
}
export const quoteCheckCard = (q?: Quote) => <QuoteCheckCard q={q} />;

/* ---------- 공정표 ---------- */
function PlanCard({ p, title }: { p: Plan; title?: boolean }) {
  return (
    <div className="card v3sum">
      {title ? (
        <div>
          <h3>예상 공정표</h3>
          <p className="muted">{`${mdw(p.start)} ~ ${mdw(p.end)} · 일하는 날 ${p.work_days}일 · ${V3.cons.weekendWork ? "공휴일만 쉬어요" : "주말 · 공휴일은 쉬어요"}`}</p>
        </div>
      ) : (
        <p className="muted">{`바뀐 공정표 · ${p.start} ~ ${p.end} · 일하는 날 ${p.work_days}일`}</p>
      )}
      <GanttEl p={p} mini />
      {p.warn.length ? <p className="warn-line">{p.warn.join(" · ")}</p> : null}
      <div className="row">
        {title ? (
          <>
            <button type="button" className="btn btn-pri" onClick={() => openPlanDoc()}>공정표 열기</button>
            <button type="button" className="btn-text" onClick={() => schedAgent()}>
              <Spark />
              일정 조건 말하기
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-pri btn-sm" onClick={() => openPlanDoc()}>공정표 열기</button>
        )}
      </div>
    </div>
  );
}

export async function schedStep() {
  setStep("sched");
  let p: Plan;
  try {
    p = await loadPlan();
  } catch (e) {
    await bot(`공정표를 계산하지 못했어요. ${errorText(e)}`);
    quick([["다시 해 보기", () => schedStep()]]);
    return;
  }
  await bot("공사 순서대로 예상 날짜를 잡았어요.", <PlanCard p={p} title />);
  quick([
    ["공사 전 체크리스트", () => F.checkStep?.("before")],
    ["12월 안에 끝내고 싶어요", () => schedAgent("12월 안에 끝내고 싶어요")],
    ["주말에도 공사해도 돼요", () => schedAgent("주말에도 공사해도 돼요")],
    ["견적서 다시 보기", () => openQuoteDoc()],
  ]);
}

export function openPlanDoc() {
  openOverlay((close) => <DocShell title="공정표" close={close}>{() => <PlanDocBody />}</DocShell>);
}

/** 공정표 숫자 허용 글: 날짜(연 · 월 · 일), 기간, 일하는 날 */
export function planNumbersText(p: Plan | null) {
  if (!p) return "";
  const out = [p.work_days + "일"];
  for (const b of p.blocks)
    for (const d of [b.start, b.end]) {
      const [y, m, dd] = d.split("-").map(Number);
      out.push(`${y}`, `${m}`, `${dd}일`, `${m}.${dd}`, d);
    }
  for (const b of p.blocks) out.push(b.days + "일");
  for (const w of p.warn) out.push(w);
  if (V3.cons.endBy) out.push(V3.cons.endBy, ...V3.cons.endBy.split("-").map(Number).map(String), Number(V3.cons.endBy.slice(8)) + "일");
  return out.join(" ");
}

const SCHED_SCHEMA = {
  type: "object",
  properties: { weekend_work: { type: "boolean" }, end_by: { type: "string" }, start_after: { type: "string" }, avoid_dates: { type: "array", items: { type: "string" }, maxItems: 20 } },
};
type Cons = { weekend_work?: boolean; end_by?: string; start_after?: string; avoid_dates?: string[] };

/** 공정표 에이전트: 고객 말 → 제약(도구) → API가 다시 계산 → 결과만 설명 */
export async function schedAgent(text?: string) {
  const say = text;
  if (!say) {
    const el = document.getElementById("chat-in") as HTMLTextAreaElement | null;
    if (el) {
      el.focus();
      el.placeholder = "예: 12월 20일까지 끝내 주세요";
    }
    return;
  }
  let before: Plan;
  try {
    before = await loadPlan();
  } catch (e) {
    me(say);
    await bot(`공정표를 계산하지 못했어요. ${errorText(e)}`);
    return;
  }
  if (!F.agentAnswer) {
    me(say);
    await bot(FAIL);
    return;
  }
  const tools = [
    {
      name: "set_schedule_constraints",
      description: "고객이 말한 일정 조건을 공정표 계산 조건으로 바꾼다. 말한 것만 넣는다. 날짜는 YYYY-MM-DD. 날짜 계산은 코드가 한다.",
      inputSchema: SCHED_SCHEMA,
      parameters: SCHED_SCHEMA,
      execute: async (a: Cons) => {
        const okd = (s?: string) => /^\d{4}-\d{2}-\d{2}$/.test(s || "");
        if (a.weekend_work != null) V3.cons.weekendWork = !!a.weekend_work;
        if (a.end_by) {
          if (!okd(a.end_by)) throw new Error("end_by는 YYYY-MM-DD");
          V3.cons.endBy = a.end_by;
        }
        if (a.start_after) {
          if (!okd(a.start_after)) throw new Error("start_after는 YYYY-MM-DD");
          V3.cons.startAfter = a.start_after;
        }
        if (a.avoid_dates) V3.cons.avoid = [...new Set([...V3.cons.avoid, ...a.avoid_dates.filter((d) => okd(d))])];
        const p = await loadPlan();
        return { 시작: p.start, 끝: p.end, 일하는_날: p.work_days, 경고: p.warn, 공정: p.blocks.map((b) => `${b.ko} ${b.start}~${b.end}`) };
      },
    },
  ];
  const r = await F.agentAnswer({
    label: say,
    ask: say,
    tools,
    system: [
      `너는 믿집의 '공정표' 에이전트야. 오늘은 ${todaySeoul()}(서울)이야. 고객의 말을 set_schedule_constraints로 조건으로 바꾸고, 도구가 돌려준 결과(시작 · 끝 · 경고)만 써서 해요체로 2~4문장 설명해.`,
      "날짜를 직접 계산하거나 지어내지 마. 도구 결과에 없는 날짜 · 일수는 쓰지 마. '11월 말 · 12월 초 · 중순 · 쯤'처럼 며칠인지 하나로 안 정해지면 그 조건은 넣지 말고 정확한 날짜를 되물어. '연말(12-31)' · '크리스마스(12-25)' · '설(음력 1월 1일)'처럼 날짜가 하나로 정해지는 말은 그 날짜를 써. 목표를 못 맞추면 경고 내용을 그대로 알려 줘.",
      `지금 공정표: ${before.start} ~ ${before.end}, 일하는 날 ${before.work_days}일. 공정: ${before.blocks.map((b) => `${b.ko} ${b.start}~${b.end}`).join(", ")}`,
    ].join("\n"),
    allowed: () => planNumbersText(V3.plan as Plan | null),
  });
  let p: Plan;
  try {
    p = await loadPlan();
  } catch {
    return r;
  }
  await bot(null, <PlanCard p={p} />);
  return r;
}

/** 견적 · 공정표를 받아 V3에 둔다 (다른 작업자가 도구에서 쓸 때) */
export const buildQuote = () => loadQuote();
export const buildPlan = () => loadPlan();
export { ensureQuote };

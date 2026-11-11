// v10 전체 스크립트로 v2 API 대응 결과를 만든다: node v2_golden.js cases.json out.json
const fs = require("fs"), vm = require("vm");
const { load } = require("./v10_env.js");
const [casesPath, outPath] = process.argv.slice(2);
const ctx = load("2026-11-11");
const harness = `
function setState(q) {
  S.info.pyeong = q.pyeong; S.info.living = q.living; S.scope.cats = q.cats.slice(); S.picks = { ...q.picks };
  S.plan = q.plan ? { kind: "apt", id: q.plan.id, expanded: q.plan.expanded } : null;
  S.scope.kind = q.plan && q.plan.spaces ? "part" : "all"; S.scope.spaces = q.plan && q.plan.spaces ? q.plan.spaces.slice() : [];
  V3.balcony = q.balcony; S.tier = q.tier; if (q.mok) S.mok10 = JSON.parse(JSON.stringify(q.mok)); else delete S.mok10;
  V3.quote = null; V3.plan = null;
}
function quoteOf(q) {
  setState(q); const r = buildQuote(); V3.quote = r;
  for (const t of r.precise) { t.band = marketBand(t); t.gap = gapSteps(t); }
  const inp = { ...r.inp }; delete inp.pick; r.inp = inp;
  return r;
}
function planOf(c) {
  quoteOf(c.quote);
  S.info.move = c.move; V3.cons = JSON.parse(JSON.stringify(c.cons)); V3.props = JSON.parse(JSON.stringify(c.props)); V3.accepted = JSON.parse(JSON.stringify(c.accepted));
  const p = buildPlan();
  let trial = null;
  if (c.trial) {
    const T = c.trial.trade, st = c.trial.start, en = c.trial.end;
    const o = { weekendWork: V3.cons.weekendWork, avoid: V3.cons.avoid };
    const tr = CALC.fixPlan(p.trades.map((x) => x.trade === T ? { ...x, fixed: { start: st } } : x), p.start, o);
    const moved = tr.blocks.filter((b) => { const old = p.blocks.find((x) => x.trade === b.trade); return old && old.start !== b.start && b.trade !== T; }).map((b) => ({ trade: b.trade, ko: b.ko, start: b.start }));
    const clash = Object.entries(V3.accepted).some(([k, a]) => k !== T && !(en < a.start || st > a.end));
    const tomorrow = CALC.addDays(todaySeoul(), 1); let error = null;
    if (st < tomorrow) error = "시작일은 내일부터 1년 안으로 골라 주세요.";
    else if (en < st) error = "끝나는 날은 시작일과 같거나 뒤로 골라 주세요.";
    else if ((CALC.day(en) - CALC.day(st)) / 864e5 > 120) error = "공사 날짜는 120일 안으로 골라 주세요.";
    else if (CALC.isOff(st, o.weekendWork, o.avoid) || CALC.isOff(en, o.weekendWork, o.avoid)) error = "시작일과 끝나는 날은 일하는 날로 골라 주세요. 주말 · 공휴일은 쉬어요.";
    const t = p.trades.find((x) => x.trade === T);
    const wd = en >= st && (CALC.day(en) - CALC.day(st)) / 864e5 <= 120 ? workCount(st, en, o) : 0;
    trial = { trade: T, start: st, end: en, moved, clash, error, work_days: wd, need: t ? t.need : null, short: t ? wd < t.need : false };
  }
  return { start: p.start, end: p.end, work_days: p.work_days, blocks: p.blocks, days: p.days, trades: p.trades, warn: p.warn, trial, today: todaySeoul(), due_next: CALC.dueAt(todaySeoul(), 1) };
}
/* quoteCheck go() 숫자 부분 (v10 2163~2195 그대로, DOM 대신 값) */
function checkOf(c) {
  const q = quoteOf(c.quote);
  const t = q.precise.find((x) => x.trade === c.trade); if (!t) return { none: true };
  const v = Math.round(+c.amount);
  if (!(v > 0)) return { warn: "받은 금액을 넣어 주세요." };
  const sc = c.scope; const on = (k) => k.startsWith("x-") ? sc.extras && sc.extras[k.slice(2)] != null : !!sc[k];
  const supply = c.mode === "included" ? CALC.fromEntered(v, "included").supply : v;
  const extra = { lo: 0, hi: 0, notes: [] }; let m;
  if (t.trade === "dobae") {
    m = marketOf(t, { include_ceiling: !!on("ceiling") });
    if (on("removal")) { const a = m.lines.find((l) => l.key === "wall").qty + m.lines.find((l) => l.key === "ceiling").qty; extra.lo += Math.round(a * 600); extra.hi += Math.round(a * 2400); extra.notes.push(\`기존 벽지 철거: 시장 ㎡당 600~2,400원 × \${fmt(a)}㎡\`); }
    if (on("moving")) extra.notes.push("짐 이동 · 정리는 업체마다 달라 범위에 넣지 않았어요");
  } else {
    if (on("etc")) return { warn: "etc" };
    m = marketOf(t);
    const picks = {};
    for (const e of MARKET.P.mokgong.extras) if (on("x-" + e.key)) picks[e.key] = Math.max(1, Math.min(9, Math.round(+(sc.extras[e.key] || 1))));
    const door = m.lines.find((l) => l.key === "door");
    const casing = on("casing9") ? { doors: door ? door.qty : MARKET.P.mokgong.doors_default(mkInputs(t).area_m2 / 3.3058), with_door: !!door } : null;
    const xr = MARKET.extrasRange(picks, casing);
    extra.lo += xr.lo; extra.hi += xr.hi; extra.notes.push(...xr.notes);
    if (on("removal")) { extra.lo += 60000; extra.hi += 200000; extra.notes.push("철거 · 폐기물 · 양중: 6만~20만 원(시장 조사)"); }
  }
  const lo = m.lo + extra.lo, hi = m.hi + extra.hi;
  const where = supply < lo ? "low" : supply > hi ? "high" : "in";
  const pct = where === "low" ? CALC.percentVs(supply, lo) : where === "high" ? CALC.percentVs(supply, hi) : 0;
  const head = where === "in" ? \`보통 범위 안이에요\` : where === "high" ? \`보통보다 \${Math.abs(pct)}% 높아요\` : \`보통보다 \${Math.abs(pct)}% 낮아요\`;
  const span = hi - lo || 1, pad = 0.15 * span, blo = Math.min(supply, lo) - pad, bhi = Math.max(supply, hi) + pad, W = bhi - blo || 1;
  return { warn: null, trade: t.trade, supply, lo, hi, where, pct, head, notes: extra.notes, vat_unknown: c.mode === "unknown", bar: { band_left: ((lo - blo) / W) * 100, band_width: (span / W) * 100, me: ((supply - blo) / W) * 100 } };
}
function estOf(c) { V3.vp = { [c.trade]: c.prices }; return estimateFor({ trade: c.trade, grade: c.grade, lines: c.lines, total: c.std_total }, true); }
function enteredOf(c) { const v = CALC.fromEntered(c.amount, c.mode); return { ...v, pct: c.std_total ? CALC.percentVs(v.total, c.std_total) : null }; }
function calc7Of(c) { const { kind, ...i } = c; return CALC7[kind](i); }
`;
setTimeout(async () => {
  await vm.runInContext("estRefReady", ctx);
  vm.runInContext(harness + "\nthis.__h = { quoteOf, planOf, checkOf, estOf, enteredOf, calc7Of };", ctx);
  const H = vm.runInContext("this.__h", ctx);
  const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
  const out = cases.map((c) => { try { return { ok: H[c.fn](c.in) }; } catch (e) { return { err: String(e && e.stack || e).slice(0, 300) }; } });
  fs.writeFileSync(outPath, JSON.stringify(out)); console.log("js cases", out.length);
}, 100);

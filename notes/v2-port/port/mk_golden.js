const fs = require("fs"), vm = require("vm");
const [casesPath, outPath] = process.argv.slice(2);
const ctx = {}; vm.createContext(ctx);
const src = fs.readFileSync("calc10_base.js", "utf8") + ";" + fs.readFileSync("market_base.js", "utf8") + `
function roomsFor(py) { return py < 28 ? 2 : py < 38 ? 3 : 4; }
` + fs.readFileSync("market_gap_data.js", "utf8") + `
{ const base = MARKET.mokgong; MARKET.mokgong = function (input, p) {
    const r = base(input, p), x = input.extra_amount || 0; if (!x) return r;
    const r10k = (v) => Math.round(v / 10000) * 10000;
    r.lines.push({ key: "extras", name: "그 밖의 목공 (정해진 가격)", qty: null, unit: "식", unit_price: null, amount: x, note: "공공 기준과 같은 정해진 단가" });
    r.supply += x; r.lo = r10k(r.lo + x); r.hi = r10k(r.hi + x); return r;
  }; }
function runMarket(trade, input, p) { return trade === "dobae" ? MARKET.dobae(input, p) : MARKET.mokgong(input, p); }
function gap(trade, t, input) {
  const P = MARKET.P[trade], cur = { ...P, ...PUB_EQ[trade] };
  const out = [{ key: "vat", d: -t.vat }];
  let prev = runMarket(trade, input, cur).supply;
  const base = prev - t.supply;
  if (Math.abs(base) >= 1000) out.push({ key: "lines", d: base });
  for (const [k] of GAP_STEPS[trade]) { cur[k] = P[k]; const s = runMarket(trade, input, cur).supply; if (Math.abs(s - prev) >= 1000) out.push({ key: k, d: s - prev }); prev = s; }
  return { from: t.supply + t.vat, steps: out.map((s) => [s.key === "doors_default" ? "doors_count" : s.key, s.d]), to: prev };
}
this.MARKET = MARKET; this.gap = gap;`;
vm.runInContext(src, ctx);
const out = JSON.parse(fs.readFileSync(casesPath, "utf8")).map((c) => {
  if (c.kind === "extras") { const r = ctx.MARKET.extrasRange(c.picks, c.casing); return { lo: r.lo, hi: r.hi, notes: r.notes }; }
  const r = c.kind === "dobae" ? ctx.MARKET.dobae(c.input) : ctx.MARKET.mokgong(c.input);
  const g = ctx.gap(c.kind, c.pub, c.input);
  return { lines: r.lines.map((l) => [l.key, l.name, l.qty, l.unit_price, l.amount, l.note]), supply: r.supply, lo: r.lo, hi: r.hi, band: [r.band.lo, r.band.hi], gap: g };
});
fs.writeFileSync(outPath, JSON.stringify(out)); console.log("cases", out.length);

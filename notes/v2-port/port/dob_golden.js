const fs = require("fs"), vm = require("vm");
const [casesPath, outPath] = process.argv.slice(2);
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync("calc10_base.js", "utf8") + "\nthis.CALC=CALC;", ctx);
const out = JSON.parse(fs.readFileSync(casesPath, "utf8")).map((c) => { const r = ctx.CALC.dobae(c);
  return { lines: r.lines.map((l) => [l.key, l.name, l.qty, l.unit_price, l.amount, l.state, l.basis, l.calc, l.source]), supply: r.supply, vat: r.vat, total: r.total, man_days: r.man_days, steps: r.steps.map((s) => [s.key, s.name, s.half_days]), days: r.days, notes: r.notes }; });
fs.writeFileSync(outPath, JSON.stringify(out)); console.log("cases", out.length);

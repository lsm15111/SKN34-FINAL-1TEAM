const fs = require("fs"), vm = require("vm");
const [casesPath, outPath] = process.argv.slice(2);
const ctx = {}; vm.createContext(ctx);
ctx.DATA = JSON.parse(fs.readFileSync("../mvp/build/data.json", "utf8"));
vm.runInContext(fs.readFileSync("calc10_base.js", "utf8") + "\n" + fs.readFileSync("../mvp/v10/mok10.js", "utf8") + "\nthis.CALC=CALC;this.CALC10=CALC10;", ctx);
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const out = cases.map((c) => { const r = ctx.CALC10.mokgong(ctx.CALC, c.js); return r && { lines: r.lines.map((l) => [l.key, l.name, l.qty, l.unit_price, l.amount, l.state, l.basis, l.calc, l.source]), supply: r.supply, vat: r.vat, total: r.total, man_days: r.man_days, steps: r.steps.map((s) => [s.key, s.half_days]), days: r.days, notes: r.notes, extra: r.extra_amount }; });
fs.writeFileSync(outPath, JSON.stringify(out)); console.log("cases", out.length);

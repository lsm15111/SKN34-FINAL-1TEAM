const fs = require("fs"), vm = require("vm");
const [calcPath, plansPath, outPath] = process.argv.slice(2);
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(calcPath, "utf8") + "\nthis.CALC9 = CALC9;", ctx);
const plans = JSON.parse(fs.readFileSync(plansPath, "utf8"));
const combos = [{}, { expanded: false }, { ceiling: false }, { ceiling_h: 2.4 }, { kinds: ["room", "living", "hall", "dress"] }, { expanded: false, ceiling: false, kinds: ["kitchen", "entry"] }];
const out = [];
for (const p of plans) for (const [i, o] of combos.entries()) {
  const r = ctx.CALC9.fromPlan(p, o);
  out.push({ id: p.id, combo: i, opts: o, total: r.total, spaces: r.spaces.map((s) => ({ id: s.id, w: s.w, d: s.d, floor: s.floor, perim: s.perim, wall: s.wall, ceiling: s.ceiling, molding: s.molding, base: s.base, own_door: s.own_door, papered: s.papered })), low: r.low });
}
fs.writeFileSync(outPath, JSON.stringify(out));
console.log("cases", out.length);

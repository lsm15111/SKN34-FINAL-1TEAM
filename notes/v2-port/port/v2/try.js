const { load } = require("./v10_env.js"); const vm = require("vm");
const ctx = load("2026-11-11");
setImmediate(async () => {
  await new Promise((r) => setTimeout(r, 50));
  const r = vm.runInContext(`(async()=>{ await estRefReady; S.info.pyeong=32; S.scope.cats=["wallpaper","carpentry","floor"]; const q=buildQuote(); return JSON.stringify({code:q.code, at:q.at, total:q.total, ref:q.ref.map(t=>[t.cat,t.lo,t.hi]), band:q.band, p:q.precise.map(t=>[t.trade,t.total,t.band&&t.band.lo])}); })()`, ctx);
  console.log(await r);
});

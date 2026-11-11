// v10.html 전체 스크립트를 node vm에서 DOM 없이 돌린다(빈 Proxy로 DOM을 대신함).
const fs = require("fs"), vm = require("vm"), path = require("path");
const SITE = "C:/Workspace/SKN34/mitjip-mvp/site";
function any() {
  const f = function () { return P; };
  const P = new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "then") return undefined;
      if (k === Symbol.iterator) return function* () {};
      if (k === "length") return 0;
      if (k === "style") return P;
      return P;
    },
    set() { return true; },
    apply() { return P; },
    construct() { return P; },
    has() { return true; },
  });
  return P;
}
function load(today) {
  const html = fs.readFileSync(path.join(SITE, "v10.html"), "utf8");
  const s = html.indexOf("<script>") + 8, e = html.lastIndexOf("</script>");
  const code = html.slice(s, e);
  const D = any();
  const files = { "data.json": "data.json", "estimate_ref.json": "estimate_ref.json", "rag5.json": "rag5.json", "router.json": null };
  const ctx = {
    console, document: D, window: D, navigator: D, location: { search: "", hash: "", href: "http://x/v10.html" }, history: D,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    matchMedia: () => ({ matches: false, addEventListener() {} }), setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0, MutationObserver: function () { return { observe() {}, disconnect() {} }; }, IntersectionObserver: function () { return { observe() {}, disconnect() {} }; },
    ResizeObserver: function () { return { observe() {}, disconnect() {} }; }, AbortController, URL, URLSearchParams, Blob: function () {}, FileReader: function () {},
    Image: function () { return D; }, HTMLElement: function () {}, Node: function () {}, Event: function () {}, CustomEvent: function () {}, getComputedStyle: () => D, scrollTo() {}, addEventListener() {},
    TextEncoder, TextDecoder, Intl, structuredClone,
    fetch: (u) => { const f = String(u).split("?")[0]; const p = path.join(SITE, f); if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) return Promise.resolve({ ok: false, status: 404, json: async () => null, text: async () => "" });
      const t = fs.readFileSync(p, "utf8"); return Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(t), text: async () => t }); },
  };
  ctx.globalThis = ctx; ctx.self = ctx;
  if (today) { const RealDate = Date; const fixed = new RealDate(today + "T03:00:00Z").getTime();
    ctx.Date = class extends RealDate { constructor(...a) { if (a.length) super(...a); else super(fixed); } static now() { return fixed; } }; }
  vm.createContext(ctx);
  vm.runInContext(code, ctx, { filename: "v10.js" });
  return ctx;
}
module.exports = { load };

const { load } = require("./v10_env.js"); const vm = require("vm");
const ctx = load("2026-11-11");
setTimeout(() => { console.log(JSON.stringify(vm.runInContext("PLANS9.map((p) => [p.id, CALC9.fromPlan(p).est])", ctx))); }, 50);

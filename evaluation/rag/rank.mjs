// 화면 검색(rag.ts)으로 평가 질문마다 순위를 뽑는다. LLM 호출 없음.
//   node evaluation/rag/rank.mjs --rag frontend/components/v2/ai/rag.ts --corpus evaluation/rag/.cache/corpus.json \
//        --out evaluation/rag/.cache/rank_current.json [--name current] [--k 20] [--trade]
// --trade: 질문의 공정(도배 · 목공)을 검색에 넘긴다 (공정 에이전트가 넘기는 경우)
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i < 0 ? dflt : process.argv[i + 1];
};
const here = resolve(import.meta.dirname);
const ragPath = resolve(arg("rag", "frontend/components/v2/ai/rag.ts"));
const corpus = readFileSync(resolve(arg("corpus", `${here}/.cache/corpus.json`)), "utf-8");
const questions = readFileSync(resolve(arg("questions", `${here}/questions.jsonl`)), "utf-8")
  .split("\n")
  .filter(Boolean)
  .map((l) => JSON.parse(l));
const k = Number(arg("k", "20"));
const withTrade = process.argv.includes("--trade");

// 말뭉치는 이미 합쳐 두었으니 기본 자료 주소로만 돌려준다
globalThis.fetch = async (url) =>
  url === "/v2/rag5.json" ? { ok: true, json: async () => JSON.parse(corpus) } : { ok: false, json: async () => null };
const rag = await import(pathToFileURL(ragPath).href);
await rag.ragReady();

const out = { name: arg("name", "current"), rag: ragPath, version: rag.rag.index?.version, k, trade: withTrade, rankings: {}, enough: {} };
for (const q of questions) {
  const trade = withTrade && q.trade !== "공통" ? q.trade : undefined;
  const r = rag.ragSearch7(q.text, { k, trade });
  out.rankings[q.id] = r.hits.map((h) => h.ref);
  out.enough[q.id] = r.enough;
}
writeFileSync(resolve(arg("out", `${here}/.cache/rank_${out.name}.json`)), JSON.stringify(out, null, 1), "utf-8");
console.log(`${out.name}: ${questions.length}문항 · ${out.version}`);

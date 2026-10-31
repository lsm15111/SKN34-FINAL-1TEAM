// 공정 상담 상태를 이 탭에만 남긴다 (sessionStorage). 가견적 받기에 다녀와도 상담을 이어서 보이게.
// 이미 화면에 있는 결과(카드 포함) · 공정 의견 · 대화만 넣는다. 읽지 못하거나 모양이 지금과 다르면 버리고 처음부터 한다.
import type { Schemas } from "@/lib/backend/client";

type Out = Schemas["ConsultOut"];
type Plan = Schemas["PlanOut"];
export type Turn = { role: "user" | "assistant"; text: string };
export type Saved = { out: Out; plans: Record<string, Plan>; log: Turn[] };

// 저장 모양을 바꾸면 v 숫자를 올린다 (예전 값은 읽지 않는다). 같은 탭에서 계정을 바꿔도 섞이지 않게 계정 id를 넣는다
const key = (userId: string, projectId: string) => `mj_consult_v1_${userId}_${projectId}`;

type Obj = Record<string, unknown>;
const obj = (x: unknown): x is Obj => typeof x === "object" && x !== null && !Array.isArray(x);
const str = (x: unknown) => typeof x === "string";
const num = (x: unknown) => typeof x === "number";
const list = (x: unknown, ok: (v: unknown) => boolean = obj): x is unknown[] => Array.isArray(x) && x.every(ok);

// API 타입 전체가 아니라 화면이 바로 읽는 칸만 본다
const isTurn = (t: unknown) => obj(t) && (t.role === "user" || t.role === "assistant") && str(t.text);
const isPlan = (p: unknown) => obj(p) && str(p.summary) && list(p.steps) && list(p.visit_checks, str) && list(p.cautions);
const isQuote = (q: unknown) => obj(q) && num(q.total) && num(q.subtotal) && num(q.vat) && list(q.lines) && list(q.steps) && list(q.assumptions, str);
const isResult = (r: unknown) => obj(r) && str(r.trade) && str(r.label) && isQuote(r.quote);
const isSummary = (x: unknown) => x === null || (obj(x) && num(x.total) && num(x.subtotal) && num(x.vat) && str(x.days) && obj(x.basis_counts));
const isQuestion = (q: unknown) => obj(q) && str(q.field) && list(q.choices);
const isOut = (o: unknown) =>
  obj(o) && obj(o.card) && obj(o.trade_labels) && list(o.questions, isQuestion) && list(o.facts)
  && list(o.results, isResult) && list(o.schedule) && list(o.overlaps, str) && isSummary(o.summary);

function isSaved(x: unknown): x is Saved {
  return obj(x) && isOut(x.out) && obj(x.plans) && Object.values(x.plans).every(isPlan) && list(x.log, isTurn) && x.log.length > 0;
}

export function readSaved(userId: string, projectId: string): Saved | null {
  try {
    const raw = sessionStorage.getItem(key(userId, projectId));
    if (!raw) return null;
    const x: unknown = JSON.parse(raw);
    if (isSaved(x)) return x;
  } catch { /* 저장소를 못 쓰거나 값이 깨졌으면 처음부터 */ }
  clearSaved(userId, projectId); // 모양이 지금과 다르면 버린다
  return null;
}

export function writeSaved(userId: string, projectId: string, value: Saved) {
  try { sessionStorage.setItem(key(userId, projectId), JSON.stringify(value)); } catch { /* 못 남겨도 화면은 그대로 */ }
}

export function clearSaved(userId: string, projectId: string) {
  try { sessionStorage.removeItem(key(userId, projectId)); } catch { /* 저장소를 못 쓰면 지울 것도 없다 */ }
}

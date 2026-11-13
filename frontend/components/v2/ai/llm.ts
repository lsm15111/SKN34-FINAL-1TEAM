// AI 상담 한 턴 (POST /v2/ask). 지시문 · 도구 정의 · 반복 횟수 · 숫자 검사는 서버가 한다.
// 서버가 화면 도구(고객 상태 저장 · 단계 카드)를 부르면 여기서 실행하고
// 결과를 POST /v2/ask/{turn}로 보낸다. 답은 숫자 · 인용 검사를 마친 뒤 근거 · 이어 물을 질문과 함께 한 번에 온다.
// 자료 검색 · 이어 물을 질문 고르기는 서버가 한다.
import { v2Get, v2Post } from "../api";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AiTool = { name: string; execute: (a: any) => unknown };
type ToolCall = { id: string; name: string; arguments: Record<string, unknown> };
export type Cons = { weekendWork: boolean; endBy: string; startAfter: string; avoid: string[] };
export type AskOut = {
  done: boolean;
  turn: string | null;
  tool_calls: ToolCall[];
  text: string;
  failed: boolean;
  gate: "out" | null;
  intent: { label: string; confidence: number; source: string } | null;
  dropped: string[];
  cons: Cons | null;
  sources: AskSource[];
  cites_dropped: number;
  suggest: { text: string; ref: string | null }[];
};
export type AskSource = { ref: string; source_type: string; title: string; publisher: string; date: string; section: string; url: string; official: boolean };
export type AskBody = {
  kind: "chat" | "quote_explanation" | "schedule";
  message: string;
  profile?: Record<string, unknown>;
  quote?: unknown;
  plan?: unknown;
  materials?: unknown[];
  images?: string[];
};

/** AI를 쓸 수 있는지. 실패했으면 다음 질문 때 다시 묻는다 */
let health: Promise<boolean> | null = null;
export function localClaude() {
  if (!health)
    health = v2Get<{ ok: boolean; live: boolean }>("ask/health")
      .then((j) => !!j?.live)
      .catch(() => {
        health = null;
        return false;
      });
  return health;
}

/** 사진을 긴 변 1280px 안쪽 jpeg로 줄여 base64로. 화면에 보이는 원본은 그대로 둔다 */
export async function toImageBlock(file: Blob): Promise<string> {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k);
  c.height = Math.round(bmp.height * k);
  c.getContext("2d")?.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close?.();
  return c.toDataURL("image/jpeg", 0.8).split(",")[1];
}

const abortErr = () => Object.assign(new Error("질문을 멈췄어요."), { name: "AbortError" });
const aborted = (signal?: AbortSignal) => {
  if (signal?.aborted) throw abortErr();
};
/** 끊으면(처음부터) 서버 답을 기다리지 않고 바로 끝낸다. 늦게 온 답은 버린다 */
function race<T>(p: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return p;
  return new Promise<T>((res, rej) => {
    if (signal.aborted) return rej(abortErr());
    const on = () => rej(abortErr());
    signal.addEventListener("abort", on, { once: true });
    p.then(
      (v) => (signal.removeEventListener("abort", on), res(v)),
      (e) => (signal.removeEventListener("abort", on), rej(e)),
    );
  });
}

/** 한 턴: 서버가 화면 도구를 부르면 실행하고 결과를 보낸다 (서버가 도구 4번까지로 막는다) */
export async function runAsk(body: AskBody, tools: AiTool[], signal?: AbortSignal): Promise<AskOut> {
  aborted(signal);
  let out = await race(v2Post<AskOut>("ask", body), signal);
  for (let i = 0; i < 6 && !out.done && out.turn; i++) {
    aborted(signal);
    const results = [];
    for (const c of out.tool_calls) {
      const tool = tools.find((x) => x.name === c.name);
      let content: string;
      try {
        if (!tool) throw new Error("없는 도구");
        content = JSON.stringify((await tool.execute(c.arguments || {})) ?? { ok: true });
      } catch (e) {
        content = JSON.stringify({ error: String((e as Error)?.message || e) });
      }
      results.push({ id: c.id, content: content.slice(0, 20000) });
    }
    out = await race(v2Post<AskOut>(`ask/${encodeURIComponent(out.turn)}`, { results }), signal);
  }
  aborted(signal);
  return out;
}

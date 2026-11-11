// AI 한 번 부르기 (v10 localClaude · toImageBlock · runLocal).
// LLM 호출은 백엔드 POST /mvp/v2/llm 한 곳. 도구 실행은 브라우저에서 하고, 도구 호출이 끝날 때까지 최대 5번 주고받는다.
import { v2Get, v2Post } from "../api";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AiTool = { name: string; description: string; inputSchema: Record<string, unknown>; execute: (a: any) => unknown };
type Part = { type: "text"; text: string } | { type: "image"; data: string };
type ToolCall = { id: string; name: string; arguments: Record<string, unknown> };
type ChatMsg = { role: "user" | "assistant" | "tool"; content: string | Part[]; tool_calls?: ToolCall[]; tool_call_id?: string };
type LlmOut = { text: string; tool_calls: ToolCall[]; stop: "tool_calls" | "stop" | "refusal" };

/** AI를 쓸 수 있는지 (v10 api/health 자리). 실패했으면 다음 질문 때 다시 묻는다 */
let health: Promise<boolean> | null = null;
export function localClaude() {
  if (!health)
    health = v2Get<{ ok: boolean; live: boolean }>("llm/health")
      .then((j) => !!j?.live)
      .catch(() => {
        health = null;
        return false;
      });
  return health;
}

/** 사진을 긴 변 1568px 안쪽 jpeg로 줄여 base64로 */
export async function toImageBlock(file: Blob): Promise<Part> {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, 1568 / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k);
  c.height = Math.round(bmp.height * k);
  c.getContext("2d")?.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close?.();
  return { type: "image", data: c.toDataURL("image/jpeg", 0.85).split(",")[1] };
}

const aborted = (signal?: AbortSignal) => {
  if (signal?.aborted) throw Object.assign(new Error("질문을 멈췄어요."), { name: "AbortError" });
};

/** onText: 글이 올 때마다 지금까지의 글 */
export async function runLocal(system: string, q: string, files: Blob[], tools: AiTool[], onText: (t: string) => void, signal?: AbortSignal) {
  const content: Part[] = [];
  for (const f of files) {
    try {
      content.push(await toImageBlock(f));
    } catch {}
  }
  content.push({ type: "text", text: q });
  const messages: ChatMsg[] = [{ role: "user", content }];
  const defs = tools.map((t) => ({ name: t.name, description: t.description, parameters: t.inputSchema }));
  let text = "", nudged = false;
  for (let round = 0; round < 5; round++) {
    aborted(signal);
    const j = await v2Post<LlmOut>("llm", { system, messages, tools: defs });
    aborted(signal);
    const t = j?.text || "";
    const calls = j?.tool_calls || [];
    if (t) {
      text = text ? text + "\n" + t : t;
      onText(text);
    }
    if (j?.stop === "refusal") throw { code: "refusal", text };
    messages.push({ role: "assistant", content: t, ...(calls.length ? { tool_calls: calls } : {}) });
    if (j?.stop !== "tool_calls" || !calls.length) {
      if (!text && !nudged && round < 4) {
        nudged = true;
        if (!t && !calls.length) messages.pop();
        const last = messages[messages.length - 1], ask = "(위 도구 결과로 고객 질문에 대한 답 글을 해요체로 써 주세요.)";
        if (last.role === "user" && Array.isArray(last.content)) last.content.push({ type: "text", text: ask });
        else messages.push({ role: "user", content: ask });
        continue;
      }
      return text || "답이 비어 있어요. 다시 물어봐 주세요.";
    }
    for (const b of calls) {
      const tool = tools.find((x) => x.name === b.name);
      let out: string;
      try {
        if (!tool) throw new Error("없는 도구");
        out = JSON.stringify((await tool.execute(b.arguments || {})) ?? { ok: true });
      } catch (e) {
        out = JSON.stringify({ error: String((e as Error)?.message || e) });
      }
      messages.push({ role: "tool", tool_call_id: b.id, content: out });
    }
  }
  return text || "답을 마무리하지 못했어요. 다시 물어봐 주세요.";
}

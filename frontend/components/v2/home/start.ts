// 첫 화면에서 상담 시작하기 (v10 startWithLook · startWithAsk · startWithTool)
import type { Style } from "../data";
import type { Look } from "../looks";
import { goChat } from "../V2App";

export const startWithLook = (st: Style, lk: Look) => goChat("look", { style: st.id, look: lk.id });
export const startWithAsk = (q: string) => goChat("ask", { ask: q });
export const startWithTool = (t: "calc" | "check") => goChat("tool", { tool: t });

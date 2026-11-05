// 확정 공정표(시안 WPlanDone)에만 쓰는 화면 말 · 막대 줄 만들기. 날짜 · 일수는 API(계산 엔진) 값을 고르고 형식만 바꾼다.
// 서버 · 브라우저 양쪽에서 쓴다.
import type { Schemas } from "@/lib/backend/client";
import { euro } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { span } from "@/components/schedule/text";

export type Plan = Schemas["PlanOut"];
export type Block = Schemas["PlanBlockOut"];
export type Day = Schemas["PlanDayOut"];
export type PlanChange = Schemas["PlanChangeOut"];
export type CellState = Block["state"];

/** 칸 상태 말: 수락함 · 수락 전 · 예상 */
export const STATE_TEXT: Record<CellState, string> = { confirmed: "날짜 수락함", pending: "수락 전", expected: "예상" };

/** 막대 색: 수락함 · 수락 전(새 날짜) · 예상 자리 · 지금(바꾸기 전 날짜) */
export type Tone = CellState | "now";

/** 막대 한 줄: 이름 칸 · 보조 줄 · 색 · 막대 안 글 · 그 줄에 칠할 날 */
export type BarRow = { key: string; name: string; vendor?: string | null; sub: string; tone: Tone; text: string; on: (d: Day) => boolean };

/** 날짜 칸이 이 블록의 날인지 (일은 같은 공정, 건조 · 청소는 같은 종류) */
export const belongs = (b: Block, d: Day) => (b.kind === "work" ? d.kind === "work" && d.trade === b.trade : d.kind === b.kind);

const SUB: Record<string, string> = { dry: "창문 닫기", clean: "고객이 직접" };

/** 블록 보조 줄: 일은 "11.16(월) ~ 11.18(수) · 3일", 건조 · 청소는 "2일 · 창문 닫기" */
export const blockSub = (b: Block) => (b.kind === "work" ? `${span(b.start, b.end)} · ${b.days}일` : `${b.days}일${SUB[b.kind] ? ` · ${SUB[b.kind]}` : ""}`);

/** 확정 공정표 막대 줄: 블록마다 상태 색과 말 */
export const blockRows = (blocks: Block[]): BarRow[] =>
  blocks.map((b) => ({
    key: `${b.kind}-${b.trade ?? ""}-${b.start}`,
    name: b.label,
    vendor: b.kind === "work" ? b.vendor_name : null,
    sub: blockSub(b),
    tone: b.state,
    text: STATE_TEXT[b.state],
    on: (d: Day) => belongs(b, d),
  }));

/** 새 날짜 미리 보기 줄: 바꾸는 공정은 '지금'(지금 공정표의 그 공정 날) + '새 날짜' 두 줄, 나머지는 바꾼 뒤 공정표 그대로 */
export function changeRows(c: PlanChange, now: Day[]): BarRow[] {
  const nowDays = new Set(now.filter((d) => d.kind === "work" && d.trade === c.trade).map((d) => d.day));
  const tName = tradeLabel(c.trade);
  return c.blocks.flatMap((b): BarRow[] => {
    const row = blockRows([b])[0];
    if (!(b.kind === "work" && b.trade === c.trade)) return [row];
    return [
      { key: `now-${c.trade}`, name: `${tName} · 지금`, sub: span(c.current_start, c.current_end), tone: "now", text: "지금", on: (d) => nowDays.has(d.day) },
      { ...row, name: `${tName} · 새 날짜`, vendor: null, tone: "pending", text: "새 날짜" },
    ];
  });
}

/** 공사 기간 끝 = 마지막 일 블록의 끝 (건조 · 청소 빼고). 일이 없으면 공정표 끝 */
export const workEnd = (p: Pick<Plan, "blocks" | "end">) => p.blocks.filter((b) => b.kind === "work").at(-1)?.end ?? p.end;

/** "11.24(화) ~ 11.26(목)" 뒤에 로/으로 (마지막 요일 글자의 받침으로) */
export const spanRo = (sp: string) => {
  const w = sp.at(-2) ?? "";
  return `${sp}${euro(w).slice(w.length)}`;
};

/** 머리 줄: "목공 날짜 수락함 · 도배 날짜 수락 전" (공정 순서대로, 같은 상태는 묶는다) */
export function stateLine(blocks: Block[]): string {
  const works = blocks.filter((b) => b.kind === "work" && b.trade);
  const order: CellState[] = ["confirmed", "pending", "expected"];
  const tail: Record<CellState, string> = { confirmed: "날짜 수락함", pending: "날짜 수락 전", expected: "예상 자리" };
  return order
    .map((st) => works.filter((b) => b.state === st).map((b) => tradeLabel(b.trade ?? "")))
    .map((names, i) => (names.length ? `${names.join(" · ")} ${tail[order[i]]}` : ""))
    .filter(Boolean)
    .join(" · ");
}

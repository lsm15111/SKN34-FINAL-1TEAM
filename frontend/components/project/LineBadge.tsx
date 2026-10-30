import type { LineState } from "@/lib/types";
import { LINE_STATE_LABEL } from "@/lib/types";

const CLS: Record<LineState, string> = { in: "mj-b-in", bundle: "mj-b-bundle", sep: "mj-b-sep", opt: "mj-b-opt", cond: "mj-b-cond", no: "mj-b-no" };

export function LineBadge({ state }: { state: LineState }) {
  return <span className={`mj-badge ${CLS[state]}`}>{LINE_STATE_LABEL[state]}</span>;
}

export function LineStateLegend() {
  const d: Record<LineState, string> = { in: "금액에 들어 있어요", bundle: "다른 줄 금액에 들어 있어요", sep: "따로 받는 금액이에요", opt: "고르면 더해져요", cond: "실측 보고 정해요", no: "이번 공사에서 안 해요" };
  return (
    <dl style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", margin: 0, fontSize: "var(--fs-sm)" }}>
      {(Object.keys(d) as LineState[]).map((k) => (
        <div key={k} style={{ display: "flex", gap: 6, alignItems: "center" }}><dt><LineBadge state={k} /></dt><dd style={{ margin: 0, color: "var(--ink-sub)" }}>{d[k]}</dd></div>
      ))}
    </dl>
  );
}

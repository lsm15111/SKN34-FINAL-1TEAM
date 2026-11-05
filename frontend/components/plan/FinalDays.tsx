// 확정 공정표 날짜별 표 (시안 WPlanDone '날짜별로 보기'): 날짜 · 공정과 상태 · 업체 · 하는 일.
// 상태 · 업체 · 하는 일은 API 값 그대로다(업체는 그 공정 블록의 업체 이름). 좁은 화면은 업체를 공정 칸 아래에 둔다.
import { Check } from "@/components/vendors/icons";
import { md } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { STATE_TEXT, type Block, type CellState, type Day, type Plan } from "./text";
import s from "./plan.module.css";

const None = () => <><span aria-hidden="true">—</span><span className="mj-sr">없음</span></>;

export function StateMark({ state }: { state: CellState }) {
  if (state === "confirmed") return <span className="mj-st mj-st-ok"><Check />{STATE_TEXT.confirmed}</span>;
  return <span className={`${s.chip}${state === "pending" ? ` ${s.chipNow}` : ""}`}>{STATE_TEXT[state]}</span>;
}

function who(d: Day, blocks: Block[]) {
  if (d.kind === "work") return blocks.find((b) => b.kind === "work" && b.trade === d.trade)?.vendor_name ?? <span className="mj-sub">아직 안 정함</span>;
  if (d.kind === "clean") return "직접";
  return <span className="mj-sub">업체 없음</span>;
}

/** 일이 없는 날: 공휴일 이름 · 공정 날짜 안의 쉬는 날(휴일) · 공정 사이 빈 날(공사 없는 날). API는 둘 다 off로 준다 */
function offText(d: Day, blocks: Block[]) {
  if (d.holiday) return `휴일 · ${d.holiday}`;
  return blocks.some((b) => b.kind === "work" && b.start <= d.day && d.day <= b.end) ? "휴일" : "공사 없는 날";
}

function what(d: Day, blocks: Block[]) {
  if (d.kind === "work") return tradeLabel(d.trade ?? "");
  return blocks.find((b) => b.kind === d.kind)?.label ?? "";
}

/** quiet: 모든 공정을 수락함 → 줄마다 '날짜 수락함'을 쓰지 않는다 */
export function FinalDays({ plan, quiet = false }: { plan: Plan; quiet?: boolean }) {
  return (
    <div className={s.tblBox}>
      <table className={`mj-table mj-num ${s.days}`}>
        <caption className={s.cap}>날짜별 할 일 · {md(plan.start)} ~ {md(plan.end)} (입주 청소까지)</caption>
        <thead><tr><th scope="col">날짜</th><th scope="col">공정</th><th scope="col" className={s.vCol}>업체</th><th scope="col">하는 일</th></tr></thead>
        <tbody>
          {plan.days.map((d) =>
            d.kind === "off" ? (
              <tr key={d.day} className={s.offRow}>
                <th scope="row">{md(d.day)}</th>
                <td>{offText(d, plan.blocks)}</td>
                <td className={s.vCol}><None /></td>
                <td><None /></td>
              </tr>
            ) : (
              <tr key={d.day}>
                <th scope="row">{md(d.day)}</th>
                <td>
                  <span className={s.what}>{what(d, plan.blocks)} {quiet && d.state === "confirmed" ? null : <StateMark state={d.state} />}</span>
                  <span className={`mj-small ${s.vIn}`}>{who(d, plan.blocks)}</span>
                </td>
                <td className={s.vCol}>{who(d, plan.blocks)}</td>
                <td>{d.names.join(", ")}</td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

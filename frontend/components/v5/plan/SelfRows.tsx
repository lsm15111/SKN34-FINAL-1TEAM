// 반셀프 직접 할 일 줄(공정표 '고객이 직접'): API(계산 엔진)가 준 블록 kind diy를 그대로 늘어놓아요.
// 날짜 · 기간을 새로 계산하지 않아요. 예상 · 확정 공정표가 같은 꼴(범례 줄)로 써요.
import type { ApiPlan } from "@/lib/v5/api/project";
import { dateShort, rangeText } from "@/lib/v5/format";
import s from "./planv3.module.css";

type Block = ApiPlan["blocks"][number];

export const selfBlocks = (plan: ApiPlan): Block[] => plan.blocks.filter((b) => b.kind === "diy");

const when = (b: Block) => (b.start === b.end ? dateShort(b.start) : rangeText(b.start, b.end, { weekday: true }));

/** '페인트(문틀 · 몰딩) 칠하기 12.1(화)~12.4(금) · 고객이 직접' 줄들(범례 목록 안에 넣어요) */
export function SelfRows({ plan }: { plan: ApiPlan }) {
  return selfBlocks(plan).map((b) => (
    <li key={`diy-${b.label}-${b.start}`}>
      <i aria-hidden="true" className={s.self} />
      <b>{b.label}</b> <span className="mj-num">{when(b)} · 고객이 직접</span>
    </li>
  ));
}

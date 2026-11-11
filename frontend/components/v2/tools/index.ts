// tools 단계 함수를 F 표에 넣는다: 셀프 계산기 · 체크리스트 (v10 calcStep · checkStep · STEP_FN.calc/check)
import { createElement } from "react";
import { bot, register } from "../engine";
import { STEP_NAMES } from "../flow";
import { CalcCard } from "./CalcCard";
import { CheckCard } from "./CheckCard";

export async function calcStep(kind?: "wall" | "trim" | "paint") {
  await bot(null, createElement(CalcCard, { kind }));
}
export async function checkStep(which?: "before" | "contract" | "after") {
  await bot(null, createElement(CheckCard, { which }));
}

register({ calcStep, checkStep });
/* 상담 화면 단계 이름 → 도구 카드 (v10 STEP_FN.calc · STEP_FN.check). stepFn("calc")가 이 이름으로 F를 찾는다 */
STEP_NAMES.calc = "calcStep";
STEP_NAMES.check = "checkStep";

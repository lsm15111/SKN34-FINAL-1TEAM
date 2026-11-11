// intake(시작 · 고르기) 단계 함수를 F 표에 넣는다
import { register } from "../engine";
import { openLooks } from "./Looks";
import { planQtyTool, planStep } from "./PlanStep";
import { pp9Context, pp9Kinds, pp9Measured, pp9Qty, resetPlans } from "./plans";
import { budgetStep, infoStep, photoStep, scopeStep } from "./steps";
import { afterStyle, chooseLook, chooseStyle, collapseRail, guideStep, reopenStyles, resetRail, startLook, welcome } from "./StyleRail";

register({
  welcome,
  reopenStyles,
  collapseRail,
  chooseStyle,
  chooseLook,
  afterStyle,
  startLook,
  openLooks,
  guideStep,
  infoStep,
  scopeStep,
  budgetStep,
  photoStep,
  planStep,
  planQtyTool,
  pp9Measured,
  pp9Context,
  pp9Kinds,
  pp9Qty,
  resetLocal: () => {
    resetRail();
    resetPlans();
  },
});

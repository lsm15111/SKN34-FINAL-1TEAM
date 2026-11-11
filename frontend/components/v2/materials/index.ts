// materials 단계 함수를 F 표에 넣는다 (자재 고르기 · 목공 · 정리)
import { register } from "@/components/v2/engine";
import { setAllTier } from "./actions";
import { openCompare, openSheet } from "./Sheets";
import { mok10St, mok10Sync, redraw } from "./state";
import { finish, matStep, resetMaterials, setMatFull, summaryText } from "./steps";

register({
  matStep,
  refreshMat: () => redraw(),
  setAllTier,
  openSheet,
  openCompare,
  finish,
  mok10Sync,
  mok10St,
  setMatFull,
  summaryText,
  resetMaterials,
});

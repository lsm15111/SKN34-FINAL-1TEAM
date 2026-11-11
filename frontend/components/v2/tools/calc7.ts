// 셀프 계산기 수량 계산은 백엔드 POST /mvp/v2/calc7 (v10 CALC7). 부르는 곳은 이 파일 하나.
// 입력 · 출력은 v10 CALC7 함수 그대로라고 가정한다: { kind, ...입력 } → 결과 객체
import { v2Post } from "../api";

export type WallIn = { w: number; d: number; hgt: number; doors: number; windows: number; ceiling: boolean; rollW: number; rollLen: number; repeat: number; loss: number };
export type WallOut = { wall_m2: number; ceiling_m2: number; strips: number; cStrips: number; per_roll: number; rolls_raw: number; rolls: number };
export type TrimIn = { w: number; d: number; doors: number; pieceLen: number; loss: number };
export type TrimOut = { molding_m: number; molding_pcs: number; base_m: number; base_pcs: number };
export type PaintIn = { w: number; d: number; hgt: number; doors: number; windows: number; ceiling: boolean; coats: number; cover: number };
export type PaintOut = { area_m2: number; liters: number; n18: number; n4: number };

export const CALC7 = {
  wallpaper: (i: WallIn) => v2Post<WallOut>("calc7", { kind: "wallpaper", ...i }),
  trim: (i: TrimIn) => v2Post<TrimOut>("calc7", { kind: "trim", ...i }),
  paint: (i: PaintIn) => v2Post<PaintOut>("calc7", { kind: "paint", ...i }),
};

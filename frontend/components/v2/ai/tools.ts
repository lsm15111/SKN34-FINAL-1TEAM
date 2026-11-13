// AI가 화면을 움직이는 도구의 실행 부분 (v10 claudeTools).
// 도구 이름 · 설명 · 입력 모양은 서버(backend/app/v2/ask_tools.py)가 정한다. 여기서는 받은 값을 검사하고 실행만 한다.
// 공사비(price_reference) · 공정표 조건(set_schedule_constraints) · 지식 검색(search_knowledge) ·
// 이어 물을 질문(suggest_questions)은 서버가 실행한다.
import { flashBoard } from "../Board";
import { CATS, manwon, SPACES, STYLES, TIER_ORDER, TIERS } from "../data";
import { moveLabel } from "../dates";
import { autoPick, fillPicks, STEP_NAMES, tierFromBudget } from "../flow";
import { DATA, S, touch, type Tier } from "../store";
import type { AiTool } from "./llm";

export type After = { step?: string };

/** show_step이 고를 수 있는 단계 */
const stepKeys = () => [...new Set(["styles", "guide", ...Object.keys(STEP_NAMES)])];

export function claudeTools(applied: string[], after: After): AiTool[] {
  const changed = () => {
    touch();
    flashBoard();
  };
  return [
    {
      name: "set_style",
      execute: ({ style_id }: { style_id: string }) => {
        const st = STYLES.find((s) => s.id === style_id);
        if (!st) throw new Error("없는 스타일");
        S.style = st.id;
        if (S.far >= 5) autoPick();
        changed();
        applied.push(st.ko);
        return { ok: true };
      },
    },
    {
      name: "set_home_info",
      execute: (a: { pyeong?: number; region?: string; living?: "living" | "vacant"; move?: string }) => {
        if (a.pyeong != null) {
          if (!(a.pyeong >= 10 && a.pyeong <= 90)) throw new Error("평형은 10~90");
          S.info.pyeong = Math.round(a.pyeong);
          applied.push(`${S.info.pyeong}평`);
        }
        if (a.region) {
          S.info.region = String(a.region).slice(0, 30);
          applied.push(S.info.region);
        }
        if (a.living === "living" || a.living === "vacant") {
          S.info.living = a.living;
          applied.push(a.living === "living" ? "살면서 공사" : "빈집");
        }
        if (a.move && /^\d{4}-\d{2}(-\d{2})?$/.test(a.move)) {
          S.info.move = a.move;
          applied.push(`${moveLabel(a.move)} 입주`);
        }
        changed();
        return { ok: true };
      },
    },
    {
      name: "set_scope",
      execute: ({ kind, spaces = [] }: { kind: "all" | "part"; spaces?: string[] }) => {
        if (kind !== "all" && kind !== "part") throw new Error("범위는 all · part");
        S.scope.kind = kind;
        if (kind === "all") {
          S.scope.spaces = [];
          S.scope.cats = [];
          applied.push("집 전체");
        } else {
          const sp = SPACES.filter((s) => spaces.includes(s.id));
          if (!sp.length) throw new Error("공간을 하나 이상 골라야 해요");
          const c = new Set(sp.flatMap((s) => s.cats));
          S.scope.spaces = sp.map((s) => s.id);
          S.scope.cats = CATS.filter((x) => c.has(x.id)).map((x) => x.id);
          applied.push(sp.map((s) => s.ko).join(", "));
        }
        if (S.far >= 5) fillPicks();
        changed();
        return { ok: true, cats: S.scope.cats };
      },
    },
    {
      name: "set_budget",
      execute: ({ budget_manwon, tier }: { budget_manwon?: number; tier?: Tier }) => {
        if (budget_manwon != null) {
          if (!(budget_manwon >= 100 && budget_manwon <= 100000)) throw new Error("예산 범위가 이상해요");
          S.budget = Math.round(budget_manwon);
          S.budgetUnknown = false;
          applied.push(manwon(S.budget));
          if (!tier && S.tierBy !== "me") S.tier = tierFromBudget();
        }
        if (tier) {
          if (!TIER_ORDER.includes(tier)) throw new Error("없는 등급");
          S.tier = tier;
          S.tierBy = "me";
        }
        applied.push(TIERS[S.tier]);
        if (S.far >= 5) autoPick();
        changed();
        return { ok: true, tier: S.tier };
      },
    },
    {
      name: "pick_material",
      execute: ({ material_id }: { material_id: string }) => {
        const m = DATA.materials.find((x) => x.id === material_id);
        if (!m) throw new Error("없는 자재 id");
        S.picks[m.cat] = m.id;
        changed();
        applied.push(m.name);
        return { ok: true };
      },
    },
    {
      name: "show_step",
      execute: ({ step }: { step: string }) => {
        if (!stepKeys().includes(step)) throw new Error("없는 단계");
        after.step = step;
        return { ok: true };
      },
    },
  ];
}

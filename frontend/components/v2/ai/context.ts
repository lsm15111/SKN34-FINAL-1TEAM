// AI에 넘기는 고객 상태 글 (v10 contextText + pp9Context). 도면 수량은 백엔드 계산(GET /mvp/plans/{id}/qty) 결과를 그대로 쓴다.
import { mvpGet } from "../api";
import { CAT, GUIDE, manwon, priceText, TIERS } from "../data";
import { F } from "../engine";
import { scopeCats, styleOf } from "../flow";
import { DATA, S } from "../store";

type PlanQty = { wall_m2: string | number; ceiling_m2: string | number; rolls: { kind: string; rolls: number }[]; molding_m: string | number; base_m: string | number; doors: number };

async function planContext() {
  if (S.plan?.kind !== "apt" || !S.plan.id) return null;
  const qs = new URLSearchParams({ expanded: String(S.plan.expanded !== false) });
  for (const k of (F.pp9Kinds?.() as string[] | null | undefined) || []) qs.append("kinds", k);
  try {
    const t = await mvpGet<PlanQty>(`plans/${encodeURIComponent(S.plan.id)}/qty?${qs}`);
    const roll = (k: string) => t.rolls.find((r) => r.kind === k)?.rolls;
    return `도면 수량(계산 엔진, 실측 전 어림): 벽 도배 ${t.wall_m2}㎡ · 천장 ${t.ceiling_m2}㎡ · 실크 ${roll("silk")}롤 · 합지 ${roll("hapji")}롤 · 몰딩 ${t.molding_m}m · 걸레받이 ${t.base_m}m · 방문 ${t.doors}개`;
  } catch {
    return null;
  }
}

export async function contextText() {
  const st = styleOf(S.style);
  const picks = Object.entries(S.picks)
    .map(([c, id]) => {
      const m = DATA.materials.find((x) => x.id === id);
      return m ? `${CAT[c]?.ko}: ${m.brand} ${m.name} (${TIERS[m.tier]}, ${priceText(m.price)})` : null;
    })
    .filter(Boolean);
  const inScope = new Set(scopeCats().map((c) => c.id));
  const mats = DATA.materials
    .filter((m) => inScope.has(m.cat))
    .map((m) => `- ${m.id} [${CAT[m.cat]?.ko}/${TIERS[m.tier]}${m.rank ? "/" + m.rank + "위" : ""}] ${m.brand} ${m.name} | ${(m.spec || "").slice(0, 70)} | ${priceText(m.price)}${(m.tags || []).length ? " | " + m.tags.join(",") : ""}`)
    .join("\n");
  return [
    "## 고객 상태",
    `스타일: ${st ? st.ko : "미정"} / 평형: ${S.info.pyeong ? S.info.pyeong + "평" : "모름"} / 지역: ${S.info.region || "모름"} / 공사 중: ${S.info.living || "모름"} / 범위: ${S.scope.kind === "part" ? S.scope.cats.map((c) => CAT[c]?.ko).join(", ") : S.scope.kind === "all" ? "집 전체" : "미정"} / 예산: ${S.budget ? manwon(S.budget) : "미정"} / 등급: ${TIERS[S.tier]} / 지금 단계: ${S.step}`,
    `고른 자재: ${picks.length ? picks.join("; ") : "없음"}`,
    `사진: 지금 집 ${S.photos.length}장, 참고 ${S.refs.length}장 / 도면: ${S.plan ? S.plan.name : "없음"}`,
    await planContext(),
    "## 공정 순서",
    GUIDE.map((g, i) => `${i + 1}. ${g.n}(${g.d}): ${g.t}`).join("\n"),
    "## 믿집 자재 자료 (가격은 자재값, 시공비 제외)",
    mats,
  ].join("\n");
}

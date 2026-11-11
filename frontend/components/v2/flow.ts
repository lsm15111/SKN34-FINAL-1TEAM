// 흐름 공통: 단계 옮기기 · 추천 순서 · 예산으로 등급 · 스타일 사진 (v10 '상태 · 도우미' · '추천 · 등급' · '화면 전환').
// 금액 · 수량은 여기서 만들지 않는다. 추천 점수는 자재를 늘어놓는 순서일 뿐이다.
import { CATS, type Material, STEP_INDEX, STEPS, STYLES, TIER_ORDER, type Style } from "./data";
import { F } from "./engine";
import { lookOf, type Look, toneFit } from "./looks";
import { type Srcs, view } from "./photo";
import { DATA, S, touch } from "./store";

export function scopeCats() {
  return S.scope.cats.length ? CATS.filter((c) => S.scope.cats.includes(c.id)) : CATS;
}

/** 추천 점수: 사진(느낌)을 골랐으면 색 비중을 키우고, 등급 점수도 같이 키워 등급은 그대로 지킨다 */
export function score(m: Material) {
  const lk = lookOf(S.look), on = !!(lk && lk.style === S.style);
  let s = 0;
  if (S.style && (m.styles || []).includes(S.style)) s += on ? 1 : 2;
  const d = Math.abs(TIER_ORDER.indexOf(m.tier) - TIER_ORDER.indexOf(S.tier));
  if (m.rank && m.rank <= 5) s += 1;
  if ((m.tags || []).includes("요즘 인기")) s += 0.5;
  return s + (on ? (d === 0 ? 6 : d === 1 ? 2 : 0) + toneFit(m) * 2 : d === 0 ? 3 : d === 1 ? 1 : 0);
}
export const rankOf = (m: Material) => m.rank || 99;
export function recommend(cat: string) {
  return DATA.materials
    .filter((m) => m.cat === cat)
    .map((m) => ({ m, s: score(m) }))
    .sort((a, b) => b.s - a.s || rankOf(a.m) - rankOf(b.m))
    .slice(0, 3)
    .map((x) => x.m);
}
export const lowP = (m: Material) => m.price?.min ?? m.price?.max ?? Infinity;
export function sortMats(list: Material[], how: string) {
  const by: Record<string, (a: Material, b: Material) => number> = {
    rec: (a, b) => score(b) - score(a) || rankOf(a) - rankOf(b),
    pop: (a, b) => rankOf(a) - rankOf(b),
    low: (a, b) => lowP(a) - lowP(b),
    high: (a, b) => (b.price?.max ?? b.price?.min ?? -1) - (a.price?.max ?? a.price?.min ?? -1),
  };
  return [...list].sort(by[how] ?? by.rec);
}

/** 범위 안 공정마다 추천 1순위를 고른다. 바뀐 개수를 돌려준다 */
export function autoPick() {
  let n = 0;
  for (const c of scopeCats()) {
    const r = recommend(c.id)[0];
    if (r && S.picks[c.id] !== r.id) {
      S.picks[c.id] = r.id;
      n++;
    }
  }
  if (scopeCats().some((c) => c.id === "carpentry")) F.mok10Sync?.();
  return n;
}
/** 빈 공정만 추천 1순위로 채운다 */
export function fillPicks() {
  for (const c of scopeCats())
    if (!S.picks[c.id]) {
      const r = recommend(c.id)[0];
      if (r) S.picks[c.id] = r.id;
    }
  if (scopeCats().some((c) => c.id === "carpentry")) F.mok10Sync?.();
}
/** 예산 → 등급. 평당 예산(만 원)으로 나눈다 (v10과 같은 경계). 금액을 만들지 않고 고르기만 한다 */
export function tierFromBudget(): "economy" | "basic" | "premium" {
  if (S.budgetUnknown || !S.budget) return "basic";
  const share = S.scope.kind === "part" ? Math.max(S.scope.cats.length / CATS.length, 0.3) : 1;
  const per = S.budget / ((S.info.pyeong || 32) * share);
  return per < 130 ? "economy" : per < 220 ? "basic" : "premium";
}
export function priceFlags(m: Material) {
  const n = m.price?.note || "";
  return [/시공\s*포함|설치\s*포함|시공비\s*포함/.test(n) ? "시공 포함" : null, /추정/.test(n) ? "추정" : null].filter(Boolean).join(" · ");
}

/* ---------- 단계 ---------- */
export function setStep(s: string) {
  S.step = s;
  S.far = Math.max(S.far, STEP_INDEX[s] ?? 0);
  touch();
}
/** 지난 단계를 고친 뒤에는 가장 멀리 갔던 단계로 돌아간다 */
export function resumeStep() {
  S.step = S.far >= STEPS.length ? "done" : STEPS[S.far][0];
  touch();
}
export function proceed(next: () => void) {
  if (S.far > (STEP_INDEX[S.step] ?? 0)) {
    if (S.far >= 5) F.matStep();
    else stepFn(STEPS[S.far][0])();
  } else next();
}
/** 단계 이름 → 그 단계를 여는 함수 (v10 STEP_FN) */
export const STEP_NAMES: Record<string, string> = {
  styles: "reopenStyles", guide: "guideStep", info: "infoStep", scope: "scopeStep", budget: "budgetStep", photo: "photoStep",
  plan: "planStep", materials: "matStep", finish: "finish", quote: "quoteStep", sched: "schedStep",
};
export const stepFn = (id: string) => () => (id === "guide" ? F.guideStep(false) : F[STEP_NAMES[id]]?.());

/* ---------- 스타일 사진 ---------- */
/** 느낌 사진. 사진이 없는 느낌은 그 느낌의 색으로 그린 방 그림(F.roomSvg) */
export const lookSrcs = (lk: Look): Srcs => {
  const draw = lk.img ? null : (F.roomSvg?.(lk) as string | undefined) ?? null;
  return { ai: lk.img || draw, mfg: lk.img || draw, free: lk.img || draw, color: lk.tone.wall };
};
export function styleSrcs(st: Style, i = 0): Srcs {
  const d = DATA.styles[st.id] || ({} as Record<string, unknown>);
  const lk = lookOf(S.look);
  if (i === 0 && lk && lk.style === st.id && S.style === st.id) return lookSrcs(lk);
  const free = (d.img_free as string[] | undefined) || [];
  if (view.empty && d.img_empty) return { ai: d.img_empty as string, mfg: d.img_empty as string, free: d.img_empty as string, color: st.pal[1] };
  return { ai: `img/ai/style-${st.id}.jpg`, mfg: (d.img_mfg as string) || null, free: free[i] || free[0] || null, color: st.pal[1] };
}
export const styleOf = (id: string | null | undefined) => STYLES.find((s) => s.id === id) || null;
export const matOf = (id: string | null | undefined) => (id ? DATA.materials.find((m) => m.id === id) || null : null);

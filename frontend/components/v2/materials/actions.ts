// 자재 고르기 동작 (v10 setAllTier · dropCat · addCat · toggleCmp · selectMat · recWhy). 금액을 만들지 않는다.
import { CAT, CATS, type Material, STYLES, TIERS } from "@/components/v2/data";
import { toast } from "@/components/v2/engine";
import { autoPick, recommend, scopeCats } from "@/components/v2/flow";
import { toneFit } from "@/components/v2/looks";
import { S, type Tier } from "@/components/v2/store";
import { CMP, listReset, M, mok10St, mok10Sync, redraw } from "./state";

export function selectMat(m: Material) {
  S.picks[m.cat] = m.id;
  redraw(true);
}

/** 공정 탭 옮기기. 목공으로 가면 목공 고른 값을 맞춘다 (v10 refreshMat 덧씌움) */
export function goCat(id: string) {
  M.cat = id;
  listReset();
  if (id === "carpentry") {
    mok10St();
    mok10Sync();
  }
  redraw();
}

export function setAllTier(t: Tier) {
  if (t === S.tier) return;
  const prev = { tier: S.tier, tierBy: S.tierBy, picks: { ...S.picks } };
  S.tier = t;
  S.tierBy = "me";
  const n = autoPick();
  redraw(true);
  toast(`자재 ${n}개를 ${TIERS[t]}으로 바꿨어요`, () => {
    S.tier = prev.tier;
    S.tierBy = prev.tierBy;
    S.picks = prev.picks;
    redraw();
  });
}

export function dropCat(id: string) {
  const cur = scopeCats().map((c) => c.id).filter((c) => c !== id);
  if (!cur.length) {
    toast("공정이 하나는 있어야 해요");
    return;
  }
  const prev = { scope: JSON.parse(JSON.stringify(S.scope)) as typeof S.scope, pick: S.picks[id], cat: M.cat };
  S.scope.kind = "part";
  S.scope.cats = cur;
  delete S.picks[id];
  if (M.cat === id) {
    M.cat = cur[0];
    listReset();
  }
  redraw(true);
  toast(`${CAT[id].ko} 공정을 뺐어요`, () => {
    S.scope = prev.scope;
    if (prev.pick) S.picks[id] = prev.pick;
    M.cat = prev.cat;
    redraw();
  });
}

export function addCat(id: string) {
  const cur = new Set(scopeCats().map((c) => c.id));
  cur.add(id);
  if (cur.size === CATS.length) Object.assign(S.scope, { kind: "all", spaces: [], cats: [] });
  else {
    S.scope.kind = "part";
    S.scope.cats = CATS.filter((c) => cur.has(c.id)).map((c) => c.id);
  }
  if (!S.picks[id]) {
    const r = recommend(id)[0];
    if (r) S.picks[id] = r.id;
  }
  M.cat = id;
  listReset();
  if (id === "carpentry") mok10Sync();
  redraw(true);
}

/** 비교 바구니에 넣고 빼기. 3개가 넘으면 false */
export function toggleCmp(m: Material) {
  const a = (CMP[m.cat] = CMP[m.cat] || []);
  const i = a.indexOf(m.id);
  if (i >= 0) a.splice(i, 1);
  else {
    if (a.length >= 3) {
      toast("비교는 3개까지예요");
      return false;
    }
    a.push(m.id);
  }
  redraw();
  return true;
}

/** 추천 이유 (점수가 아니라 글) */
export function recWhy(m: Material) {
  const st = STYLES.find((s) => s.id === S.style);
  return [
    toneFit(m) >= 0.9 ? "고른 사진과 색이 비슷해요" : null,
    st && (m.styles || []).includes(st.id) ? `${st.ko}에 어울려요` : null,
    m.rank && m.rank <= 5 ? `많이 써요 ${m.rank}위` : null,
    (m.tags || []).includes("요즘 인기") ? "요즘 인기" : null,
    m.tier === S.tier ? TIERS[m.tier] : null,
  ]
    .filter(Boolean)
    .slice(0, 2)
    .join(" · ");
}

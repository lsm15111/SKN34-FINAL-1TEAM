// 입구 관문 (v10 v5 ROUTE_* · routeQ · routeHint) + 답 글 표시 도우미 (cleanMarks · NEXT_STEPS · nextStepOf).
// 학습: 고객 질문 v5 dev 4,000문장, 글자 1~3조각 로지스틱 회귀. 자료: public/v2/router.json
// - 범위 밖: 신뢰도 0.6 이상이거나 범위 밖 낱말 + 공사 낱말 없음이면 LLM 없이 안내. 그 밖은 신뢰도 0.6 이상이면 해당 도구를 먼저 쓰라고 알린다

type Model = { classes: string[]; b: number[]; w: Record<string, number[]> };
const router = { data: null as { route: Model; trade: Model } | null };
let loading: Promise<unknown> | null = null;
export function routerReady() {
  if (!loading)
    loading = fetch("/v2/router.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j?.route && j?.trade) router.data = j;
      })
      .catch(() => null);
  return loading;
}
if (typeof window !== "undefined") routerReady();

export const ROUTE_KO: Record<string, string> = { price: "공사비", schedule: "공정 순서 · 기간", vendor: "업체 고르기", out: "상담 범위 밖", knowledge: "시공 · 법규 · 자재 지식" };
function routeFeats(q: string) {
  const s = " " + String(q).toLowerCase().replace(/[^0-9a-z가-힣]+/g, " ").trim() + " ", o = new Set<string>();
  for (let n = 1; n <= 3; n++)
    for (let i = 0; i + n <= s.length; i++) {
      const g = s.slice(i, i + n);
      if (g.trim()) o.add(g);
    }
  return [...o];
}
function routePredict(m: Model, q: string) {
  const f = routeFeats(q), sc = m.b.slice(), a = sc.map(() => 0);
  for (const x of f) {
    const w = m.w[x];
    if (w) for (let i = 0; i < sc.length; i++) a[i] += w[i];
  }
  const n = Math.sqrt(f.length) || 1;
  for (let i = 0; i < sc.length; i++) sc[i] += a[i] / n;
  const mx = Math.max(...sc), ex = sc.map((v) => Math.exp(v - mx)), z = ex.reduce((p, r) => p + r, 0), i = sc.indexOf(mx);
  return { label: m.classes[i], p: ex[i] / z };
}
/* 범위 밖 낱말(dev 범위밖 질문을 보고 만듦)과 공사 낱말. 공사 낱말이 있으면 낱말 목록으로는 막지 않는다 */
const OUT_WORDS = /대출|ltv|dsr|버팀목|청약|가점|취득세|등록세|재산세|종부세|이사 ?(업체|비용|센터|날)|이삿짐|포장 ?이사|보관 ?이사|손 ?없는 ?날|전입 ?신고|전출|냉장고|세탁기|건조기|소파|침대|매트리스|관리비|인터넷|잔금|중개 ?수수료|부동산 ?(매매|중개)|카페|상가|상업 ?공간|사무실/i;
const WORK_WORDS = /인테리어|도배|벽지|목공|몰딩|걸레받이|공사|시공|리모델링|철거|타일|장판|마루|욕실|싱크|수리|누수|곰팡이|원상 ?복구/;

export type Route = { route: string; p: number; sure: boolean; by?: string; trade: string | null };
export function routeQ(q: string): Route {
  const R = router.data;
  // 분류 자료를 아직 못 읽었으면 지식 검색으로 (확신 없음)
  if (!R) return { route: "knowledge", p: 0, sure: false, trade: null };
  const r = routePredict(R.route, q), t = routePredict(R.trade, q);
  const trade = t.p >= 0.7 && t.label !== "other" ? t.label : null;
  if (r.label === "out" && r.p >= 0.6) return { route: "out", p: +r.p.toFixed(2), sure: true, by: "model", trade };
  if (OUT_WORDS.test(q) && !WORK_WORDS.test(q) && !(r.label !== "out" && r.p >= 0.9)) return { route: "out", p: +r.p.toFixed(2), sure: true, by: "words", trade };
  const route = r.label === "out" ? "knowledge" : r.label; // 확신 없는 범위 밖은 지식 검색으로(자료에 없으면 없다고 답함)
  return { route, p: +r.p.toFixed(2), sure: r.p >= 0.6 && r.label !== "out", trade };
}
const ROUTE_HINT: Record<string, string> = {
  price: "질문 종류(입구 관문): 공사비. price_reference 도구를 먼저 쓰고 그 숫자만 말해.",
  schedule: "질문 종류(입구 관문): 공정 순서 · 기간. 기간 · 날짜 숫자는 지어내지 말고, 순서는 자료로 답한 뒤 공정표(show_step 'sched')로 안내해.",
  vendor: "질문 종류(입구 관문): 업체 고르기. 믿집은 조건에 맞는 업체를 골라 보여 주고 실측 요청을 연결만 한다고 안내해. 고르는 기준(사업자 · 하자 보수 · 견적서 항목)은 자료로 답해.",
  knowledge: "질문 종류(입구 관문): 시공 · 법규 · 자재 지식. search_knowledge로 찾고 자료 번호를 붙여 답해.",
};
/** 관문 기록 (v10 V5.routes) */
export const routeLog: (Route & { q: string; gate?: boolean })[] = [];
export const lastRoute = { r: null as Route | null };
export function routeHint(q: string) {
  const r = (lastRoute.r = routeQ(q));
  routeLog.push({ q: String(q).slice(0, 60), ...r });
  if (!r.sure || r.route === "out") return "";
  return ROUTE_HINT[r.route] + (r.trade ? ` 공정은 ${r.trade === "dobae" ? "도배" : "목공"}으로 보여(검색할 때 trade로 써).` : "");
}
export function routeChipText() {
  const r = lastRoute.r;
  if (!r || !r.sure) return null;
  return `질문 종류: ${ROUTE_KO[r.route]}${r.trade ? " · " + (r.trade === "dobae" ? "도배" : "목공") : ""}`;
}

/* 반셀프 안내 표시. [K12] 같은 근거 표시는 글에서 숨기고(근거는 아래 '근거 n개'에 그대로),
   '다음에 할 일:' 줄에 화면 단계 이름이 있으면 그 단계를 여는 버튼을 붙인다 */
export const NEXT_STEPS: [string, string, string][] = [
  ["계산기", "calc", "계산기"], ["체크리스트", "check", "체크리스트"],
  ["공정표", "sched", "공정표"], ["표준견적서", "quote", "견적서"], ["견적서", "quote", "견적서"], ["집 정보", "info", "집 정보"],
  ["범위", "scope", "범위"], ["예산", "budget", "예산"], ["도면", "photo", "사진 · 도면"], ["사진", "photo", "사진 · 도면"], ["자재", "materials", "자재"],
];
export function cleanMarks(t: string) {
  return String(t || "").replace(/\s*\[K\d{1,5}\](?:\s*\[K\d{1,5}\])*/g, "").replace(/[ \t]+\n/g, "\n");
}
export function nextStepOf(t: string) {
  const line = String(t || "").split("\n").reverse().find((l) => l.trim().startsWith("다음에 할 일"));
  if (!line) return null;
  const hit = NEXT_STEPS.find(([ko]) => line.includes(ko));
  return hit ? { step: hit[1], ko: hit[2] } : null;
}

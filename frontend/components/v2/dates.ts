// 날짜 글 도우미 (v10 cal8 · moveDay8 · moveLabel8). 날짜 계산(공정표 · 휴일)은 백엔드가 한다. 여기는 보여 주기만.
const WD = ["일", "월", "화", "수", "목", "금", "토"];
export const toDate = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
export const toStr = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
/** "2026-11-16" → "11.16(월)" */
export const md = (s: string) => {
  const d = toDate(s);
  return `${d.getMonth() + 1}.${d.getDate()}(${WD[d.getDay()]})`;
};
/** "2026-11-16" → "2026년 11월 16일 (월)" */
export const longDay = (s: string) => {
  const d = toDate(s);
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 (${WD[d.getDay()]})`;
};
/** 서울 오늘 "YYYY-MM-DD" */
export const todaySeoul = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
/** 입주 희망: v8부터 날짜(YYYY-MM-DD). 예전 값(YYYY-MM)도 읽음 */
export const moveDay = (m: string) => (m && m.length === 7 ? m + "-01" : m);
export const moveLabel = (m: string) => (!m ? "" : m.length === 7 ? m.replace("-", ".") : md(m));

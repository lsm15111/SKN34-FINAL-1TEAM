// 표시 형식만 바꿔요. 금액 · 날짜 · 기한은 계산 엔진이 만든 값을 받아 모양만 바꾸고 새로 계산하지 않아요(00-prompt 3.6).
// - 금액 표기: copy-guide F1(카드 · 문장은 만 단위 won, 견적서 줄 · 합계 칸은 전체 자리 wonFull)
// - 날짜 · 시각 · 기한 · 범위: ADR copy-01 · copy-guide F2~F5(아래 'v3 날짜 꼴' 묶음). 옛 md · dotDate · stampSeoul은 지금 화면이 쓰고 있어 그대로 둬요.

/** 5168000 → "516만 8,000원", 3000000 → "300만 원" */
export function won(n: number): string {
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  const man = Math.floor(a / 10000);
  const rest = a % 10000;
  if (man === 0) return `${sign}${rest.toLocaleString("ko-KR")}원`;
  if (rest === 0) return `${sign}${man.toLocaleString("ko-KR")}만 원`;
  return `${sign}${man.toLocaleString("ko-KR")}만 ${rest.toLocaleString("ko-KR")}원`;
}

/** 5168000 → "5,168,000원" (견적서 줄) */
export function wonFull(n: number): string {
  return `${n < 0 ? "−" : ""}${Math.abs(n).toLocaleString("ko-KR")}원`;
}

/** 증감 표시: 180000 → "+18만 원" */
export function wonDelta(n: number): string {
  return n > 0 ? `+${won(n)}` : n < 0 ? won(n) : "변동 없음";
}

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
/** "2026-11-16" → "11.16(월)" */
export function md(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const w = new Date(y, m - 1, d).getDay();
  return `${m}.${d}(${WEEK[w]})`;
}
/** "2026-11-16" → "2026년 11월 16일" */
export function ymd(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

/** 받침에 맞춰 을/를을 붙인다: "결도배" → "결도배를" */
export function eulReul(word: string): string {
  const c = word.charCodeAt(word.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return `${word}을(를)`;
  return `${word}${(c - 0xac00) % 28 === 0 ? "를" : "을"}`;
}

/** 받침에 맞춰 로/으로를 붙인다: "결도배" → "결도배로", "마루와벽" → "마루와벽으로" (ㄹ 받침은 "로").
 * 괄호로 끝나면 괄호 안 마지막 한글로 본다: "11.30(일)" → "11.30(일)로" */
export function euro(word: string): string {
  const last = /([가-힣])[)\]\s]*$/.exec(word);
  if (!last) return `${word}(으)로`;
  const j = (last[1].charCodeAt(0) - 0xac00) % 28;
  return `${word}${j === 0 || j === 8 ? "로" : "으로"}`;
}

export function sqm(n: number): string {
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}㎡`;
}

const SEOUL_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
/** API가 준 시각(UTC) → 서울 날짜 "2026-10-29" */
export function dateSeoul(isoTime: string): string {
  return SEOUL_DAY.format(new Date(isoTime));
}
/** 오늘 서울 날짜 "2026-10-29". 달력에서 지난 날을 막는 데만 쓴다. */
export function todaySeoul(): string {
  return SEOUL_DAY.format(new Date());
}

/** 공정표 칸: 일하는 날 목록의 첫날부터 끝날까지 모든 날짜. 일정을 새로 만들지 않고 칸만 늘어놓는다. */
export function calendarSpan(days: string[]): string[] {
  if (!days.length) return [];
  const sorted = [...days].sort();
  const last = sorted[sorted.length - 1];
  const [y, m, d] = sorted[0].split("-").map(Number);
  const out: string[] = [];
  for (const t = new Date(Date.UTC(y, m - 1, d)); out.length < 400; t.setUTCDate(t.getUTCDate() + 1)) {
    const iso = t.toISOString().slice(0, 10);
    out.push(iso);
    if (iso >= last) break;
  }
  return out;
}

/** "2026-11-02" · "2026-11-02T…" → "2026.11.02" (서류의 날짜) */
export function dotDate(iso: string): string {
  return iso.slice(0, 10).replaceAll("-", ".");
}

/** 1189011 → "1,189,011" (단위를 표 머리에 둔 칸) */
export function numText(n: number): string {
  return n.toLocaleString("ko-KR");
}

/** API가 준 소수 문자열의 끝 0만 뺀다: "7.5" → "7.5", "32.0" → "32", "198.40" → "198.4" */
export function decText(s: string): string {
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

/** 파일 크기: 3250000 → "3.1MB", 820000 → "801KB" */
export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  return `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

/** "2026-11-16" → { m: 11, d: 16, w: "월" } (공정표 날짜 머리 칸) */
export function dayParts(iso: string): { m: number; d: number; w: string } {
  const [y, m, d] = iso.split("-").map(Number);
  return { m, d, w: WEEK[new Date(y, m - 1, d).getDay()] };
}

const SEOUL_STAMP = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** 받은 시각 → 서울 "11.02(월) 14:20" (임시 저장 안내) */
export function stampSeoul(t: Date): string {
  const p = Object.fromEntries(SEOUL_STAMP.formatToParts(t).map((x) => [x.type, x.value]));
  return `${md(`${p.year}-${p.month}-${p.day}`)} ${p.hour}:${p.minute}`;
}

// ───── v3 날짜 꼴 (ADR copy-01 · copy-guide F2~F5) ─────
// 날짜(date)는 "2026-12-15", 시각(timestamptz)은 API가 준 ISO 문자열 그대로 받아요. 서울 기준으로만 보여요.
// today · now는 화면이 시계를 읽지 않게 서버가 준 값(또는 todaySeoul())을 넘겨요. 안 주면 연도를 붙이지 않아요.

const WEEK_LONG = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
const ymdParts = (iso: string) => iso.slice(0, 10).split("-").map(Number) as [number, number, number];
const weekOf = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, d)).getUTCDay();
const dayNo = (iso: string) => { const [y, m, d] = ymdParts(iso); return Date.UTC(y, m - 1, d) / 86400000; };
const isTime = (v: string) => v.length > 10;
/** 날짜든 시각이든 서울 날짜 "YYYY-MM-DD"로 */
const seoulDay = (v: string) => (isTime(v) ? dateSeoul(v) : v.slice(0, 10));

/** 짧은 꼴(기본): "2026-12-15" → "12.15(화)", 올해가 아니면 "2027.1.4(월)". 0을 붙이지 않아요 */
export function dateShort(iso: string, today?: string): string {
  const [y, m, d] = ymdParts(seoulDay(iso));
  const w = WEEK[weekOf(y, m, d)];
  return today && Number(today.slice(0, 4)) !== y ? `${y}.${m}.${d}(${w})` : `${m}.${d}(${w})`;
}
/** 긴 꼴(화면 주인공 날짜 · 채팅 날 바뀜 줄): "12월 15일(화)", 올해가 아니면 "2027년 1월 4일(월)" */
export function dateLong(iso: string, today?: string): string {
  const [y, m, d] = ymdParts(seoulDay(iso));
  const w = WEEK[weekOf(y, m, d)];
  return today && Number(today.slice(0, 4)) !== y ? `${y}년 ${m}월 ${d}일(${w})` : `${m}월 ${d}일(${w})`;
}
/** 읽는 이름(낭독기): "12월 15일 화요일" — 짧은 꼴을 보일 때 <time aria-label>로 줘요(copy-guide A10) */
export function dateSpoken(iso: string): string {
  const [y, m, d] = ymdParts(seoulDay(iso));
  return `${m}월 ${d}일 ${WEEK_LONG[weekOf(y, m, d)]}`;
}

const SEOUL_TIME = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** 시각: "09:05"(24시간 · 두 자리) */
export function timeSeoul(isoTime: string): string {
  return SEOUL_TIME.format(new Date(isoTime));
}
/** 알림 · 기록 목록 시각: "11.21 10:12"(요일 없이) */
export function listStamp(isoTime: string): string {
  const [, m, d] = ymdParts(dateSeoul(isoTime));
  return `${m}.${d} ${timeSeoul(isoTime)}`;
}

/** 반나절 이름. 실측은 반나절만 보이고 시각은 채팅으로 정해요 */
export const HALF_LABEL = { am: "오전", pm: "오후" } as const;
export type Half = keyof typeof HALF_LABEL;
/** "12.15(화) 오전" · 긴 꼴은 "12월 15일(화) 오전" */
export function halfDayText(iso: string, half: Half, long = false): string {
  return `${long ? dateLong(iso) : dateShort(iso)} ${HALF_LABEL[half]}`;
}

const RELATIVE = ["오늘", "내일", "모레"];
/** 기한: "11.25(수) 09:05까지". relative면 오늘 · 내일 · 모레를 말로(업체 폰 작업함 · 일정 탭), 사흘 뒤부터 짧은 꼴 */
export function dueText(dueTime: string, opts: { now?: string; relative?: boolean; today?: string } = {}): string {
  const day = dateSeoul(dueTime);
  const t = timeSeoul(dueTime);
  if (opts.relative && opts.now) {
    const gap = dayNo(day) - dayNo(dateSeoul(opts.now));
    if (gap >= 0 && gap < RELATIVE.length) return `${RELATIVE[gap]} ${t}까지`;
  }
  return `${dateShort(day, opts.today)} ${t}까지`;
}
/** 가까운 날 말: today(서버가 준 'YYYY-MM-DD') 기준 '오늘' · '내일' · '모레', 그 밖은 null(공정표 · 업체 일정 날짜 묶음 머리) */
export function dayWord(day: string, today: string): string | null {
  const gap = dayNo(day) - dayNo(today);
  return gap >= 0 && gap < RELATIVE.length ? RELATIVE[gap] : null;
}
/** 기한 상태: 지남(over) · 가까움(near: 서울 날짜로 오늘 · 내일) · 보통. now는 서버 시각을 넘겨요 */
export function dueState(dueTime: string, now: string): "over" | "near" | "normal" {
  if (new Date(now).getTime() >= new Date(dueTime).getTime()) return "over";
  return dayNo(dateSeoul(dueTime)) - dayNo(dateSeoul(now)) <= 1 ? "near" : "normal";
}

/** 범위: "12.7~12.21" · weekday면 "12.7(월)~12.21(월)" · long이면 같은 달 "12월 13일~18일", 다른 달 "12월 28일~1월 4일" */
export function rangeText(from: string, to: string, opts: { weekday?: boolean; long?: boolean } = {}): string {
  const [, m1, d1] = ymdParts(from);
  const [, m2, d2] = ymdParts(to);
  if (opts.long) return m1 === m2 ? `${m1}월 ${d1}일~${d2}일` : `${m1}월 ${d1}일~${m2}월 ${d2}일`;
  if (opts.weekday) return `${dateShort(from)}~${dateShort(to)}`;
  return `${m1}.${d1}~${m2}.${d2}`;
}

/** 면적(F7): 기준을 앞에 "공급 69.4㎡". 값은 계산 엔진이 준 ㎡(numeric, 소수 한 자리)를 그대로 써요 */
export function areaText(m2: number | string, basis?: "supply" | "exclusive" | string | null): string {
  const n = typeof m2 === "string" ? decText(m2) : m2.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  const b = basis === "exclusive" ? "전용 " : basis === "supply" ? "공급 " : "";
  return `${b}${n}㎡`;
}

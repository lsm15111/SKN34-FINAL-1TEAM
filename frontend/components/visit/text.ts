// 실측 일정 화면 말(copy-guide 1.4 · 1.9 · F2~F5 · CF-01~CF-07 · CF-60). 날짜 · 기한은 API 값을 모양만 바꿔요(lib/format).
import { areaText, dateLong, dateSeoul, dateShort, dueText, halfDayText, rangeText, timeSeoul, type Half } from "@/lib/format";
import { visitState, type StateTone } from "@/lib/labels";
import type { BoardRow, VisitProject } from "@/lib/api/visit";

/** 보낸 내용 한 줄: '노원구 상계동 · 아파트 · 전체 · 공급 69.4㎡ · 빈 집'(CF-62) */
export function homeLine(p: VisitProject): string {
  const place = [p.sgg, p.emd].filter(Boolean).join(" ");
  const scope = p.scope === "partial" ? "부분" : p.scope === "full" ? "전체" : null;
  return [place, "아파트", scope, p.areaM2 ? areaText(p.areaM2, p.areaBasis) : null, p.occupied ? "사는 중" : "빈 집"].filter(Boolean).join(" · ");
}

/** 날짜 긴 꼴에서 요일 괄호를 뺀 '1월 4일'(문장 속 괄호 안에 넣을 때) */
export const dayOnly = (iso: string) => dateLong(iso).replace(/\(.\)$/, "");

/** 같은 달이면 '1월 5일(화)~9일(토)', 다른 달이면 '12월 28일(월)~1월 4일(월)' */
export function rangeLong(from: string, to: string): string {
  const a = dateLong(from);
  const b = dateLong(to);
  return from.slice(0, 7) === to.slice(0, 7) ? `${a}~${b.replace(/^\d+월 /, "")}` : `${a}~${b}`;
}

/** 받침에 맞춘 이/가: "마루와벽" → "마루와벽이", "결도배" → "결도배가" */
export function iGa(word: string): string {
  const c = word.charCodeAt(word.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return `${word}이(가)`;
  return `${word}${(c - 0xac00) % 28 === 0 ? "가" : "이"}`;
}
/** 받침에 맞춘 은/는 */
export function eunNeun(word: string): string {
  const c = word.charCodeAt(word.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return `${word}은(는)`;
  return `${word}${(c - 0xac00) % 28 === 0 ? "는" : "은"}`;
}
/** 받침에 맞춘 과/와 */
export function gwaWa(word: string): string {
  const c = word.charCodeAt(word.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return `${word}와(과)`;
  return `${word}${(c - 0xac00) % 28 === 0 ? "와" : "과"}`;
}

/** 실측 취소 이유(C30). late_quote(견적서가 늦어서 닫음)는 늦은 견적서 알림에서만 써요 */
export const CANCEL_REASONS = [
  { key: "changed", label: "일정이 바뀌었어요" },
  { key: "other_vendor", label: "다른 업체로 할래요" },
  { key: "other", label: "그 밖" },
] as const;
export type CancelCode = (typeof CANCEL_REASONS)[number]["key"] | "late_quote";
export const cancelLabel = (k: string | null | undefined) => (k === "late_quote" ? "견적서가 늦어서 닫았어요" : CANCEL_REASONS.find((r) => r.key === k)?.label ?? "그 밖");

/** 업체가 다른 날을 제안한 이유(V07) */
export const PROPOSAL_REASON: Record<string, string> = { other_site: "다른 현장이 있어요", no_crew: "자재 · 사람이 안 돼요", other: "그 밖" };

/** 반나절 '12.15(화) 오전'(짧은 꼴) · long이면 '12월 15일(화) 오전' */
export const slotText = (s: { day: string; half: Half }, long = false) => halfDayText(s.day, s.half, long);

/** 업체 가능 기간 한 줄: '가능 12.13~12.18 · 16일 빼고'(CF-60) */
export function windowText(w: { start: string; end: string; excluded: string[] }): string {
  const ex = w.excluded.map((d) => `${Number(d.slice(8, 10))}일`).join(" · ");
  return `가능 ${rangeText(w.start, w.end)}${ex ? ` · ${ex} 빼고` : ""}`;
}

/** 기한 줄 꼴(표 칸): '11.25(수) 09:05'(까지 없이) */
export const dueCell = (t: string) => `${dateShort(dateSeoul(t))} ${timeSeoul(t)}`;

/** 상태 칩 말 · 모양(N4 C). 실측 시각이 지났는데 아직 확정 상태면 '실측 시각 지남'(copy-guide 1.9) */
export function boardState(r: Pick<BoardRow, "status" | "can">): { label: string; tone: StateTone } {
  if (r.status === "booked" && r.can.visited) return { label: "실측 시각 지남", tone: "todo" };
  return visitState(r.status, "customer");
}

/** 표 '다음 할 일' 칸(D03 · CF-07). 누가 할 일인지 밝혀요(W3) */
export function nextText(r: BoardRow): string {
  const v = r.vendor_name;
  switch (r.status) {
    case "requested": return `${iGa(v)} 기간을 답해요`;
    case "offered": return "날짜 고르기";
    case "picked": return `${iGa(v)} 수락해요`;
    case "proposed": return "제안한 날 고르기";
    case "booked": return r.can.visited ? "실측 받았는지 알려 주기" : r.change?.status === "open" ? `${iGa(v)} 일정 바꾸기에 답해요` : "실측 날 기다리기";
    case "visited": return `${iGa(v)} 견적서를 보내요`;
    case "quoted": return "견적서 비교하고 확정하기";
    case "chosen": return `${iGa(v)} 공사 날짜를 올려요`;
    case "expired": return r.can.again ? "한 번 더 요청 · 다른 업체 담기" : "다른 업체 담기";
    case "declined": return "다른 업체 담기";
    default: return "—";
  }
}

/** 표 '날짜' 칸: 기간 · 고른 날 · 제안한 날 · 확정 날 */
export function dayCell(r: BoardRow): string | null {
  if (r.status === "offered" && r.window) return rangeText(r.window.start, r.window.end);
  if (r.status === "proposed" && r.proposal) return r.proposal.slots.map((x) => slotText(x)).join(" · ");
  if (r.booked && ["picked", "booked", "visited", "quoted", "chosen"].includes(r.status)) return slotText(r.booked);
  return null;
}

/** 요청 머리 한 줄: '11월 17일(화) 요청' + '희망 12.7~12.21 · 2곳' */
export function headText(head: { sent_at: string; wish_start: string | null; wish_end: string | null }, count?: number) {
  const wish = head.wish_start && head.wish_end ? `희망 ${rangeText(head.wish_start, head.wish_end)}` : "희망 기간 없음";
  return { title: `${dateLong(dateSeoul(head.sent_at))} 요청`, sub: count ? `${wish} · ${count}곳` : wish, wishLong: head.wish_start && head.wish_end ? `희망 ${rangeText(head.wish_start, head.wish_end, { long: true })}` : null };
}

/** 날짜 고르기 화면 제목(폰 머리 · 웹 제목이 같아요): '마루와벽 날짜 고르기' · '결도배가 제안한 날' · '실측 일정' */
export function pickTitle(p: { status: string; vendor_name: string; proposal: unknown }): string {
  if (p.status === "offered") return `${p.vendor_name} 날짜 고르기`;
  if (p.status === "proposed" && p.proposal) return `${iGa(p.vendor_name)} 제안한 날`;
  return "실측 일정";
}

/** 기한 문장: '11.19(목) 21:40까지 답해요' 같은 짧은 꼴(CF-60) */
export const dueSentence = (t: string, tail: string) => `${dueText(t)} ${tail}`;

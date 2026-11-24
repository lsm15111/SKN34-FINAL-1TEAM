// 작업함 줄(InboxRowOut)을 화면 글로 바꿔요. 금액 · 날짜 · 기한은 API 값의 모양만 바꾸고 새로 계산하지 않아요.
import type { InboxRowV3 } from "@/lib/api/vendor";
import { dateShort, dueText, rangeText, timeSeoul, won } from "@/lib/format";
import { visitState, type StateTone } from "@/lib/labels";

export const rowTone = (r: InboxRowV3): StateTone => (r.state?.icon as StateTone | undefined) ?? visitState(r.status, "vendor").tone;
export const rowLabel = (r: InboxRowV3) => r.state?.label ?? visitState(r.status, "vendor", { close_reason: r.close_reason }).label;
export const rowTitle = (r: InboxRowV3) => r.area_label ?? `${r.region} ${r.area_name}`;
export const isJob = (r: InboxRowV3) => !!r.deal_id;
/** 고객이 고른 반나절을 업체 수락까지 잡아 둔 줄(D10 A) */
export const isHold = (r: InboxRowV3) => r.status === "picked";

/** 줄이 가는 곳: 공사는 공사 한 건, 나머지는 실측 요청 */
export function rowHref(r: InboxRowV3): string {
  if (r.deal_id) return `/vendor/jobs/${encodeURIComponent(r.deal_id)}`;
  if (r.status === "visited") return `/vendor/requests/${encodeURIComponent(r.id)}/quote`;
  return `/vendor/requests/${encodeURIComponent(r.id)}`;
}

/** 공사 날짜 글: '1.4(월) · 1.5(화)' 또는 시작~끝 */
export function jobDays(r: InboxRowV3): string | null {
  if (r.start_date && r.end_date) return r.start_date === r.end_date ? dateShort(r.start_date) : rangeText(r.start_date, r.end_date, { weekday: true });
  return null;
}

/** 폰 카드 아래 한 줄(V03): 집 · 희망 · 공사 시작 희망(L04) · 가견적 · 예산 */
export function rowSub(r: InboxRowV3): string {
  if (isJob(r)) return [jobDays(r), r.deal_total != null ? `확정 ${won(r.deal_total)}` : null].filter(Boolean).join(" · ") || (r.home ?? "");
  if (r.status === "expired" && r.next?.due_at) return [r.home, `${dateShort(r.next.due_at)} ${timeSeoul(r.next.due_at)}까지 답하지 못했어요`].filter(Boolean).join(" · ");
  return [
    r.home,
    r.wish_start && r.wish_end ? `희망 ${rangeText(r.wish_start, r.wish_end)}` : null,
    r.work_wish_on ? `공사 시작 희망 ${dateShort(r.work_wish_on)}` : null,
    r.estimate_total != null ? `가견적 ${won(r.estimate_total)}` : null,
    r.budget_won != null ? `예산 ${won(r.budget_won)}` : null,
  ].filter(Boolean).join(" · ");
}
/** 웹 표 '집' 칸 아래 줄(D04): 집 · 희망 */
export function rowSubShort(r: InboxRowV3): string {
  if (isJob(r)) return [r.home, jobDays(r)].filter(Boolean).join(" · ");
  return [r.home, r.wish_start && r.wish_end ? `희망 ${rangeText(r.wish_start, r.wish_end)}` : null].filter(Boolean).join(" · ");
}

/** '다음 할 일 …' 줄. 폰은 기한을 '내일 21:40까지'처럼 말로(V03), 지난 기한은 붙이지 않아요 */
export function rowNext(r: InboxRowV3, now: string): string | null {
  if (!r.next) return null;
  const due = r.next.due_at && !r.next.overdue ? ` · ${dueText(r.next.due_at, { now, relative: true })}` : "";
  return `${r.next.label}${due}`;
}
/** 웹 표 '기한' 칸(D04): '11.19(목) 21:40' */
export function rowDue(r: InboxRowV3): string {
  const t = r.next?.due_at;
  return t ? `${dateShort(t)} ${timeSeoul(t)}` : "—";
}

/** 카드 · 옆 자세히의 다음 단추 하나 */
export function rowAction(r: InboxRowV3): { label: string; href: string; variant: "primary" | "weak" | "secondary" } | null {
  if (r.deal_id) return r.dates_state === "waiting" || r.dates_state === "requested" ? { label: "공사 날짜 올리기", href: rowHref(r), variant: "primary" } : { label: "공사 한 건 보기", href: rowHref(r), variant: "secondary" };
  switch (r.status) {
    case "requested": return { label: "기간 답하기", href: rowHref(r), variant: "primary" };
    case "picked": return { label: "답하기", href: rowHref(r), variant: "weak" };
    case "visited": return { label: "견적서 올리기", href: rowHref(r), variant: "primary" };
    case "booked": return { label: "요청 보기", href: rowHref(r), variant: "secondary" };
    default: return null;
  }
}

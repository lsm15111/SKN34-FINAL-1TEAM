// 한 공사 기록(C63 · I2) 줄 말. visit_events · deal_events 코드를 짧은 명사꼴로(W13 · CF-51). 금액 · 날짜는 API 값 모양만 바꿔요.
import type { ApiLogItem } from "@/lib/api/schedule";
import { dateSeoul, dateShort, halfDayText, HALF_LABEL, listStamp, rangeText, wonDelta, won } from "@/lib/format";

export type LogLine = { key: string; at: string; time: string; who: string; text: string };

const md = (iso: string) => { const [, m, d] = dateSeoul(iso.length > 10 ? iso : `${iso}T12:00:00+09:00`).split("-").map(Number); return `${m}.${d}`; };
const slot = (x: ApiLogItem) => (x.day ? (x.half ? halfDayText(x.day, x.half) : dateShort(x.day)) : "");
const tail = (s: string) => (s ? ` · ${s}` : "");

function textOf(x: ApiLogItem, all: ApiLogItem[]): string {
  const v = x.vendor_name ?? "업체";
  switch (x.code) {
    case "asked": return `실측 요청 보냄${tail(v)}`;
    case "re_asked": return `${v}에 한 번 더 요청`;
    case "answered": return `기간 답함${x.day && x.day_to ? tail(rangeText(x.day, x.day_to)) : ""}`;
    case "declined": return "못 받아요 · 요청 닫힘";
    case "picked": return slot(x) ? `${v}에 ${slot(x)} 보냄` : `${v}에 날짜 보냄`;
    case "booked":
    case "proposal_picked": return slot(x) ? `${v} ${slot(x)} 확정` : `${v} 실측 확정`;
    case "hold_released": return `${v} 잡아 둔 날짜 풀림`;
    case "proposed": return `다른 날 제안${x.day ? tail(`${md(x.day)}${x.half ? ` ${HALF_LABEL[x.half]}` : ""}`) : ""}${x.day_to ? tail(md(x.day_to)) : ""}`;
    case "repick": return `${v} 업체 기간에서 다시 고름`;
    case "change_requested": return `${v} 일정 바꾸기 요청${tail(slot(x))}`;
    case "change_accepted": return `${v} 일정 바뀜${tail(slot(x))}`;
    case "change_countered": return `${v} 일정 바꾸기에 다른 날 제안`;
    case "change_expired": return `${v} 일정 바꾸기 답 없음 · 원래 일정 그대로`;
    case "cancelled": return `${v} 실측 취소`;
    case "visited": return `${v} 실측 받음`;
    case "no_show": return `${v} 업체가 안 옴`;
    case "quote_sent": return `실측 견적서 보냄${x.amount != null ? tail(won(x.amount)) : ""}`;
    case "expired": return `${v} 답 없음 · 기한 48시간`;
    case "closed": return `${v} 견적서 닫힘`;
    case "requote": return `${v}에 견적서 다시 요청`;
    case "reselected": return `${v} 확정 풀고 다시 고르기`;
    case "chosen":
    case "confirmed": {
      const others = [...new Set(all.filter((y) => y.code === "quote_sent" && y.vendor_name && y.vendor_name !== x.vendor_name).map((y) => y.vendor_name as string))];
      return others.length ? `${v} 확정 · ${others.join(" · ")} 견적서 닫힘` : `${v} 확정`;
    }
    case "dates_sent": return `공사 날짜 올림${x.day ? tail(x.day_to && x.day_to !== x.day ? rangeText(x.day, x.day_to, { weekday: true }) : dateShort(x.day)) : ""}`;
    case "date_requested": return `${v}에 다른 날짜 요청`;
    case "dates_accepted": return `${v} 공사 날짜 수락`;
    case "extra_sent": return `추가 금액 올림${x.amount != null ? tail(wonDelta(x.amount)) : ""}`;
    case "extra_approved": return `추가 금액 승인${x.amount != null ? tail(wonDelta(x.amount)) : ""}`;
    case "extra_rejected": return "추가 금액 거절";
    case "extra_asked": return "추가 금액 채팅으로 물음";
    case "extra_answered": return "추가 금액 답함";
    case "work_done":
    case "done_posted": return "공사 끝 알림";
    case "done":
    case "checked": return `${v} 공사 끝 확인`;
    case "auto_done": return "공사 끝 · 확인 기한이 지나 자동으로 끝남";
    case "fixing": return `${v}에 고칠 곳 알림`;
    case "review": return `${v} 리뷰 올림`;
    default: return "기록";
  }
}

const WHO = (x: ApiLogItem) => (x.actor === "customer" ? "고객" : x.actor === "mijip" ? "믿집" : x.vendor_name ?? "업체");

/** 시간 순 줄. 같은 시각 · 같은 사람의 '실측 요청 보냄'은 한 줄로 묶어요(9판 C63 '실측 요청 보냄 · 마루와벽 · 결도배') */
export function logLines(items: ApiLogItem[]): LogLine[] {
  const sorted = [...items].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const out: LogLine[] = [];
  sorted.forEach((x, i) => {
    const prev = out[out.length - 1];
    if (x.code === "asked" && prev && prev.key.startsWith("asked:") && prev.at === x.at) {
      prev.text = `${prev.text} · ${x.vendor_name ?? "업체"}`;
      return;
    }
    out.push({ key: `${x.code}:${x.at}:${i}`, at: x.at, time: listStamp(x.at), who: WHO(x), text: textOf(x, sorted) });
  });
  return out;
}

// 업체 공사 한 건의 지금 모습 · 할 수 있는 일(공사 한 건 화면 · ?step= 단계가 같이 써요). 서버 status · dates_state를 나누기만 해요.
// 서버: 추가 금액(EXTRA_OPEN) · 공사 끝 알리기(FINISHABLE)는 공사 중(scheduled) · 남은 일(fixing), 날짜 바꾸기(CHANGEABLE)는 끝 알리기 전.
import type { JobV3 } from "@/lib/api/vendor";

type Job = Pick<JobV3, "status" | "dates_state" | "done_posted_at" | "work_done_on" | "work_days" | "start_date">;
export type JobTone = "now" | "wait" | "ok" | "mute";

export function jobState(j: Job, today: string): { tone: JobTone; label: string } {
  if (j.status === "done") return { tone: "mute", label: "공사 끝" };
  // 고객이 업체를 다시 골라 닫힌 공사(dates_state closed): 옛 알림 링크로 열어도 할 일로 보이지 않게
  if (j.status === "reselected" || j.dates_state === "closed") return { tone: "mute", label: "다시 고르기로 닫힘" };
  // 고객이 '남은 일이 있어요'로 답했어요. 끝을 알린 때(done_posted_at)는 그대로 남아도 업체 차례예요
  if (j.status === "fixing") return { tone: "now", label: "남은 일" };
  if (j.done_posted_at || j.work_done_on) return { tone: "wait", label: "고객 확인 기다림" };
  if (j.dates_state === "proposed" || j.dates_state === "change_proposed") return { tone: "wait", label: "날짜 수락 기다림" };
  if (j.dates_state === "scheduled") return j.work_days.length && today < j.work_days[0] ? { tone: "ok", label: "공사 전" } : { tone: "ok", label: "공사 중" };
  return { tone: "now", label: "공사 날짜 올리기" };
}

/** 추가 금액 올리기 · 공사 끝 알리기를 할 수 있어요: 날짜를 수락한 공사 중(끝 알리기 전) · 남은 일 */
export function jobWorking(j: Job): boolean {
  if (j.status === "fixing") return true;
  return j.status === "scheduled" && j.dates_state === "scheduled" && !j.done_posted_at && !j.work_done_on;
}

/** 수락한 날짜를 바꾸자고 보낼 수 있어요: 공사 첫날 전까지. 서버는 내일부터의 날만 받아서, 공사가 시작되면
 *  지난 공사 날을 뺄 수 없는 날짜 폼이 보내지지 않아요 */
export function jobCanChange(j: Job, today: string): boolean {
  if (j.status !== "scheduled" || j.done_posted_at || j.work_done_on || !j.start_date) return false;
  return (j.dates_state === "scheduled" || j.dates_state === "change_proposed") && today < j.start_date;
}

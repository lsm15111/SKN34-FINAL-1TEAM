// 업체 공사 한 건 기록(V23) 줄 말: 서버 기록 코드(backend schedule/history.py)를 모두 업체가 읽는 말로 바꿔요.
// '기록이 남았어요'는 모르는 코드일 때만이에요(영어를 보이지 않게).
import { expect, test } from "@playwright/test";
import { logText } from "@/components/pro/text";

// 서버가 업체 기록에 보내는 코드: 실측 요청 이력(visit.models.EVENT_CODES · history.VISIT_CODE) · 견적서 ·
// 업체 확정 이력(schedule.models.DEAL_EVENT_CODES · history.DEAL_CODE) · 공사 날짜 · 추가 금액(extra_<답>)
const CODES = [
  "asked", "re_asked", "answered", "declined", "picked", "booked", "hold_released", "proposed", "proposal_picked",
  "repick", "change_requested", "change_accepted", "change_countered", "change_expired", "change_withdrawn",
  "cancelled", "visited", "no_show", "expired", "closed", "requote", "chosen",
  "quote_sent", "quote_resent",
  "confirmed", "dates_sent", "dates_accepted", "dates_changed", "date_requested", "extra_sent", "extra_revised",
  "extra_answered", "extra_approved", "extra_rejected", "extra_asked", "done_posted", "fixing", "checked", "auto_done",
  "reselected",
];

test("서버 기록 코드는 모두 업체가 읽는 말이에요", () => {
  const unknown = CODES.filter((c) => logText(c) === "기록이 남았어요");
  expect(unknown).toEqual([]);
  for (const c of CODES) expect(logText(c)).toMatch(/[가-힣]/);
});

test("모르는 코드는 영어 대신 '기록이 남았어요'", () => {
  expect(logText("something_new")).toBe("기록이 남았어요");
});

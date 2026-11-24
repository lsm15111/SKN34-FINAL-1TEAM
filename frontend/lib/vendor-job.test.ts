// 업체 공사 한 건의 상태 · 할 수 있는 일(components/pro/jobs/state). 값은 서버 JobOut 그대로예요.
import { expect, test } from "@playwright/test";
import { jobCanChange, jobState, jobWorking } from "@/components/pro/jobs/state";

type J = Parameters<typeof jobState>[0];
const job = (x: Partial<J> = {}): J => ({
  status: "scheduled", dates_state: "scheduled", done_posted_at: null, work_done_on: null,
  work_days: ["2027-01-04", "2027-01-05"], start_date: "2027-01-04", ...x,
});

// 점검 R7 #1: 업체가 끝을 알리고 고객이 '남은 일이 있어요'로 답한 공사. 서버는 status만 fixing으로 바꾸고
// 끝 알린 때 · 끝낸 날은 그대로 둬요(schedule.service check_work)
const fixing = job({ status: "fixing", done_posted_at: "2027-01-05T09:00:00Z", work_done_on: "2027-01-05" });

test("남은 일(fixing) 공사는 업체 차례라 추가 금액 · 다시 끝 알리기를 열어요", () => {
  expect(jobState(fixing, "2027-01-06")).toEqual({ tone: "now", label: "남은 일" });
  expect(jobWorking(fixing)).toBe(true);
  expect(jobCanChange(fixing, "2027-01-06")).toBe(false);
});

test("끝을 알리고 고객 확인을 기다리는 공사(checking)는 그대로 막아요", () => {
  const checking = job({ status: "checking", done_posted_at: "2027-01-05T09:00:00Z", work_done_on: "2027-01-05" });
  expect(jobState(checking, "2027-01-06")).toEqual({ tone: "wait", label: "고객 확인 기다림" });
  expect(jobWorking(checking)).toBe(false);
});

// 점검 R7 #17
test("고객이 다시 고른 공사(reselected · dates_state closed)는 닫힌 공사로 보여요", () => {
  const closed = job({ status: "reselected", dates_state: "closed", work_days: [], start_date: null });
  expect(jobState(closed, "2026-12-20")).toEqual({ tone: "mute", label: "다시 고르기로 닫힘" });
  expect(jobWorking(closed)).toBe(false);
  expect(jobCanChange(closed, "2026-12-20")).toBe(false);
});

// 점검 R7 #13
test("수락한 날짜 바꾸기는 공사 첫날 전까지만 열어요(서버는 내일부터의 날만 받아요)", () => {
  expect(jobCanChange(job(), "2027-01-03")).toBe(true);
  expect(jobCanChange(job({ dates_state: "change_proposed" }), "2027-01-03")).toBe(true);
  expect(jobCanChange(job(), "2027-01-04")).toBe(false);
  expect(jobCanChange(job(), "2027-01-05")).toBe(false);
  expect(jobState(job(), "2027-01-04").label).toBe("공사 중");
});

test("공사 중에는 추가 금액 · 끝 알리기를 열고, 날짜를 내기 전 · 수락 기다림에는 닫아요", () => {
  expect(jobWorking(job())).toBe(true);
  expect(jobState(job(), "2027-01-03")).toEqual({ tone: "ok", label: "공사 전" });
  const waiting = job({ status: "confirmed", dates_state: "waiting", work_days: [], start_date: null });
  expect(jobWorking(waiting)).toBe(false);
  expect(jobState(waiting, "2026-12-20")).toEqual({ tone: "now", label: "공사 날짜 올리기" });
  expect(jobWorking(job({ status: "confirmed", dates_state: "proposed", work_days: [], start_date: null }))).toBe(false);
});

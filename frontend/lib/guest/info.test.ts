// 기본 정보 답 → API 몸통(lib/guest/info toHomeInfo): 방 개수 · 공사 시작 희망일 · 직접 할 일(반셀프 칩)
import { expect, test } from "@playwright/test";
import { diyFromPicks, diyOfKeys, diyPicks, diyText, EMPTY_DRAFT, roomsOf, ROOM_RULE_EMPTY, summaryRows, toEditBody, toHomeInfo, type InfoDraft } from "./info";

const DRAFT: InfoDraft = {
  ...EMPTY_DRAFT, sido: "seoul", sgg: "노원구", area: "105.8", occupied: false, grade: "basic", demolition: "none",
  rooms: 3, when: "next_month", start: "2026-12-15",
};

test("직접 할 일은 고른 때만 보내요(안 물었으면 빼고, 없어요는 빈 목록)", () => {
  expect("diy" in toHomeInfo(DRAFT)).toBe(false);
  expect("diy" in toHomeInfo({ ...DRAFT, diy: null })).toBe(false);
  expect(toHomeInfo({ ...DRAFT, diy: [] }).diy).toEqual([]);
  expect(toHomeInfo({ ...DRAFT, diy: ["paint", "clean"] }).diy).toEqual(["paint", "clean"]);
});

test("방 개수 · 공사 시작 희망일은 그대로 보내요(고른 시기 칩은 보내지 않아요)", () => {
  const body = toHomeInfo(DRAFT);
  expect([body.rooms, body.start_date, body.demolition]).toEqual([3, "2026-12-15", "none"]);
  expect("when" in body).toBe(false);
  expect(toHomeInfo({ ...DRAFT, when: "unknown", start: null }).start_date).toBeNull();
});

test("고치기는 받아 둔 동을 지켜요(없으면 안 보내고, 손님 계산 · 공사 만들기 몸통에는 넣지 않아요)", () => {
  expect(toEditBody({ ...DRAFT, emd: "상계동" }).emd).toBe("상계동");
  expect("emd" in toEditBody(DRAFT)).toBe(false);
  expect("emd" in toHomeInfo({ ...DRAFT, emd: "상계동" })).toBe(false);
});

test("방 개수를 안 골랐으면 면적 기본값(표가 없으면 fallback)이 보이는 값이에요", () => {
  expect(roomsOf({ ...DRAFT, rooms: null }, ROOM_RULE_EMPTY)).toBe(ROOM_RULE_EMPTY.fallback);
  expect(roomsOf(DRAFT, ROOM_RULE_EMPTY)).toBe(3);
});

test("고른 직접 할 일 글은 칩 순서로 이어요", () => {
  expect(diyText(["clean", "paint"])).toBe("페인트(문틀 · 몰딩), 입주 청소");
  expect(diyText([])).toBe("없어요");
});

test("저장된 직접 할 일은 모은 조건 diy.* 줄에서 읽어요(안 물음 null · 없어요 빈 목록 · 칩 순서)", () => {
  expect(diyOfKeys(["demolition", "dobae.living"])).toBeNull();
  expect(diyOfKeys(["diy.none"])).toEqual([]);
  expect(diyOfKeys(["diy.clean", "demolition", "diy.paint"])).toEqual(["paint", "clean"]);
});

test("직접 할 일 칩: 없어요는 다른 칩과 같이 고르지 않고, 다 끄면 없어요예요", () => {
  expect(diyPicks(null)).toEqual([]);
  expect(diyPicks([])).toEqual(["none"]);
  expect(diyFromPicks(["none", "paint"], ["none"])).toEqual(["paint"]);
  expect(diyFromPicks(["paint", "none"], ["paint"])).toEqual([]);
  expect(diyFromPicks(["clean", "paint"], ["clean"])).toEqual(["paint", "clean"]);
  expect(diyFromPicks([], ["paint"])).toEqual([]);
});

test("넣은 내용 줄: 철거 범위 · 직접 할 일은 고른 때만 끝에 붙어요", () => {
  const tail = (d: InfoDraft) => summaryRows(d).slice(10).map((r) => `${r.label}=${r.value}`);
  expect(tail({ ...DRAFT, demolition: null })).toEqual([]);
  expect(tail({ ...DRAFT, demolition: "partial", diy: [] })).toEqual(["철거 범위=부분 철거", "직접 할 일=없어요"]);
  expect(tail({ ...DRAFT, diy: ["clean"] })).toEqual(["철거 범위=철거 안 함", "직접 할 일=입주 청소"]);
});

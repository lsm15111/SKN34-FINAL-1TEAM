// 카드 창이 다닌 길(lib/assistant/trail): '앞 화면으로' · 닫기가 몇 칸 돌아갈지 · 창 안 앞 칸
import { expect, test } from "@playwright/test";
import { canBack, cardsBefore, closePlan, EMPTY_TRAIL, walk, type Move, type Trail } from "./trail";

const B = "/projects/p1";
const go = (...steps: [string, Move?, number?][]) =>
  steps.reduce<Trail>((t, [p, m = "push", to]) => walk(t, p, m, to ?? null), EMPTY_TRAIL);

test("대화에서 연 창: 업체 보기 → 업체 자세히에서 앞 화면이 있고, 닫기는 두 칸 뒤 대화로", () => {
  const t = go([B], [`${B}/vendors`], [`${B}/vendors/v1`]);
  expect(canBack(t, B)).toBe(true);
  expect(closePlan(t, B)).toEqual({ back: 2, replace: false });
  const first = walk(t, `${B}/vendors`, "pop");
  expect(first.at).toBe(1);
  expect(canBack(first, B)).toBe(false); // 한 칸 뒤가 대화라 '앞 화면으로'는 없어요
  expect(closePlan(first, B)).toEqual({ back: 1, replace: false });
});

test("앞으로 가기 · 뒤로 간 뒤 새 칸은 앞쪽 칸을 버려요", () => {
  let t = go([B], [`${B}/vendors`], [`${B}/vendors/v1`], [`${B}/vendors`, "pop"]);
  expect(walk(t, `${B}/vendors/v1`, "pop")).toMatchObject({ at: 2, move: "pop" });
  t = walk(t, `${B}/standard`, "push");
  expect(t.list).toEqual([B, `${B}/vendors`, `${B}/standard`]);
});

test("닫기가 정한 자리(history.go)로 바로 가고, 같은 주소가 앞에 또 있어도 가까운 대화 자리로 닫아요", () => {
  const t = go([B], [`${B}/home`], [B], [`${B}/plan`], [`${B}/docs`]);
  expect(closePlan(t, B)).toEqual({ back: 2, replace: false });
  expect(walk(t, B, "pop", 2).at).toBe(2);
});

test("링크로 바로 연 창: 대화 자리가 없으면 처음 카드까지 돌아가 대화 주소로 바꿔요", () => {
  expect(closePlan(go([`${B}/visits/1`]), B)).toEqual({ back: 0, replace: true });
  const t = go([`${B}/visits/1`], [`${B}/vendors/v1`]);
  expect(canBack(t, B)).toBe(true);
  expect(closePlan(t, B)).toEqual({ back: 1, replace: true });
  expect(walk(walk(t, `${B}/visits/1`, "pop", 0), B, "replace").list).toEqual([B, `${B}/vendors/v1`]);
});

test("목록 → 업체 → 목록(링크)에서 닫으면 처음 목록 칸으로 옮겨 그 칸을 대화로 바꿔요(주소가 지금과 같아도)", () => {
  const t = go([`${B}/vendors`], [`${B}/vendors/v1`], [`${B}/vendors`]);
  expect(closePlan(t, B)).toEqual({ back: 2, replace: true });
  const landed = walk(t, `${B}/vendors`, "pop", 0);
  expect(landed.at).toBe(0);
  expect(walk(landed, B, "replace").list).toEqual([B, `${B}/vendors/v1`, `${B}/vendors`]);
  expect(walk(t, `${B}/vendors`, "pop", 1)).toBe(t); // 정한 자리 주소가 다르면 그대로
});

test("이 화면이 뜨기 전 칸으로 뒤로 가면 맨 앞에 붙고, 같은 주소를 다시 받아도 한 칸이에요", () => {
  const t = walk(go([`${B}/plan`]), `${B}/standard`, "pop");
  expect(t).toMatchObject({ list: [`${B}/standard`, `${B}/plan`], at: 0 });
  expect(walk(t, `${B}/standard`, "push")).toBe(t);
});

test("창 안 앞 칸(창 모양 정하기): 창을 연 칸부터 지금 칸 앞까지, 대화 자리에서 끊어요", () => {
  expect(cardsBefore(go([B], [`${B}/vendors`], [`${B}/vendors/v1`]), B)).toEqual([`${B}/vendors`]); // 업체 보기 안에서 연 업체
  expect(cardsBefore(go([B], [`${B}/vendors/v1`]), B)).toEqual([]); // 대화에서 바로 연 업체
  const t = go([B], [`${B}/vendors/v1`], [`${B}/visits/new`], [`${B}/vendors`], [`${B}/vendors/v2`]);
  expect(cardsBefore(t, B)).toEqual([`${B}/vendors/v1`, `${B}/visits/new`, `${B}/vendors`]);
  expect(cardsBefore(walk(t, `${B}/vendors/v1`, "pop", 1), B)).toEqual([]); // 뒤로 창을 연 칸에 오면 앞 칸 없음
  expect(cardsBefore(go([B], [`${B}/home`], [B], [`${B}/vendors/v1`]), B)).toEqual([]); // 앞서 닫은 창 칸은 세지 않아요
  expect(cardsBefore(go([`${B}/vendors`], [`${B}/vendors/v1`]), B)).toEqual([`${B}/vendors`]); // 링크로 바로 연 창
  expect(cardsBefore(go([B], [`${B}/vendors`], [B]), B)).toEqual([]); // 창이 없으면 없음
  expect(cardsBefore(EMPTY_TRAIL, B)).toEqual([]);
});

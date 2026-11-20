// J3 표준견적서 → 업체 보기 → 업체 상세 → 업체 담기 3곳 → 실측 일정 요청 → 실측 일정 상태판
// 화면: C06 · C07 · C10 · C11 · C13 · C14 · C15 · C50 (웹 D01 · D06 · D07 · D08 · D03) · C12(다른 집 예시)
// - 고객: 김처음(v3-c01, 기본 정보만). 시연 노원구 업체는 3곳(마루와벽 · 결도배 · 한결인테리어)이고 한결은 '가견적 준비 중'이에요.
//   3곳 담기를 보려고 시험 가운데에 한결이 단가를 확인해요(API, 업체가 D02에서 하는 일과 같은 몸통).
// - 금액: 표준견적서 · 가견적 · 고정된 가견적 = API 값. 개인정보: 업체가 받는 요청에 이름 · 휴대폰이 없고 사진 위치 정보가 지워져요.
import type { BrowserContext, Locator, Page } from "@playwright/test";
import { apiGet, apiSend, board, loginApi } from "./support/api";
import { dueShort } from "./support/calendar";
import { DEMO, demoPassword } from "./support/env";
import { asset, hasGpsExif } from "./support/files";
import { expect, test } from "./support/fixtures";
import { expectAmount, expectNoEnglishState, expectNoSideScroll, isPhone, loginUi, pageText, shot, shown, won } from "./support/ui";

type Std = { supply: number; vat: number; total: number; trades: { lines: { name: string; amount: number | null; state: string }[] }[] };
type Card = { vendor_id: string; name: string; sgg: string; estimate_total: number | null; vs_standard_pct: string | null; rating: string | null; review_count: number; done_count: number; instant_badge: boolean; state: string };
type List = { local: Card[]; nearby: Card[]; nearby_sgg: string[]; area_name: string; standard_total: number };
type Detail = { estimate_v3: { total: number; supply: number; vat: number } | null; grade_diff?: number | null };

/** '표준견적서보다 58.5% 많아요'(components/vendors/v3text compareText와 같은 말) */
function compareText(pct: string | null): string | null {
  if (pct == null || pct === "") return null;
  const n = Number(pct);
  if (n === 0) return "표준견적서와 같아요";
  return `표준견적서보다 ${String(Math.abs(n))}% ${n > 0 ? "많아요" : "적어요"}`;
}

/** 업체 카드 하나(이름 링크를 품은 가장 안쪽 칸) */
function card(page: Page, name: string): Locator {
  return page.locator("div").filter({ has: page.getByRole("link", { name: new RegExp(`^${name}`) }) }).last();
}

/** 한결인테리어가 도배 단가를 확인해요(D02 '확인하고 저장'과 같은 API, 시연 마루와벽과 비슷한 값) */
async function hangyeolConfirmsPrices(ctx: BrowserContext) {
  {
    const got = await apiGet<{ v3: { version: number } | null }>(ctx, "/vendor/prices?trade=dobae");
    await apiSend(ctx, "POST", "/vendor/prices/dobae/confirm", {
      base_version: got.v3?.version ?? 0,
      lines: [
        { key: "putty", mode: "price", unit_price: 18_000 },
        { key: "paper_hapji", mode: "price", unit_price: 5_000 },
        { key: "paper_silk", mode: "price", unit_price: 9_800 },
        { key: "material", mode: "price", unit_price: 12_000 },
        { key: "labor", mode: "price", unit_price: 290_000 },
        { key: "meal", mode: "included", included_in: "labor" },
        { key: "truck", mode: "price", unit_price: 40_000 },
      ],
    });
  }
}

test("J3 표준견적서 → 업체 담기 3곳 → 실측 일정 요청 → 상태판", async ({ page, other }, info) => {
  test.setTimeout(420_000);
  const phone = isPhone(info);
  const ctx = page.context();
  let pid = "";

  await test.step("C06 로그인 → 진행 중 공사", async () => {
    await loginUi(page, DEMO.c01, demoPassword());
    await page.waitForURL(/\/projects\/[^/]+$/);
    pid = new URL(page.url()).pathname.split("/")[2];
  });

  const std = await apiGet<Std>(ctx, `/projects/${pid}/standard`);
  await test.step("C07 · D01 표준견적서 = API", async () => {
    await page.goto(`/projects/${pid}/standard`);
    await expect(page.getByRole("heading", { name: "표준견적서", level: 1 })).toBeVisible();
    await expect(page.getByText(won(std.total), { exact: true }).first()).toBeVisible();
    for (const n of [std.supply, std.vat, std.total]) await expectAmount(page, n, "C07 합계 칸");
    for (const l of std.trades.flatMap((t) => t.lines).filter((x) => x.amount != null && x.state === "included")) await expectAmount(page, l.amount!, `C07 줄 ${l.name}`);
    await expect(shown(page.getByText("시장 데이터 기준으로 계산한 참고 금액이에요. 업체 견적이 아니에요.")).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "바꾸기" })).toHaveAttribute("href", `/start?edit=${pid}`);
    if (!phone) await expect(page.getByRole("complementary", { name: /AI/ }).first()).toBeVisible();
    await expectNoEnglishState(page, "C07");
    await expectNoSideScroll(page, "C07 표준견적서");
    await shot(page, "01-C07-standard");
  });

  let list: List;
  await test.step("C10 · D06 업체 보기: 가견적 낮은 순 · API 값 · 한결 '가견적 준비 중'", async () => {
    await shown(page.getByRole("link", { name: "업체 보기" })).first().click();
    await page.waitForURL(`**/projects/${pid}/vendors`);
    list = await apiGet<List>(ctx, `/projects/${pid}/vendors?trade=dobae`);
    const n = list.local.length;
    await expect(page.getByText(`${list.area_name} ${n}곳 · 모두 사업자 확인함 · 가견적 낮은 순 · 표준견적서 ${won(list.standard_total)}`)).toBeVisible();
    expect(list.standard_total, "업체 목록 표준견적서 = 표준견적서 합계").toBe(std.total);
    for (const c of list.local) {
      const box = card(page, c.name);
      if (c.estimate_total == null) {
        await expect(box).toContainText("가견적 준비 중");
        await expect(box.getByRole("button", { name: "가견적 준비 중" })).toBeDisabled();
        continue;
      }
      await expect(box).toContainText(won(c.estimate_total));
      const cmp = compareText(c.vs_standard_pct);
      if (cmp) await expect(box).toContainText(cmp);
      await expect(box).toContainText(`믿집 공사 ${c.done_count}건`);
      if (c.instant_badge) await expect(box).toContainText("바로 확정");
    }
    // 가견적 낮은 순(가견적 없음은 맨 뒤)
    const priced = list.local.filter((c) => c.estimate_total != null).map((c) => c.estimate_total!);
    expect([...priced].sort((a, b) => a - b)).toEqual(priced);
    await expect(page.getByText(/가견적 준비 중인 업체 1곳/)).toBeVisible();
    await expect(shown(page.getByText("3곳까지 담을 수 있어요")).first()).toBeVisible();
    await expectNoEnglishState(page, "C10");
    await expectNoSideScroll(page, "C10 업체 보기");
    await shot(page, "02-C10-vendors");
  });

  const maru = () => list.local.find((c) => c.name === "마루와벽")!;
  await test.step("C11 · D07 업체 상세: 가견적 = API, 합지로 보기 = API(?grade=economy)", async () => {
    await page.getByRole("link", { name: /^마루와벽/ }).first().click();
    await page.waitForURL(`**/projects/${pid}/vendors/${maru().vendor_id}`);
    const d = await apiGet<Detail>(ctx, `/projects/${pid}/vendors/${maru().vendor_id}?trade=dobae`);
    await expect(page.getByRole("heading", { name: "마루와벽", level: 1 })).toBeAttached();
    await expect(page.getByText("가견적 · 부가세 포함")).toBeVisible();
    await expect(page.getByText(won(d.estimate_v3!.total), { exact: true }).first()).toBeVisible();
    for (const n of [d.estimate_v3!.supply, d.estimate_v3!.vat, d.estimate_v3!.total]) await expectAmount(page, n, "C11 가견적 합계 칸");
    await expect(page.getByText("요청할 때 고른 벽지로 가견적이 고정돼요")).toBeVisible();
    await expect(page.getByText("업체 단가 × 믿집 수량").first()).toBeVisible();
    await expectNoSideScroll(page, "C11 업체 상세");
    await shot(page, "03-C11-detail");
    // 합지로 보기: 주소 ?grade=economy, 금액은 서버가 다시 계산(화면은 더하지 않아요)
    const eco = await apiGet<Detail>(ctx, `/projects/${pid}/vendors/${maru().vendor_id}?trade=dobae&grade=economy`);
    await page.getByRole("radio", { name: /합지/ }).check();
    await page.waitForURL(/grade=economy/);
    await expect(page.getByText(won(eco.estimate_v3!.total), { exact: true }).first()).toBeVisible();
    await page.getByRole("radio", { name: /실크/ }).check();
    await page.waitForURL(/grade=basic/);
    await expect(page.getByText(won(d.estimate_v3!.total), { exact: true }).first()).toBeVisible();
    await page.goto(`/projects/${pid}/vendors`);
  });

  await test.step("C10 담기: 빠르게 두 번 눌러도 한 번(D29) · 2곳 담기", async () => {
    const m = card(page, "마루와벽").getByRole("button", { name: "담기" });
    await m.dblclick();
    await expect(card(page, "마루와벽").getByRole("button", { name: /담음/ })).toHaveAttribute("aria-pressed", "true");
    const s1 = await apiGet<{ items: { vendor_id: string }[] }>(ctx, `/projects/${pid}/shortlist?trade=dobae`);
    expect(s1.items.map((x) => x.vendor_id), "마루와벽 한 번만 담김").toEqual([maru().vendor_id]);
    await card(page, "결도배").getByRole("button", { name: "담기" }).click();
    await expect(card(page, "결도배").getByRole("button", { name: /담음/ })).toHaveAttribute("aria-pressed", "true");
    await expect(shown(page.getByText("1곳 더 담을 수 있어요")).first()).toBeVisible();
  });

  await test.step("D06 A 한결이 단가를 확인하면 담을 수 있어요 → 3곳 담기 · 3곳 다 담음", async () => {
    await expect(card(page, "한결인테리어").getByRole("button", { name: "가견적 준비 중" })).toBeDisabled();
    await hangyeolConfirmsPrices((await other(DEMO.hangyeol)).context);
    await page.reload();
    list = await apiGet<List>(ctx, `/projects/${pid}/vendors?trade=dobae`);
    const h = list.local.find((c) => c.name === "한결인테리어")!;
    expect(h.estimate_total, "한결 가견적(단가 확인 뒤)").not.toBeNull();
    await expect(card(page, "한결인테리어")).toContainText(won(h.estimate_total!));
    await card(page, "한결인테리어").getByRole("button", { name: "담기" }).click();
    await expect(card(page, "한결인테리어").getByRole("button", { name: /담음/ })).toHaveAttribute("aria-pressed", "true");
    await expect(shown(page.getByText("3곳을 다 담았어요")).first()).toBeVisible();
    await expect(shown(page.getByText("담은 업체 3곳")).first()).toBeVisible();
    await expectNoSideScroll(page, "C10 업체 3곳 담음");
    await shot(page, "04-C10-shortlist-3");
  });

  let draft: { wish_start: string; wish_end: string; vendors: { vendor_id: string; name: string; estimate_total: number | null }[] };
  await test.step("C13 · D08 실측 일정 요청서: 희망 기간 초안 · 보낼 업체 3곳 · 사진 2장", async () => {
    await shown(page.getByRole("link", { name: "실측 일정 잡기" })).first().click();
    await page.waitForURL(`**/projects/${pid}/visits/new`);
    draft = await apiGet<typeof draft>(ctx, `/projects/${pid}/visits/draft?trade=dobae`);
    await expect(page.getByRole("heading", { name: "실측 일정 요청", level: 1 })).toBeVisible();
    const send = page.getByRole("group", { name: "보낼 업체" });
    expect(draft.vendors.length).toBe(3);
    for (const v of draft.vendors) {
      const row = send.getByRole("checkbox", { name: new RegExp(v.name) });
      await expect(row).toBeChecked();
      await expect(send).toContainText(`가견적 ${won(v.estimate_total!)}`);
    }
    await page.getByLabel("집 사진 올리기").setInputFiles([asset("wall-gps-1.jpg"), asset("wall-gps-2.jpg")]);
    await expect(page.getByRole("list", { name: "올린 사진" }).getByRole("img")).toHaveCount(2);
    await expect(page.getByText("올리는 중")).toHaveCount(0, { timeout: 60_000 });
    await expect(shown(page.getByText("보내면 지금 가견적이 고정되고, 기본 정보는 잠겨요")).first()).toBeVisible();
    await expectNoSideScroll(page, "C13 실측 일정 요청서");
    await shot(page, "05-C13-request");
  });

  await test.step("C13 → C14 · D03 '고른 3곳에 요청 보내기' → 상태판: 답 기다림 · 기한 = 보낸 때 + 48시간(API)", async () => {
    const res = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${pid}/visits`) && r.request().method() === "POST");
    await shown(page.getByRole("button", { name: "고른 3곳에 요청 보내기" })).first().click();
    expect((await res).status(), "POST 실측 요청").toBe(201);
    await page.waitForURL(`**/projects/${pid}/visits`);
    const rows = await board(ctx, pid);
    expect(rows.map((r) => r.status)).toEqual(["requested", "requested", "requested"]);
    const v = await apiGet<{ head: { sent_at: string } | null; board: { vendor_name: string; next: { due_at: string | null } }[] }>(ctx, `/projects/${pid}/visits`);
    const sent = new Date(v.head!.sent_at).getTime();
    for (const r of v.board) {
      expect(new Date(r.next.due_at!).getTime() - sent, `${r.vendor_name} 답 기한 = 보낸 때 + 48시간`).toBe(48 * 3600_000);
    }
    const due = dueShort(v.board[0].next.due_at!);
    if (phone) {
      const cards = page.getByRole("list", { name: "업체별 실측 일정" });
      for (const r of v.board) {
        const li = cards.getByRole("listitem").filter({ has: page.getByRole("heading", { name: r.vendor_name }) });
        await expect(li).toContainText("답 기다림");
        await expect(li).toContainText(`${due} 답해요`);
      }
    } else {
      const table = page.getByRole("table", { name: "업체별 실측 일정" });
      await expect(table).toBeVisible();
      for (const r of v.board) await expect(table.getByRole("columnheader", { name: new RegExp(r.vendor_name) })).toBeVisible();
      await expect(table).toContainText("답 기다림");
    }
    // 고정된 가견적 = 요청서의 가견적
    for (const r of rows) expect(r.estimate_total, `${r.vendor_name} 고정된 가견적`).toBe(draft.vendors.find((x) => x.name === r.vendor_name)!.estimate_total);
    await expectNoEnglishState(page, "C14");
    await expectNoSideScroll(page, "C14 실측 일정");
    await shot(page, "06-C14-board");
  });

  await test.step("C15 요청 내용: 고정된 가견적 · 사진 위치 정보 지움 · 보내지 않은 것", async () => {
    await shown(page.getByRole("button", { name: "요청 내용" })).first().click();
    const sheet = page.getByRole("dialog", { name: /에 보낸 요청$/ });
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("위치 정보 지움");
    await expect(sheet).toContainText("2장");
    await expect(sheet).toContainText("이름 · 휴대폰 · 동 · 호수");
    for (const v of draft.vendors) await expect(sheet).toContainText(won(v.estimate_total!));
    await expectNoSideScroll(page, "C15 요청 내용");
    await shot(page, "07-C15-request-sheet");
    await sheet.getByRole("button", { name: "닫기" }).first().click();
    // 폰 시트는 열 때 기록 한 칸을 넣고 닫을 때 history.back()을 한 박자 뒤에 해요(useModal).
    // 그 뒤로 가기가 다음 page.goto와 겹치면 ERR_ABORTED라서, 창이 닫히고 기록 칸이 걷힐 때까지 기다려요
    await expect(sheet).toBeHidden();
    await page.waitForFunction(() => !(history.state as { mjModal?: boolean } | null)?.mjModal);
  });

  await test.step("C50 기본 정보 잠김", async () => {
    await page.goto(`/start?edit=${pid}`);
    await expect(page.getByText("실측 요청을 보내서 기본 정보를 바꿀 수 없어요.", { exact: false })).toBeVisible();
    await expect(shown(page.getByRole("link", { name: "다른 조건으로 새로 받기" })).first()).toBeVisible();
    await expectNoSideScroll(page, "C50 기본 정보 잠김");
  });

  await test.step("업체가 받은 요청: 구 · 동 · 면적만, 사진 위치 정보 없음(G6)", async () => {
    const v = await other(DEMO.maru);
    const rows = await apiGet<{ items: { id: string; area_label?: string | null }[] }>(v.context, "/vendor/visits?tab=todo");
    const mine = (await board(ctx, pid)).find((r) => r.vendor_name === "마루와벽")!;
    const row = rows.items.find((x) => x.id === mine.visit_id);
    expect(row, "마루와벽 작업함에 새 요청").toBeTruthy();
    const detail = await apiGet<Record<string, unknown> & { photos?: string[]; area_label?: string | null }>(v.context, `/vendor/visits/${mine.visit_id}`);
    const flat = JSON.stringify(detail);
    expect(flat, "업체 응답에 고객 이름이 없어요").not.toContain("김처음");
    expect(detail.area_label ?? "", "구 · 동 · 면적까지").toContain("상계동");
    expect(detail.photos?.length ?? 0, "요청 사진 2장").toBe(2);
    for (const fid of detail.photos ?? []) {
      const res = await v.context.request.get(`/api/vendor/visits/${mine.visit_id}/photos/${fid}`);
      expect(res.ok(), "업체가 요청 사진을 받아요").toBeTruthy();
      expect(hasGpsExif(Buffer.from(await res.body())), "사진 위치 정보(GPS)가 지워졌어요").toBe(false);
    }
    await v.page.goto(`/vendor/requests/${mine.visit_id}`);
    const text = await pageText(v.page);
    expect(text).not.toContain("김처음");
    await expectNoSideScroll(v.page, "V04 업체가 받은 요청(J3 끝)");
  });
});

test("J3 · C12 업체 0곳: 이 구에 업체가 없으면 가까운 구 업체", async ({ page }) => {
  await loginApi(page.context(), DEMO.c01);
  // 시연 업체는 서울 25개 구를 다 다녀서(11-20), 서울 밖 구리시에 새 공사 하나를 API로 만들어요(기본 정보 v3 몸통).
  // 구리시는 이웃 구 자료가 없어 '가까운 구에도 아직 업체가 없어요' 갈래로 가요
  const p = await apiSend<{ id: string }>(page.context(), "POST", "/projects", {
    trade: "dobae", scope: "full", spaces: [], faces: ["wall", "ceiling"], housing: "apt",
    sido: "gyeonggi", sgg: "구리시", emd: null, area_m2: "59.9", area_basis: "exclusive", occupied: true, grade: "basic", budget_won: null, start_date: null,
  }, { "Idempotency-Key": crypto.randomUUID() });
  const list = await apiGet<List>(page.context(), `/projects/${p.id}/vendors?trade=dobae`);
  expect(list.local.length, "구리시 업체").toBe(0);
  await page.goto(`/projects/${p.id}/vendors`);
  await expect(page.getByRole("heading", { name: /구리시에서 도배하는\s*믿집 업체가 아직 없어요/ })).toBeVisible();
  if (list.nearby.length) {
    await expect(page.getByText(`가까운 구 · ${list.nearby_sgg.join(" · ")} ${list.nearby.length}곳`)).toBeVisible();
    // 9판 C12 · CF-30: 가까운 구 카드마다 그 업체의 구 이름('노원구')
    for (const c of list.nearby) {
      if (c.estimate_total != null) await expect(card(page, c.name)).toContainText(c.sgg);
      else await expect.soft(card(page, c.name), `${c.name}(가견적 준비 중) 카드에도 구 이름이 있어요`).toContainText(c.sgg);
    }
  } else {
    await expect(page.getByText("가까운 구에도 아직 업체가 없어요.")).toBeVisible();
  }
  await expectNoSideScroll(page, "C12 업체 0곳");
  await shot(page, "08-C12-zero");
});

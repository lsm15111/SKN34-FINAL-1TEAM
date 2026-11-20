// J1 처음 온 고객: 홈 → 기본 정보(평으로 넣기) → 손님 표준견적서(+ 로그인 전 AI 칸) → 업체 보기 → 가입 카드 → 이메일 가입 → 업체 보기
// 화면: C01 · C02 · C03 · C57 · C58 · C59 · C05 · C10 (웹 D10 · D11 · D12 · D13 · D06) · C42 · C54 · C55
// 금액: 손님 표준견적서 = POST /guest/standard 값, 가입 뒤 내 공사 표준견적서 · 업체 가견적 = API 값
import { randomUUID } from "node:crypto";
import { apiGet } from "./support/api";
import { addDays, pickDay, todaySeoul } from "./support/calendar";
import { freshEmail } from "./support/env";
import { expect, test } from "./support/fixtures";
import { choose, expectAmount, expectNoEnglishState, expectNoSideScroll, isPhone, pageText, shot, shown, won } from "./support/ui";

type GuestLine = { key: string; name: string; amount: number | null; state: string };
type GuestOut = { supply: number; vat: number; total: number; lines: GuestLine[] };
type VendorCard = { vendor_id: string; name: string; estimate_total: number | null; state: string };


/** 다음 월요일(오늘 + 48일 뒤부터, 9판 요청 → 공사 시작 간격) */
function startMonday(): string {
  let d = addDays(todaySeoul(), 48);
  while (new Date(`${d}T00:00:00Z`).getUTCDay() !== 1) d = addDays(d, 1);
  return d;
}

test("J1 처음 고객: 기본 정보 → 손님 표준견적서 → 가입 카드 → 가입 → 업체 보기", async ({ page }, info) => {
  const phone = isPhone(info);

  await test.step("C01 · D10 홈(로그인 전)", async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /표준견적서부터\s*받아 보세요/ })).toBeVisible();
    await expect(page.getByText("시장 데이터 기준 금액과 업체 가견적을 나란히 봐요.")).toBeVisible();
    await expect(page.getByText("1분 · 가입 없이 바로 봐요")).toBeVisible();
    await expect(shown(page.getByRole("link", { name: "업체로 가입" })).first()).toBeVisible();
    if (!phone) await expect(page.getByRole("heading", { name: "이렇게 진행돼요" })).toBeVisible();
    await expectNoSideScroll(page, "C01 홈");
    await shot(page, "01-C01-home");
  });

  await test.step("C02 · D11 기본 정보", async () => {
    await shown(page.getByRole("link", { name: /견적서 받기/ })).first().click();
    await expect(page).toHaveURL(/\/start$/);
    await expect(page.getByRole("heading", { name: "기본 정보", level: 1 })).toBeVisible();
    for (const g of ["어떤 공사", "우리 집", "희망"]) await expect(page.getByRole("heading", { name: g, exact: true })).toBeVisible();
    await expect(page.getByText("빌라 · 다세대")).toBeVisible();

    await choose(page, "공사 범위", "전체");
    // 지역: 시 · 도 → 시 · 군 · 구 → 동
    await page.getByRole("button", { name: /지역/ }).click();
    const region = page.getByRole("dialog", { name: "지역 고르기" });
    await region.getByLabel("시 · 도").selectOption("seoul");
    await region.getByLabel("시 · 군 · 구").selectOption("노원구");
    await region.getByLabel("동").selectOption("상계동");
    await region.getByRole("button", { name: "이 지역으로" }).click();
    await expect(region).toBeHidden();
    await expect(page.getByRole("button", { name: /서울 노원구 상계동/ })).toBeVisible();
  });

  await test.step("C03 평으로 넣기(21평 → 69.4㎡)", async () => {
    await page.getByRole("button", { name: "평으로 넣기" }).click();
    const sheet = page.getByRole("dialog", { name: "평으로 넣기" });
    await expect(sheet.getByText("계산 · 견적서는 ㎡로 해요. 평은 넣을 때만 써요.")).toBeVisible();
    await sheet.getByLabel("평", { exact: true }).fill("21");
    await expect(sheet.getByText("3.3058")).toBeVisible();
    await expect(sheet.getByText(/69\.4/).first()).toBeVisible();
    await expectNoSideScroll(page, "C03 평으로 넣기");
    await shot(page, "02-C03-pyeong");
    await sheet.getByRole("button", { name: /69\.4㎡로 넣기/ }).click();
    await expect(sheet).toBeHidden();
    await expect(page.getByLabel("공급면적(㎡)")).toHaveValue("69.4");
  });

  const start = startMonday();
  await test.step("C02 나머지 칸 · 공사 시작 희망일", async () => {
    await choose(page, "공사할 때 집은", "빈 집");
    await choose(page, "벽지", "실크");
    await page.getByLabel("예산").fill("300");
    await page.getByRole("button", { name: /공사 시작 희망일/ }).click();
    const sheet = page.getByRole("dialog", { name: "공사 시작 희망일" });
    await pickDay(sheet.getByRole("group", { name: "공사 시작 희망일" }), start);
    await sheet.getByRole("button", { name: "이 날로" }).click();
    await expect(sheet).toBeHidden();
    if (!phone) {
      // D11 오른쪽 '넣은 내용' 요약이 넣는 대로 바뀌어요
      const aside = page.getByRole("complementary", { name: "넣은 내용" });
      await expect(aside).toContainText("상계동");
      await expect(aside).toContainText("69.4㎡");
      await expect(aside).toContainText("실크");
      await expect(aside).toContainText("300만 원");
    }
    await expect(shown(page.getByText("가입 없이 바로 봐요 · 답은 이 기기에 저장돼요")).first()).toBeVisible();
    await expectNoSideScroll(page, "C02 기본 정보");
    await shot(page, "03-C02-info");
  });

  let guest: GuestOut;
  await test.step("C57 · D12 손님 표준견적서 = 계산 엔진 값", async () => {
    const res = page.waitForResponse((r) => r.url().includes("/api/guest/standard") && r.request().method() === "POST");
    await shown(page.getByRole("button", { name: "표준견적서 보기" })).first().click();
    const got = await res;
    expect(got.status(), "POST /guest/standard").toBe(200);
    guest = (await got.json()) as GuestOut;
    await expect(page).toHaveURL(/\/start\/standard$/);
    await expect(page.getByRole("heading", { name: "표준견적서", level: 1 })).toBeVisible();
    // 큰 합계(만 단위) + 합계 칸(공급가 · 부가세 · 합계)이 API 값과 같아요
    await expect(page.getByText(won(guest.total), { exact: true }).first()).toBeVisible();
    const sum = page.getByRole("region", { name: "표준견적서 합계" });
    await expect(sum).toContainText("부가세 포함");
    // 폰은 줄 목록('1,873,295원'), 웹은 표('1,873,295')로 그려서 보이는 글 전체에서 찾아요
    for (const n of [guest.supply, guest.vat, guest.total]) await expectAmount(page, n, "C57 합계 칸");
    expect(guest.supply + guest.vat).toBe(guest.total);
    // 줄 금액 = API 줄 금액, 실측 후 줄(철거)은 괄호 · 합계 밖
    for (const l of guest.lines.filter((x) => x.amount != null && x.state === "included")) await expectAmount(page, l.amount!, `C57 줄 ${l.name}`);
    const removal = guest.lines.find((l) => l.key === "removal");
    if (removal?.amount != null) expect(await pageText(page), "철거 줄은 괄호(합계 밖)").toContain(`(${removal.amount.toLocaleString("ko-KR")}`);
    await expect(page.getByText("시장 데이터 기준으로 계산한 참고 금액이에요. 업체 견적이 아니에요.").first()).toBeVisible();
    await expectNoEnglishState(page, "C57");
    await expectNoSideScroll(page, "C57 손님 표준견적서");
    await shot(page, "04-C57-guest-standard");
  });

  await test.step("C58 · D12 로그인 전 AI에게 묻기: 칩만", async () => {
    // 9판 C58 · D12: '로그인하면 AI에게 물을 수 있어요' + 자주 묻는 질문 칩 3개 + '가입 · 로그인'
    const chips = ["표준견적서는 업체 견적이에요?", "가견적은 어떻게 나와요?", "실측은 돈이 들어요?"];
    let box;
    if (phone) {
      await page.getByRole("button", { name: "AI에게 묻기" }).click();
      box = page.getByRole("dialog", { name: "로그인하면 AI에게 물을 수 있어요" });
    } else {
      box = page.getByRole("complementary", { name: "AI에게 묻기" });
      await expect(box.getByText("로그인하면 AI에게 물을 수 있어요")).toBeVisible();
    }
    await expect(box.getByText("그 전에는 자주 묻는 질문을 볼 수 있어요.").or(box.getByText("그 전에는 자주 묻는 질문을 봐요."))).toBeVisible();
    for (const q of chips) await expect(box.getByText(q, { exact: true })).toBeVisible();
    await shot(page, "05-C58-guest-ask");
    await box.getByRole("button", { name: "가입 · 로그인" }).click();
    // 시트를 닫고 가운데 가입 카드가 떠요
    const join = page.getByRole("dialog", { name: "가입하고 이어서 봐요" });
    await expect(join).toBeVisible();
    await join.getByRole("button", { name: "나중에 할게요" }).click();
    await expect(join).toBeHidden();
  });

  await test.step("C59 · D13 업체 보기 → 가입 카드 → 나중에 → 다시 → 이메일로 가입", async () => {
    await shown(page.getByRole("button", { name: "업체 보기" })).first().click();
    const join = page.getByRole("dialog", { name: "가입하고 이어서 봐요" });
    await expect(join.getByText("업체 가견적 · 예상 공정표는 가입하면 열려요")).toBeVisible();
    await expect(join.getByText("준비 중")).toBeVisible();
    await expectNoSideScroll(page, "C59 가입 카드");
    await shot(page, "06-C59-join");
    await join.getByRole("button", { name: "나중에 할게요" }).click();
    await expect(join).toBeHidden();
    await expect(page.getByText(won(guest.total), { exact: true }).first()).toBeVisible();
    await shown(page.getByRole("button", { name: "업체 보기" })).first().click();
    await join.getByRole("link", { name: "이메일로 가입" }).click();
    await expect(page).toHaveURL(/\/signup\?step=email/);
  });

  const email = freshEmail("j1", info.project.name);
  let projectId = "";
  await test.step("C05 이메일 가입 · 약관 동의(휴대폰 비움) → 업체 보기", async () => {
    const form = page.getByRole("form", { name: "이메일로 가입" });
    await expect(form.getByText("업체에는 가지 않아요.")).toBeVisible();
    await form.getByLabel("이메일").fill(email);
    await form.getByLabel("비밀번호").fill(`E2e-${randomUUID().slice(0, 12)}`); // 이 시험에서만 쓰는 값(기록하지 않아요)
    await form.getByLabel("이름").fill("시험 고객");
    await form.getByLabel("모두 동의해요").check();
    for (const t of ["[필수] 이용약관", "[필수] 개인정보 수집 · 이용", "[필수] 만 14세 이상이에요"]) await expect(form.getByLabel(t)).toBeChecked();
    await expectNoSideScroll(page, "C05 이메일 가입");
    await shot(page, "07-C05-email");
    await form.getByRole("button", { name: "가입하고 업체 보기" }).click();
    await page.waitForURL(/\/projects\/[^/]+\/vendors$/, { timeout: 60_000 });
    projectId = page.url().match(/\/projects\/([^/]+)\/vendors/)![1];
  });

  await test.step("C10 · D06 업체 보기: 가견적 = API, 표준견적서 금액은 가입 전과 같아요", async () => {
    const ctx = page.context();
    const std = await apiGet<{ total: number }>(ctx, `/projects/${projectId}/standard`);
    expect(std.total, "가입 전 · 뒤 표준견적서 합계").toBe(guest.total);
    const list = await apiGet<{ local: VendorCard[]; standard_total: number; area_name: string }>(ctx, `/projects/${projectId}/vendors?trade=dobae`);
    await expect(page.getByRole("heading", { name: "업체 보기", level: 1 })).toBeVisible();
    await expect(page.getByText(`${list.area_name} ${list.local.length}곳 · 모두 사업자 확인함 · 가견적 낮은 순`)).toBeVisible();
    expect(list.local.length, "노원구 시연 업체").toBeGreaterThanOrEqual(2);
    for (const v of list.local) {
      const link = page.getByRole("link", { name: new RegExp(`^${v.name}`) }).first();
      await expect(link).toBeVisible();
      if (v.estimate_total != null) await expect(link).toContainText(won(v.estimate_total));
      else await expect(link).toContainText("가견적 준비 중");
    }
    await expect(shown(page.getByText("3곳까지 담을 수 있어요")).first()).toBeVisible();
    await expectNoEnglishState(page, "C10");
    await expectNoSideScroll(page, "C10 업체 보기");
    await shot(page, "08-C10-vendors");
  });

  await test.step("C42 내 공사: 공사 1건 · 단계 '업체 담기'", async () => {
    await page.goto("/my");
    await expect(page.getByText(/상계동 아파트 도배/).first()).toBeVisible();
    await expect(page.getByText("업체 담기").first()).toBeVisible();
    await expectNoSideScroll(page, "C42 내 공사");
  });

  await test.step("C54 자주 묻는 질문 · C55 약관", async () => {
    await page.goto("/faq");
    await expect(page.getByRole("heading", { name: "자주 묻는 질문", level: 1 })).toBeVisible();
    await expectNoSideScroll(page, "C54 자주 묻는 질문");
    await page.goto("/legal");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/약관|개인정보/);
    await expectNoSideScroll(page, "C55 약관");
  });
});

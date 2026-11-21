// J10 업체: 가입부터 첫 답까지
// 화면: V01 → A01(보완 요청) → V14 → A01(승인) → V02 → V15 → V16 → V18 → D02 → V03 → V04 (웹은 D04 · D14 배치)
// - 새 업체가 화면으로 가입 신청(등록증 PDF) → 관리자 보완 요청 → 업체가 등록증 사진(위치 정보가 든 JPG)을 다시 보냄 → 승인
//   → 기본 정보 · 시공 사례 · 외부 리뷰 링크 · 도배 단가를 넣어 고객에게 보일 준비 → 고객(김처음)이 API로 담고 실측 요청 → 업체가 기간을 답해요.
// - 금액: D02 '공급 69.4㎡ 집이면' 줄 금액 · 가견적 = GET /vendor/prices 값, 고객(같은 집) 가견적과도 견줘요.
// - 개인정보: 다시 올린 등록증 사진의 위치 정보(GPS EXIF)가 지워졌는지 관리자 화면 파일로 봐요.
// - 관리자 화면은 웹 전용이라 폰 프로젝트에서도 관리자 문맥은 1280×800으로 열어요.
// 9판 글과 지금 코드 글이 다른 곳(copy-fixes 반영): V01 '하는 공정' → '하는 공사'(CF-11) · A01 표 머리 '신청 · 공정' → '신청일 · 공사'(CF-66 · CF-11)
//   · V03 · V04 위치 안내 '위치는 동까지만 …' → '위치는 동네(구 · 동)까지만 … 동 · 호수 …' · V15 세금 '과세 · 면세' → '일반과세 · 간이과세 · 면세'(L02)
//   · V15 실내건축업 등록 도움말 '확인 안 됨으로 보여요' → '보이지 않아요'(L05). 아래 확인은 지금 코드 글을 써요.
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import type { Browser, BrowserContext, Page } from "@playwright/test";
import { apiGet, apiSend, loginApi, myProject } from "./support/api";
import { addDays, pickDay, todaySeoul } from "./support/calendar";
import { DEMO, freshEmail } from "./support/env";
import { asset, hasGpsExif } from "./support/files";
import { expect, test } from "./support/fixtures";
import { expectNoEnglishState, expectNoSideScroll, isPhone, shot, shown, won } from "./support/ui";


type PriceRow = { code: string; key: string; name: string; unit: string; mode: string | null; unit_price: number | null; example_amount: number; warn_high?: number | null };
type PricesV3 = { version: number; needs_setup: boolean; confirmed_at: string | null; lines: PriceRow[]; example: { total: number; supply: number; vat: number } | null; example_home: string };
type AdminDetail = { user_id: string; status: string; license_file_id: string; reviews: { action: string }[] };
type Profile = { contact_method: string | null; updated_at: string | null; intro?: string | null; areas: { sgg: string }[]; portfolio: { space?: string | null; paper?: string | null; area_m2?: string | null }[] };
type ReviewLink = { label: string | null; url: string; status: string };
type VendorCard = { vendor_id: string; name: string; estimate_total: number | null; state: string };
type InboxRow = { id: string; status: string; area_label?: string | null; estimate_total?: number | null; wish_start?: string | null; wish_end?: string | null; state?: { label: string } | null };
type VendorVisit = { id: string; status: string; wish_start?: string | null; wish_end?: string | null; open_count?: number | null; area_label?: string | null };
type BoardRowV = { visit_id: string; vendor_id: string | null; status: string; window: { start: string; end: string; excluded: string[]; instant: boolean } | null };

/** 단가표 줄마다 넣을 값(마루와벽과 비슷한 시험 값, 원 · 부가세 빼고). meal은 '다른 줄에 포함 → 인건비'.
 *  material_hapji(1209 합지 부자재)는 시연 마루와벽과 같은 값 */
const PRICE: Record<string, number | "included"> = {
  putty: 20_000, paper_hapji: 5_000, paper_silk: 9_500, material: 13_000, material_hapji: 6_500, labor: 300_000, meal: "included", truck: 50_000,
};
const PRICE_UNIT: Record<string, string> = {
  putty: "공급면적 1평(3.3㎡)당", paper_hapji: "벽지 1평(3.3㎡)당", paper_silk: "벽지 1평(3.3㎡)당", material: "공급면적 1평(3.3㎡)당",
  material_hapji: "공급면적 1평(3.3㎡)당", labor: "1품(1명 하루)당", meal: "1품당", truck: "1대당",
};

/** "2026-12-13" → "12.13"(rangeText 기본 꼴의 한쪽) */
const md = (iso: string) => `${Number(iso.slice(5, 7))}.${Number(iso.slice(8, 10))}`;
const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
/** "2026-12-13" → "12.13(일)"(dateShort 올해 꼴) */
const dshort = (iso: string) => `${md(iso)}(${WEEK[new Date(`${iso.slice(0, 10)}T00:00:00Z`).getUTCDay()]})`;
const num = (n: number) => n.toLocaleString("ko-KR");

/** 지난달(서울) 'YYYY-MM' — 시공 사례 '찍은 때' */
function lastMonth(): string {
  const [y, m] = todaySeoul().split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
}

/** 관리자 화면(웹 전용)은 폰 프로젝트에서도 넓은 문맥으로 열어요 */
async function adminContext(browser: Browser): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 });
  await loginApi(context, DEMO.admin);
  return { context, page: await context.newPage() };
}

test("J10 업체: 가입 신청 → 보완 → 승인 → 처음 할 일 → 단가 → 첫 실측 요청에 기간 답하기", async ({ page, browser, other }, info) => {
  test.setTimeout(600_000);
  const phone = isPhone(info);
  const stamp = randomUUID().slice(0, 6);
  const biz = `시험도배 ${info.project.name} ${stamp}`;
  const owner = "시험대표";
  const bizNo = `99${String(Date.now()).slice(-8)}`; // 시험용 10자리(실제로 없는 번호)
  const bizNoText = `${bizNo.slice(0, 3)}-${bizNo.slice(3, 5)}-${bizNo.slice(5)}`;
  const email = freshEmail("j10", info.project.name);
  const vendorPhone = `010${String(Date.now()).slice(-8)}`;
  const vendorCtx = page.context();
  const admin = await adminContext(browser);

  try {
    await test.step("V01 업체 가입 신청 · 첫 칸", async () => {
      await page.goto("/signup/vendor");
      await expect(page.getByRole("heading", { name: "업체 가입 신청", level: 1 })).toBeVisible();
      await expect(page.getByText("비밀번호는 다음 칸에서 넣어요")).toBeVisible();
      await expect(page.getByText("관리자가 확인하고, 승인되면 알림으로 알려 드려요.")).toBeVisible();
      const form = page.getByRole("form", { name: "업체 가입 신청" });
      await form.getByLabel("상호").fill(biz);
      await form.getByLabel("대표자").fill(owner);
      await form.getByLabel("사업자등록번호").fill(bizNo);
      await expect(form.getByLabel("사업자등록번호")).toHaveValue(bizNoText);
      await form.getByLabel("이메일").fill(email);
      await expect(form.getByText("사업자등록증", { exact: true })).toBeVisible();
      await expect(form.getByRole("group", { name: "다니는 지역" })).toBeVisible();
      await form.getByLabel("사업자등록증 파일 올리기").setInputFiles(asset("license.pdf"));
      await expect(form.getByText("license.pdf")).toBeVisible();
      await expect(form.getByText("PDF · 사진")).toBeVisible();
      // CF-11: 9판 '하는 공정' → '하는 공사'
      await form.getByRole("group", { name: "하는 공사" }).getByRole("checkbox", { name: "도배", exact: true }).check();
      const gu = form.getByRole("group", { name: "서울 시 · 군 · 구" });
      for (const g of ["노원구", "도봉구"]) await gu.getByRole("checkbox", { name: g, exact: true }).check();
      await expect(form.getByText("고른 지역 2곳")).toBeVisible();
      await expectNoSideScroll(page, "V01 업체 가입 신청");
      await shot(page, "01-V01-signup");
      await shown(page.getByRole("button", { name: "가입 신청" })).first().click();
    });

    await test.step("V01 둘째 칸: 휴대폰 · 비밀번호 · 약관 → 심사 기다림", async () => {
      const form = page.getByRole("form", { name: "업체 가입 신청 · 비밀번호와 약관" });
      await expect(form).toBeVisible();
      const pw = `E2e-${randomUUID().slice(0, 12)}`; // 이 시험에서만 쓰는 값(기록하지 않아요)
      await form.getByLabel("휴대폰").fill(vendorPhone);
      await form.getByLabel("비밀번호", { exact: true }).fill(pw);
      await form.getByLabel("비밀번호 확인").fill(pw);
      await form.getByRole("checkbox", { name: "모두 동의해요" }).check();
      for (const t of ["[필수] 이용약관", "[필수] 개인정보 수집 · 이용"]) await expect(form.getByRole("checkbox", { name: t })).toBeChecked();
      await expectNoSideScroll(page, "V01 둘째 칸");
      await shot(page, "02-V01-step2");
      const sent = page.waitForResponse((r) => r.url().includes("/api/auth/vendor-signup") && r.request().method() === "POST");
      await shown(page.getByRole("button", { name: "가입 신청", exact: true })).last().click();
      expect((await sent).status(), "POST /auth/vendor-signup").toBe(201);
      await page.waitForURL(/\/vendor$/, { timeout: 60_000 });
      await expect(page.getByText("심사 기다림").first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "신청서를 확인하고 있어요" })).toBeVisible();
      const sub = page.getByRole("list", { name: "낸 신청" });
      await expect(sub).toContainText(biz);
      await expect(sub).toContainText(owner);
      await expect(sub).toContainText(bizNoText);
      await expectNoSideScroll(page, "V01 뒤 심사 기다림");
      await shot(page, "03-V01-pending");
    });

    const me = await apiGet<{ id: string; vendor_status?: string | null }>(vendorCtx, "/me");
    expect(me.vendor_status).toBe("pending");
    const vendorId = me.id;

    await test.step("A01 관리자 업체 심사 → 보완 요청(사진이 흐려요)", async () => {
      const ap = admin.page;
      await ap.goto("/admin/vendors");
      await expect(ap.getByRole("heading", { name: "업체 심사", level: 1 })).toBeAttached();
      const table = ap.getByRole("region", { name: /업체 심사 목록/ });
      // CF-66 · CF-11: 표 머리 '신청일 · 상호 · 공사 · 지역 · 상태'
      for (const h of ["신청일", "상호", "공사", "지역", "상태"]) await expect(table.getByRole("columnheader", { name: h, exact: true })).toBeVisible();
      const row = table.getByRole("row").filter({ hasText: biz });
      await expect(row).toContainText("심사 기다림");
      await expect(row).toContainText("노원구 · 도봉구");
      await row.getByRole("link", { name: biz }).click();
      await ap.waitForURL(new RegExp(`/admin/vendors\\?id=${vendorId}`));
      const side = ap.getByRole("complementary", { name: "고른 신청 자세히" });
      await expect(side.getByRole("heading", { name: biz })).toBeVisible();
      await expect(side).toContainText(owner);
      await expect(side).toContainText(bizNoText);
      await expect(side).toContainText("도배 · 노원구 외 1곳");
      await expect(side.getByText("license.pdf")).toBeVisible();
      for (const c of ["상호가 같아요", "등록번호가 같아요", "대표자가 같아요"]) await expect(side.getByRole("checkbox", { name: c })).toBeVisible();
      await expect(side.getByText("업체가 넣은 외부 리뷰 링크 0")).toBeVisible();
      await expect(side.getByLabel("처리 메모")).toBeVisible();
      for (const b of ["거절", "보완 요청", "승인"]) await expect(side.getByRole("button", { name: b, exact: true })).toBeVisible();
      await expectNoSideScroll(ap, "A01 업체 심사(관리자 · 웹 너비)");
      await shot(ap, "04-A01-review");

      await side.getByRole("button", { name: "보완 요청", exact: true }).click();
      const dlg = ap.getByRole("dialog", { name: `${biz}에 보완을 요청할까요?` });
      await expect(dlg.getByText("이유를 하나 골라요 · 업체 화면에 그대로 보여요")).toBeVisible();
      await dlg.getByRole("button", { name: "사진이 흐려서 글자가 안 보여요" }).click();
      await expect(dlg.getByRole("button", { name: "사진이 흐려서 글자가 안 보여요" })).toHaveAttribute("aria-pressed", "true");
      await dlg.getByLabel("업체에 남길 말").fill("등록증 글자가 흐려요. 밝은 곳에서 다시 찍어 올려 주세요.");
      await shot(ap, "05-A01-needinfo-dialog");
      await dlg.getByRole("button", { name: "보완 요청", exact: true }).click();
      await expect(ap.getByText("보완을 요청했어요. 업체에게 알림이 가요.")).toBeVisible();
      await expect(side.getByText(/보완을 요청했어요 · 사진이 흐려서 글자가 안 보여요/)).toBeVisible();
      const d = await apiGet<AdminDetail>(admin.context, `/admin/vendors/${vendorId}`);
      expect(d.status, "관리자 결정 뒤 상태").toBe("needs_info");
    });

    await test.step("V14 보완 요청 → 등록증 사진 다시 올리기(위치 정보 지움) → 다시 보내기", async () => {
      await page.goto("/vendor");
      await expect(page.getByText("보완이 필요해요")).toBeVisible();
      await expect(page.getByRole("heading", { name: "사업자등록증을 다시 올려 주세요" })).toBeVisible();
      await expect(page.getByText("등록증 글자가 흐려요. 밝은 곳에서 다시 찍어 올려 주세요.")).toBeVisible();
      await expect(page.getByText(/관리자가 .+에 남긴 말이에요/)).toBeVisible();
      await expect(page.getByText("다시 올릴 것 · 사업자등록증 파일")).toBeVisible();
      await expect(page.getByText("다른 칸은 그대로 두면 돼요.")).toBeVisible();
      await expect(page.getByText("심사 기록")).toBeVisible();
      expect(hasGpsExif(readFileSync(asset("wall-gps-1.jpg"))), "시험 사진에 위치 정보가 들어 있어야 해요").toBeTruthy();
      const up = page.waitForResponse((r) => r.url().includes("/api/files") && r.request().method() === "POST");
      await page.getByLabel("사업자등록증 파일 올리기").setInputFiles(asset("wall-gps-1.jpg"));
      expect((await up).status(), "POST /files(license)").toBe(201);
      await expect(page.getByText("wall-gps-1.jpg")).toBeVisible();
      await expect(page.getByText("위치 정보 지움")).toBeVisible();
      await expectNoSideScroll(page, "V14 심사 보완 요청");
      await shot(page, "06-V14-needinfo");
      await shown(page.getByRole("button", { name: "다시 보내기" })).first().click();
      await expect(page.getByText("다시 보냈어요. 관리자가 확인하면 알림으로 알려 드려요.")).toBeVisible();
      await expect(page.getByRole("heading", { name: "신청서를 확인하고 있어요" })).toBeVisible();
    });

    await test.step("A01 다시 온 신청 → 등록증 견주기 → 승인(다시 올린 사진에 위치 정보 없음)", async () => {
      const ap = admin.page;
      await ap.reload();
      const side = ap.getByRole("complementary", { name: "고른 신청 자세히" });
      await expect(side.getByRole("heading", { name: biz })).toBeVisible();
      await expect(side.getByText("심사 기다림")).toBeVisible();
      await expect(side.getByText("wall-gps-1.jpg")).toBeVisible();
      await expect(side.getByText("위치 정보 지움")).toBeVisible();
      await expect(side.getByText("업체가 보완해서 다시 보냄")).toBeVisible();
      // 관리자가 '크게'로 여는 등록증 파일: 서버가 지운 뒤라 GPS 칸이 없어요
      const d = await apiGet<AdminDetail>(admin.context, `/admin/vendors/${vendorId}`);
      const file = await admin.context.request.get(`/api/files/${d.license_file_id}`);
      expect(file.ok(), "등록증 파일 열기").toBeTruthy();
      expect(file.headers()["content-type"]).toContain("image/jpeg");
      expect(hasGpsExif(await file.body()), "다시 올린 등록증 사진의 위치 정보").toBeFalsy();
      for (const c of ["상호가 같아요", "등록번호가 같아요", "대표자가 같아요"]) await side.getByRole("checkbox", { name: c }).check();
      await side.getByRole("button", { name: "승인", exact: true }).click();
      await expect(ap.getByText(`${biz} 가입을 승인했어요. 업체에게 알림이 가요.`)).toBeVisible();
      await expect(side.getByText("승인한 업체예요.")).toBeVisible();
      await expect(side.getByRole("list", { name: "처리 기록" })).toContainText("승인");
      await expectNoSideScroll(ap, "A01 승인 뒤(관리자 · 웹 너비)");
      await shot(ap, "07-A01-approved");
      expect((await apiGet<AdminDetail>(admin.context, `/admin/vendors/${vendorId}`)).status).toBe("approved");
    });

    await test.step("V02 승인 · 처음 할 일", async () => {
      await page.goto("/vendor");
      await expect(page.getByText("승인됐어요")).toBeVisible();
      await expect(page.getByRole("heading", { name: /고객에게 보일\s*준비를 해요/ })).toBeVisible();
      await expect(page.getByText("단가를 넣고 확인하면 고객에게 가견적이 보여요.")).toBeVisible();
      const todo = page.getByRole("list", { name: "처음 할 일" });
      for (const t of ["도배 단가 넣기", "업체 정보 · 시공 사례", "외부 리뷰 · 시공 사례 링크", "리뷰 · 답글"]) await expect(todo.getByRole("link", { name: new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) })).toBeVisible();
      await expect(todo).toContainText("견적서 줄마다 단가 · 다른 줄에 포함 · 빼기");
      await expect(todo).toContainText("외부 리뷰 링크는 3개까지 · 관리자가 확인해요");
      await expectNoEnglishState(page, "V02");
      await expectNoSideScroll(page, "V02 처음 할 일");
      await shot(page, "08-V02-first");
    });

    await test.step("V15 업체 정보 · 기본: 연락 방법 · 통화 시간 저장", async () => {
      await page.getByRole("list", { name: "처음 할 일" }).getByRole("link", { name: /업체 정보 · 시공 사례/ }).click();
      await page.waitForURL(/\/vendor\/profile\?tab=basic/);
      await expect(page.getByRole("heading", { name: "업체 정보", level: 1 })).toBeVisible();
      const tabs = page.getByRole("navigation", { name: "업체 정보 탭" });
      await expect(tabs.getByRole("link", { name: "기본" })).toHaveAttribute("aria-current", "page");
      for (const g of ["실측 출장비", "연락 방법", "세금", "다니는 지역"]) await expect(page.getByRole("group", { name: g })).toBeVisible();
      await expect(page.getByRole("group", { name: "다니는 지역" })).toContainText("노원구");
      for (const c of ["전화", "문자", "카카오톡 채널", "홈페이지 상담"]) await expect(page.getByRole("group", { name: "연락 방법" }).getByText(c, { exact: true })).toBeVisible();
      await expect(page.getByLabel("통화 시작")).toHaveValue("09:00");
      await expect(page.getByLabel("통화 끝")).toHaveValue("18:00");
      const intro = page.getByLabel("한 줄 소개");
      if (await intro.count()) await intro.fill("도배만 해요. 이음매를 깔끔하게 맞춰요.");
      await page.getByRole("group", { name: "연락 방법" }).getByRole("radio", { name: "전화", exact: true }).check();
      // '바로 확정' 처음 값은 데이터 모델 기본 false(data-model.md 0025). 켜고 저장해요(기간 답할 때 처음 값)
      const instant = shown(page.getByRole("switch", { name: /고객이 고르면 바로 확정/ })).first();
      await expect(instant).toBeVisible();
      await instant.check();
      await expect(instant).toBeChecked();
      await expectNoSideScroll(page, "V15 업체 정보 · 기본");
      await shot(page, "09-V15-profile");
      // 앞 화면 알림('저장했어요.')이 남아 있을 수 있어서 PUT 응답을 기다려요
      const put = page.waitForResponse((r) => r.url().includes("/api/vendor/profile") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "저장", exact: true }).click();
      expect((await put).ok(), "PUT /vendor/profile").toBeTruthy();
      await expect(page.getByText("저장했어요.").first()).toBeVisible();
      const p = await apiGet<Profile>(vendorCtx, "/vendor/profile");
      expect(p.contact_method, "저장한 연락 방법(고객 목록에 보이는 조건)").toBe("phone");
      expect(p.updated_at).not.toBeNull();
      expect(p.areas.map((a) => a.sgg)).toEqual(expect.arrayContaining(["노원구", "도봉구"]));
    });

    await test.step("V16 업체 정보 · 시공 사례: 사진 한 장 + 공간 · 벽지 · 면적 · 찍은 때", async () => {
      await page.getByRole("navigation", { name: "업체 정보 탭" }).getByRole("link", { name: /^사례/ }).click();
      await page.waitForURL(/tab=cases/);
      await expect(page.getByText("시공 사진 0 / 20")).toBeVisible();
      await expect(page.getByText("사진마다 아래 칸을 적어요.")).toBeVisible();
      const made = page.waitForResponse((r) => r.url().includes("/api/vendor/portfolio") && r.request().method() === "POST");
      await page.getByLabel("시공 사진 올리기").setInputFiles(asset("wall-gps-2.jpg"));
      expect((await made).ok(), "POST /vendor/portfolio").toBeTruthy();
      await expect(page.getByText("시공 사진 1 / 20")).toBeVisible();
      await expect(page.getByText(/^고른 사진 · /)).toBeVisible();
      await page.getByLabel("공간", { exact: true }).selectOption("거실");
      await page.getByLabel("벽지", { exact: true }).selectOption("basic");
      await page.getByLabel("면적", { exact: true }).fill("79.3");
      await page.getByLabel("찍은 때", { exact: true }).fill(lastMonth());
      await expect(page.getByText("고른 사진 · 거실 · 실크")).toBeVisible();
      await expectNoSideScroll(page, "V16 시공 사례");
      await shot(page, "10-V16-cases");
      // 앞 화면 알림('저장했어요.')이 남아 있을 수 있어서 PUT 응답을 기다려요
      const put = page.waitForResponse((r) => r.url().includes("/api/vendor/profile") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "저장", exact: true }).click();
      expect((await put).ok(), "PUT /vendor/profile").toBeTruthy();
      await expect(page.getByText("저장했어요.").first()).toBeVisible();
      const p = await apiGet<Profile>(vendorCtx, "/vendor/profile");
      expect(p.portfolio.length).toBe(1);
      expect(p.portfolio[0].space).toBe("거실");
      expect(p.portfolio[0].paper).toBe("basic");
      expect(Number(p.portfolio[0].area_m2)).toBe(79.3);
    });

    await test.step("V18 업체 정보 · 링크: 외부 리뷰 링크 하나 → 확인 중", async () => {
      await page.getByRole("navigation", { name: "업체 정보 탭" }).getByRole("link", { name: "링크" }).click();
      await page.waitForURL(/tab=links/);
      await expect(page.getByText("외부 리뷰 링크 0 / 3")).toBeVisible();
      await expect(page.getByText("시공 사례 링크 0 / 5")).toBeVisible();
      await expect(page.getByText("관리자가 링크가 이 업체 것인지 확인하면 고객 화면에 보여요.")).toBeVisible();
      await page.getByRole("button", { name: "외부 리뷰 링크 넣기" }).click();
      await page.getByLabel("이름").fill("지도 리뷰(시험)");
      await page.getByLabel("주소").fill("https://example.com/e2e/place");
      await page.getByRole("button", { name: "저장", exact: true }).click();
      await expect(page.getByText("저장했어요. 바뀐 외부 리뷰 링크는 관리자가 확인하면 보여요.")).toBeVisible();
      const links = await apiGet<ReviewLink[]>(vendorCtx, "/vendor/review-links");
      expect(links.map((l) => [l.url, l.status])).toEqual([["https://example.com/e2e/place", "checking"]]);
      await page.reload();
      await expect(page.getByText("외부 리뷰 링크 1 / 3")).toBeVisible();
      await expect(page.getByText("관리자가 보는 중이에요")).toBeVisible();
      await expect(page.getByText("확인 중", { exact: true })).toBeVisible();
      await expectNoSideScroll(page, "V18 링크");
      await shot(page, "11-V18-links");
    });

    let saved: PricesV3 | null = null;
    await test.step("D02 도배 단가(1201~1209): 10배 경고 → 고쳐서 확인하고 저장 = 계산 엔진 값", async () => {
      await page.goto("/vendor/profile");
      await page.getByRole("list", { name: "처음 할 일" }).getByRole("link", { name: /도배 단가 넣기/ }).click();
      await page.waitForURL(/\/vendor\/prices\/dobae$/);
      const before = (await apiGet<{ v3: PricesV3 | null }>(vendorCtx, "/vendor/prices?trade=dobae")).v3;
      expect(before, "GET /vendor/prices v3").not.toBeNull();
      await expect(page.getByRole("heading", { name: "도배 단가", level: 1 })).toBeVisible();
      await expect(page.getByText("부가세 빼고 원 단위로 넣어요 · 고객에게는 집마다 업체 단가 × 믿집 수량으로 보여요")).toBeVisible();
      await expect(page.getByText(`${before!.example_home}이면`).first()).toBeAttached();
      const rows = page.getByRole("list", { name: "도배 단가 줄" }).getByRole("listitem");
      await expect(rows).toHaveCount(before!.lines.length);
      // 부자재는 벽지마다 따로(1205 실크 · 1209 합지, 2026-11-21)
      expect(before!.lines.map((r) => r.code)).toEqual(["1201", "1203", "1204", "1205", "1209", "1206", "1207", "1208"]);

      for (const r of before!.lines) {
        const want = PRICE[r.key];
        const unit = PRICE_UNIT[r.key] ?? `${r.unit}당`;
        const group = page.getByRole("group", { name: `${r.code} ${r.name} 받는 법` });
        if (want === "included") {
          await group.getByRole("radio", { name: "다른 줄에 포함", exact: true }).check();
          await expect(page.getByLabel(`${r.code} ${r.name} · 어느 줄에 포함`)).toHaveValue("labor");
          continue;
        }
        await group.getByRole("radio", { name: "단가", exact: true }).check();
        await page.getByLabel(`${r.code} ${r.name} 단가 · ${unit}`).fill(String(want));
      }
      // 10배 경고(L01): API 기준 값(warn_high)보다 크면 칸 아래에 경고가 떠요
      const labor = before!.lines.find((r) => r.key === "labor")!;
      const laborField = page.getByLabel(`${labor.code} ${labor.name} 단가 · ${PRICE_UNIT.labor}`);
      await laborField.fill("2800000");
      await expect(laborField).toHaveValue("2,800,000");
      if (labor.warn_high != null && 2_800_000 > labor.warn_high) {
        await expect(page.getByText("기준 단가의 10배쯤이에요. 0을 더 넣지 않았나요?")).toBeVisible();
      } else {
        info.annotations.push({ type: "확인 못 함", description: `D02 인건비 warn_high가 API에 없어요(${labor.warn_high ?? "null"}) → 10배 경고는 저장 뒤 값에만 붙어요` });
      }
      await shot(page, "12-D02-warn");
      await laborField.fill(String(PRICE.labor));
      await expect(page.getByText("기준 단가의 10배쯤이에요. 0을 더 넣지 않았나요?")).toHaveCount(0);
      await expect(page.getByText("인건비에 포함").first()).toBeVisible();
      await expect(page.getByText("저장하면 고객에게 바로 보여요. 이미 요청한 고객 값은 그대로예요.")).toBeVisible();
      const confirm = page.waitForResponse((r) => r.url().includes("/api/vendor/prices/dobae/confirm") && r.request().method() === "POST");
      await page.getByRole("button", { name: "확인하고 저장" }).click();
      expect((await confirm).ok(), "POST /vendor/prices/dobae/confirm").toBeTruthy();
      await expect(page.getByText("단가를 확인하고 저장했어요. 고객에게 바로 보여요.")).toBeVisible();

      const got = (await apiGet<{ v3: PricesV3 }>(vendorCtx, "/vendor/prices?trade=dobae")).v3;
      saved = got;
      expect(got.confirmed_at, "확인한 단가 묶음").not.toBeNull();
      expect(got.example, "예시 집 가견적").not.toBeNull();
      expect(got.example!.supply + got.example!.vat).toBe(got.example!.total);
      // 아래 띠: '공급 69.4㎡ 집 가견적 · 부가세 포함' = 계산 엔진 값(만 단위 글)
      await expect(page.getByText(`${got.example_home} 가견적 · 부가세 포함`)).toBeVisible();
      await expect(page.getByText(won(got.example!.total), { exact: true })).toBeVisible();
      // 단가 줄마다 '이 집이면' 금액 = API 줄 금액
      for (const r of got.lines.filter((x) => x.mode === "price")) {
        await expect(page.getByText(num(r.example_amount), { exact: true }).first(), `${r.code} ${r.name} 예시 금액`).toBeVisible();
      }
      await expectNoEnglishState(page, "D02");
      await expectNoSideScroll(page, "D02 도배 단가");
      await shot(page, "13-D02-saved");
    });

    // 고객(김처음, 공급 69.4㎡ · 실크 · 빈 집 · 전체 = 단가표 예시 집과 같은 조건)이 API로 담고 실측을 요청해요
    const cust = await other(DEMO.c01);
    let visitId = "";
    let wish = { start: "", end: "" };
    await test.step("고객(API): 새 업체 가견적 → 담기 → 실측 요청", async () => {
      const proj = await myProject(cust.context);
      const list = await apiGet<{ local: VendorCard[] }>(cust.context, `/projects/${proj.id}/vendors?trade=dobae`);
      const card = list.local.find((c) => c.vendor_id === vendorId);
      expect(card, "고객 업체 목록에 새 업체가 보여요(승인 + 연락 방법 + 단가 확인)").toBeTruthy();
      expect(card!.state).toBe("ok");
      expect(card!.estimate_total).not.toBeNull();
      // 같은 집 조건이면 고객 가견적 = 단가표 '공급 69.4㎡ 집' 가견적(둘 다 계산 엔진)
      expect.soft(card!.estimate_total, "고객 가견적 = D02 예시 집 가견적").toBe(saved?.example?.total);
      await apiSend(cust.context, "POST", `/projects/${proj.id}/shortlist`, { trade: "dobae", vendor_id: vendorId });
      const draft = await apiGet<{ wish_start: string | null; wish_end: string | null; vendors: { vendor_id: string }[] }>(cust.context, `/projects/${proj.id}/visits/draft?trade=dobae`);
      expect(draft.vendors.map((v) => v.vendor_id)).toContain(vendorId);
      wish = { start: draft.wish_start ?? addDays(todaySeoul(), 20), end: draft.wish_end ?? addDays(todaySeoul(), 34) };
      const out = await apiSend<{ created: { id: string; vendor_id: string }[]; failed: unknown[] }>(cust.context, "POST", `/projects/${proj.id}/visits`, {
        trade: "dobae", vendor_ids: [vendorId], wish_start: wish.start, wish_end: wish.end, photo_file_ids: [],
      });
      expect(out.failed, "보내지 못한 업체").toEqual([]);
      visitId = out.created.find((v) => v.vendor_id === vendorId)!.id;
      expect(visitId).toBeTruthy();
    });

    await test.step("V03 · D04 작업함: 새 실측 요청", async () => {
      await page.goto("/vendor");
      const rows = await apiGet<{ items: InboxRow[] }>(vendorCtx, "/vendor/visits?tab=todo");
      const row = rows.items.find((r) => r.id === visitId);
      expect(row, "작업함 할 일에 새 요청").toBeTruthy();
      const tabs = shown(page.getByRole("navigation", { name: "작업함 탭" })).first();
      for (const t of ["할 일", "기다림", "일정", "공사", "끝남"]) await expect(tabs.getByRole("link", { name: new RegExp(`^${t}`) })).toBeVisible();
      await expect(tabs.getByRole("link", { name: /^할 일/ })).toContainText("1");
      const label = row!.state?.label ?? "새 실측 요청";
      await expect(shown(page.getByText(label, { exact: true })).first()).toBeVisible();
      if (row!.area_label) await expect(shown(page.getByText(row!.area_label)).first()).toBeVisible();
      if (row!.estimate_total != null) await expect(shown(page.getByText(new RegExp(won(row!.estimate_total)))).first()).toBeVisible();
      await expect(shown(page.getByText("다음 할 일")).first()).toBeVisible();
      // 9판 '위치는 동까지만 …' → 지금 코드(LOC_NOTE) 글
      await expect(shown(page.getByText("위치는 동네(구 · 동)까지만 보여요. 동 · 호수 · 연락처는 고객이 채팅으로 알려 줘요.")).first()).toBeVisible();
      await expectNoEnglishState(page, phone ? "V03" : "D04");
      await expectNoSideScroll(page, phone ? "V03 작업함" : "D04 작업함");
      await shot(page, "14-V03-inbox");
      await shown(page.getByRole("link", { name: "기간 답하기" })).first().click();
      await page.waitForURL(new RegExp(`/vendor/requests/${visitId}$`));
    });

    await test.step("V04 · D14 기간 답하기 → 보내기 → 고객 '날짜 고를 차례'", async () => {
      await expect(page.getByRole("heading", { name: "기간 답하기", level: 1 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "갈 수 있는 기간" })).toBeVisible();
      const legend = page.getByRole("list", { name: "달력 표시" });
      for (const t of ["고객 희망", "고른 기간", "잡힌 반나절", "빼는 날"]) await expect(legend).toContainText(t);
      await expect(page.getByText("시작 · 끝을 누르고, 안 되는 날은 한 번 더 눌러요.")).toBeVisible();
      await expect(shown(page.getByText("고객이 7일 안에 고르지 않으면 이 기간이 풀려 다른 요청에 다시 열려요.")).first()).toBeVisible();
      // 고객 희망: 폰은 한 줄 요약(V04 '고객 희망 12.7~12.21'), 웹은 요약 칸(D14 '고객 희망 · 12.7(월)~12.21(월)')
      if (phone) await expect(page.getByText(`고객 희망 ${md(wish.start)}~${md(wish.end)}`)).toBeVisible();
      else await expect(page.getByText(`${dshort(wish.start)}~${dshort(wish.end)}`).first()).toBeVisible();
      const sw = shown(page.getByRole("switch", { name: /고객이 고르면 바로 확정/ })).first();
      await expect(sw).toBeChecked();

      // 고객 희망 안에서 6일 · 하루 빼기(9판 12.13~12.18, 16일 빼고와 같은 모양)
      const start = addDays(wish.start, 6);
      const end = addDays(wish.start, 11);
      const off = addDays(wish.start, 9);
      const cal = page.getByRole("group", { name: "갈 수 있는 기간 고르기" });
      await pickDay(cal, start);
      await pickDay(cal, end);
      await pickDay(cal, off);
      await expect(cal.getByRole("button", { name: /빼는 날/ })).toHaveCount(1);
      const send = shown(page.getByRole("button", { name: `${md(start)}~${md(end)} 보내기` })).first();
      await expect(send).toBeVisible();
      await expect(shown(page.getByRole("button", { name: "못 받아요", exact: true })).first()).toBeVisible();
      if (!phone) {
        // D14 오른쪽 '보낼 기간': 고객이 고를 수 있는 반나절 수 = 계산 엔진(open_count)
        const qs = new URLSearchParams({ start, end });
        qs.append("excluded", off);
        const pre = await apiGet<VendorVisit>(vendorCtx, `/vendor/visits/${visitId}?${qs.toString()}`);
        expect(pre.open_count, "open_count").not.toBeNull();
        await expect(page.getByText(`${Number(off.slice(8, 10))}일 빼고 · 고객이 고를 수 있는 반나절 ${pre.open_count}칸`)).toBeVisible();
      }
      await expectNoSideScroll(page, phone ? "V04 기간 답하기" : "D14 기간 답하기");
      await shot(page, "15-V04-period");
      const answered = page.waitForResponse((r) => r.url().includes(`/api/vendor/visits/${visitId}/window`) && r.request().method() === "POST");
      await send.click();
      expect((await answered).ok(), "POST /vendor/visits/{vid}/window").toBeTruthy();
      await expect(page.getByText("기간을 보냈어요. 고객이 날짜를 고르면 알림으로 알려 드려요.")).toBeVisible();
      await page.waitForURL(/\/vendor\?tab=waiting/);
      const waiting = await apiGet<{ items: InboxRow[] }>(vendorCtx, "/vendor/visits?tab=waiting");
      const w = waiting.items.find((r) => r.id === visitId);
      expect(w, "기다림 탭으로 옮겨요").toBeTruthy();
      await expect(shown(page.getByText(w!.state?.label ?? "고객 차례", { exact: true })).first()).toBeVisible();
      await expectNoSideScroll(page, "V04 뒤 작업함 기다림");
      await shot(page, "16-V04-sent");

      // 고객 쪽: 그 업체 줄이 '날짜 고를 차례'(offered)이고 기간 · 빼는 날 · 바로 확정이 보낸 값과 같아요
      const proj = await myProject(cust.context);
      const b = (await apiGet<{ board: BoardRowV[] }>(cust.context, `/projects/${proj.id}/visits`)).board.find((r) => r.visit_id === visitId);
      expect(b?.status).toBe("offered");
      expect(b?.window).toMatchObject({ start, end, excluded: [off], instant: true });
    });
  } finally {
    await admin.context.close().catch(() => {});
  }
});

// /account — 내 정보(C45 고객 · 업체 같이). 이름 · 이메일 · 휴대폰(고객만, 가려서) · 비밀번호 · 알림(목록으로) · 도움말.
// 로그아웃 · 탈퇴(C53, 비밀번호를 다시 받아요). 비밀번호 바꾸기는 C46(/reset-password, B2 화면)으로 가요.
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { TabBar } from "@/components/site/TabBar";
import { LogoutButton } from "@/components/my/AccountButtons";
import { WithdrawSheet } from "@/components/my/WithdrawSheet";
import { Group, Name, Row, Rows, Sub } from "@/components/project/Kit";
import { listMyProjectsV3 } from "@/lib/api/schedule";
import { projectName } from "@/lib/guest/info";
import { phoneText } from "@/lib/labels";
import { requireRoleV3b as requireRole } from "@/lib/mock/v3b/session";
import s from "@/components/my/account2.module.css";

export const metadata = { title: "내 정보" };

/** '010-****-5678'(보이기만 가려요. 저장된 번호는 그대로예요) */
function masked(phone: string): string {
  const t = phoneText(phone);
  const m = /^(\d{3})-(\d{3,4})-(\d{4})$/.exec(t);
  return m ? `${m[1]}-${"*".repeat(m[2].length)}-${m[3]}` : t;
}

export default async function AccountPage() {
  const me = await requireRole(["customer", "vendor"], "/account");
  const vendor = me.role === "vendor";
  // 탈퇴 창(C53)에 진행 중인 공사를 '상계동 아파트 도배 · 지금 할 일' 꼴로 보여요(고객만)
  const ongoing = vendor ? [] : ((await listMyProjectsV3().catch(() => [])) ?? [])
    .filter((x) => x.phase !== "done")
    .map((x) => [projectName(x.emd, x.region, x.trades), x.todo?.text].filter(Boolean).join(" · "));
  return (
    <>
      <AppHeader phone={{ title: "내 정보" }} />
      <Main narrow>
        <PageHead title="내 정보" />
        <Group>
          <Name as="h2">{me.name} 님</Name>
          <Sub>{me.email}</Sub>
        </Group>
        <Group list>
          <Rows>
            {vendor ? null : (
              <Row label="휴대폰" sub={me.phone ? masked(me.phone) : undefined} value={me.phone ? undefined : "넣기"} valueSub href="/account/phone" />
            )}
            <Row label="비밀번호 바꾸기" href="/reset-password" />
            <Row label="알림" href="/notifications" />
          </Rows>
        </Group>
        <Group list>
          <Rows>
            {vendor ? null : <Row label="믿집 백과" href="/guide" />}
            <Row label="자주 묻는 질문" href="/faq" />
            <Row label="약관 · 개인정보 처리방침" href="/legal" />
          </Rows>
        </Group>
        <div className={s.foot}>
          <LogoutButton />
          <WithdrawSheet vendor={vendor} ongoing={ongoing} />
        </div>
      </Main>
      <TabBar />
    </>
  );
}

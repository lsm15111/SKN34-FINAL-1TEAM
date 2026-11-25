// v5 사본: 메뉴 · 탭 · 로고 주소는 components/v5/site/nav.ts예요(홈 · 인테리어 받기 · 내 공사는 /v5, 나머지는 dev 주소).
// 머리 모양(design-system 3.1 AppHeader · 9판 k-hd · k-nav). 로그인한 사람(session)을 받아 역할별 머리를 그려요.
// 서버(AppHeader · SiteHeader)와 브라우저(app/error.tsx) 양쪽에서 쓰므로 서버 전용 코드를 넣지 않아요.
// - 웹(≥768): 로고 + 역할 메뉴 + 오른쪽 '알림 n'(펼침) · '이름 ▾'(손님은 '로그인')
// - 폰(<768): phone을 주면 뒤로형 · 닫기형(‹ · × + 제목 + 오른쪽 단추 하나), 안 주면 로고형. 폰 길 찾기는 아래 탭 바(TabBar)가 해요.
// - legacy: 옛 화면(SiteHeader)만. 폰에 종 + '메뉴' 펼침을 그대로 둬요(아래 탭 바가 없는 화면이라서).
import Link from "next/link";
import type { ReactNode } from "react";
import type { Session } from "@/lib/types";
import { Icon } from "@/components/ui/Icon";
import { AccountMenu } from "@/components/site/AccountMenu";
import { Bell } from "@/components/site/Bell";
import { MobileMenu } from "@/components/site/MobileMenu";
import { NavLinks } from "./NavLinks";
import { NotifyBell } from "@/components/site/NotifyBell";
import { LOGO_HREF, LOGO_TAG, accountLabel, vendorLock, type HeaderKind } from "./nav";
import s from "@/components/site/header.module.css";

export type PhoneHeader = {
  /** 폰 머리 제목(18/700). 웹에서는 PageHead가 같은 제목을 보여요 */
  title: string;
  /** ‹ 뒤로 갈 곳. 앱 모드에는 브라우저 뒤로 단추가 없어서 첫 화면 말고는 늘 둬요 */
  back?: string;
  /** × 닫기형(back 대신) */
  close?: string;
  /** 오른쪽 단추 하나(예: AsideOpenButton 'AI에게 묻기' · Menu ⋯) */
  action?: ReactNode;
  /** 제목 앞 작은 얼굴(채팅 상대) */
  lead?: ReactNode;
  /** 사진 크게 보기 */
  dark?: boolean;
};

/** pending: 누가 로그인했는지 아직 모를 때(오류 화면) 로고만 그려요. only: 레이아웃이 반쪽만 그릴 때 */
export function HeaderBar({ session, admin = false, unread = 0, pending = false, phone, only, legacy = false, sticky = true, loginHref = "/login" }: {
  session: Session | null;
  admin?: boolean;
  unread?: number;
  pending?: boolean;
  phone?: PhoneHeader;
  only?: "web" | "phone";
  legacy?: boolean;
  sticky?: boolean;
  /** v5: 로그인 주소(돌아올 곳 next= 포함) */
  loginHref?: string;
}) {
  const kind: HeaderKind = admin ? "admin" : session ? session.role : "guest";
  const tag = LOGO_TAG[kind];
  const account = session && kind !== "guest" ? { label: accountLabel({ name: session.name, role: kind }), role: kind } : null;
  const lock = kind === "vendor" ? vendorLock(session?.vendorStatus) : null;
  const bell = kind === "customer" || kind === "vendor";
  const cls = [s.header, sticky ? s.sticky : null, phone?.dark ? s.dark : null, only === "web" ? s.onlyWeb : null, only === "phone" ? s.onlyPhone : null].filter(Boolean).join(" ");

  const logo = (cn: string) => (
    <Link href={LOGO_HREF[kind]} className={cn}>믿집{tag ? <small>{tag}</small> : null}</Link>
  );

  return (
    <header className={cls} data-mj-header="">
      {only === "phone" ? null : (
        <div className={s.web}>
          <div className={s.webIn}>
            {logo(s.logo)}
            {pending ? null : (
              <>
                <nav aria-label="주 메뉴" className={s.nav}><NavLinks kind={kind} lock={lock} /></nav>
                <div className={s.right}>
                  {bell ? <NotifyBell unread={unread} /> : null}
                  {account ? <AccountMenu label={account.label} role={account.role} /> : <Link href={loginHref} className={s.login}>로그인</Link>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
      {only === "web" ? null : (
        <div className={s.phone}>
          {phone ? (
            <>
              {phone.back || phone.close ? (
                <Link href={(phone.back ?? phone.close)!} className={s.pback} aria-label={phone.close ? "닫기" : "뒤로"}>
                  <Icon name={phone.close ? "close" : "back"} size={phone.close ? 24 : 26} />
                </Link>
              ) : <span className={s.pspace} aria-hidden="true" />}
              {phone.lead}
              <p className={s.ptitle}>{phone.title}</p>
              {phone.action ? <div className={s.pact}>{phone.action}</div> : null}
            </>
          ) : (
            <>
              {logo(s.plogo)}
              {pending ? null : legacy ? (
                <div className={s.pact}>
                  {bell ? <Bell unread={unread} /> : null}
                  <MobileMenu kind={kind} account={account} lock={lock} />
                </div>
              ) : kind === "guest" ? (
                <Link href={loginHref} className={s.plogin}>로그인</Link>
              ) : null}
            </>
          )}
        </div>
      )}
    </header>
  );
}

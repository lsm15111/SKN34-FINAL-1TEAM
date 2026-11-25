"use client";
// v5 사본: 메뉴 · 탭 · 로고 주소는 components/v5/site/nav.ts예요(홈 · 인테리어 받기 · 내 공사는 /v5, 나머지는 dev 주소).
// 머리 주 메뉴 링크. 지금 보는 화면에 aria-current="page"를 붙여요.
// lock: 승인 전 업체면 작업함 · 채팅을 잠그고(누를 수 없음) 잠금 문구를 옆에 둬요.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/Icon";
import { NAV, VENDOR_LOCKED, isCurrent, type HeaderKind } from "./nav";
import s from "@/components/site/header.module.css";

export function LockMark() {
  return <Icon name="lock" size={14} />;
}

export function NavLinks({ kind, className, lock }: { kind: HeaderKind; className?: string; lock?: string | null }) {
  const path = usePathname() ?? "";
  return (
    <>
      {NAV[kind].map((l) =>
        lock && VENDOR_LOCKED.includes(l.id) ? (
          <a key={l.id} role="link" aria-disabled="true" aria-describedby="nav-lock" className={[className, s.locked].filter(Boolean).join(" ")}><LockMark />{l.label}</a>
        ) : (
          <Link key={l.id} href={l.href} className={className} aria-current={isCurrent(l, path) ? "page" : undefined}>{l.label}</Link>
        ),
      )}
      {lock ? <span id="nav-lock" className={s.lockMsg} title={lock}>{lock}</span> : null}
    </>
  );
}

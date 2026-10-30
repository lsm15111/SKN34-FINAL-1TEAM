"use client";
// 헤더 오른쪽 위 계정 아이콘. 누르면 누구로 들어왔는지(이름 · 이메일)와 갈 곳, 로그아웃이 나온다.
// 고객 · 업체: 내 정보 · 설정 (내 프로젝트 · 업체 홈은 헤더 메뉴에 있어서 두지 않는다). 관리자: 관리자 화면.
// 펼침 버튼(disclosure) 방식: Esc나 바깥을 누르면 닫히고, 닫히면 초점이 아이콘으로 돌아온다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { call } from "@/lib/backend/client";
import type { Role } from "@/lib/types";

type Item = { href: string; label: string };
const ITEMS: Record<Role, { group?: string; items: Item[] }> = {
  customer: { items: [{ href: "/account", label: "내 정보 · 설정" }] },
  vendor: { items: [{ href: "/account", label: "내 정보 · 설정" }] },
  admin: { items: [{ href: "/admin/members", label: "관리자 화면" }] },
};

export function AccountMenu({ name, email, role }: { name: string; email: string; role: Role }) {
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = ITEMS[role];

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function logout() {
    // 서버 세션을 지우고 쿠키도 API가 지운다. 연결이 안 돼도 화면은 홈으로 보낸다.
    await call("POST", "/auth/logout").catch(() => undefined);
    setOpen(false);
    router.push("/");
    router.refresh();
  }

  return (
    <div ref={box} className="mj-acct">
      <button ref={btn} type="button" className="mj-acct-btn" aria-label={`내 계정 · ${name}`} aria-expanded={open} aria-controls="acct-menu" onClick={() => setOpen((v) => !v)}>
        <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="8.5" r="3.8" /><path d="M4.5 20c1.4-3.6 4.2-5.4 7.5-5.4s6.1 1.8 7.5 5.4" /></svg>
      </button>
      <div id="acct-menu" className="mj-acct-menu" hidden={!open}>
        <div className="mj-acct-who"><b>{name}</b><span>{email}</span></div>
        {menu.group ? <div className="mj-acct-group" id="acct-group">{menu.group}</div> : null}
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }} aria-labelledby={menu.group ? "acct-group" : undefined}>
          {menu.items.map((it) => (
            <li key={it.href}><Link href={it.href} aria-current={path === it.href ? "page" : undefined} onClick={() => setOpen(false)}>{it.label}</Link></li>
          ))}
        </ul>
        <div className="mj-acct-sep" />
        <button type="button" onClick={logout}>로그아웃</button>
      </div>
    </div>
  );
}

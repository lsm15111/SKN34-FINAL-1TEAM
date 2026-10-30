"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function NavLinks({ links }: { links: { href: string; label: string }[] }) {
  const path = usePathname();
  return (
    <>
      {links.map((l) => {
        const on = path === l.href || path.startsWith(l.href + "/") || (l.href === "/my" && path.startsWith("/projects"));
        return <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}>{l.label}</Link>;
      })}
    </>
  );
}

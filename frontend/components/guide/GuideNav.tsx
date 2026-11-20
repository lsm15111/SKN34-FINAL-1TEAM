// 글 왼쪽 목록(웹 ≥1024)과 폰 아래 '백과 글 더 보기'. 있는 글만 보여요.
import Link from "next/link";
import { NAV_GROUPS, articleBySlug, articleHref } from "@/lib/guide";
import s from "./guide.module.css";

export function GuideNav({ current }: { current?: string }) {
  return (
    <nav className={s.navBox} aria-label="백과 글 목록">
      {NAV_GROUPS.map((g) => {
        const items = g.slugs.map((x) => articleBySlug(x)).filter((a) => a !== undefined);
        if (!items.length) return null;
        return (
          <div key={g.title}>
            <h2>{g.title}</h2>
            <ul>
              {items.map((a) => (
                <li key={a.slug}><Link href={articleHref(a.slug)} aria-current={a.slug === current ? "page" : undefined}>{a.title}</Link></li>
              ))}
            </ul>
          </div>
        );
      })}
      <div>
        <h2>더 보기</h2>
        <ul>
          <li><Link href="/guide/steps">믿집으로 하는 순서</Link></li>
          <li><Link href="/guide/terms">용어 사전</Link></li>
          <li><Link href="/faq">자주 묻는 질문</Link></li>
        </ul>
      </div>
    </nav>
  );
}

// 내 공사 화면 위 이동 경로: 내 공사 › 지역 · 공정 › 화면 이름 (시안 WStandard · WPlan)
import Link from "next/link";
import s from "@/components/project/ProjectCrumb.module.css";

export function ProjectCrumb({ id, title, here }: { id: string; title: string; here: string }) {
  return (
    <nav className={`mj-wrap mj-crumb ${s.crumb}`} aria-label="이동 경로">
      <ol>
        <li><Link href="/v5/my">내 공사</Link><span aria-hidden="true">›</span></li>
        <li><Link href={`/v5/projects/${id}`}>{title}</Link><span aria-hidden="true">›</span></li>
        <li><span aria-current="page">{here}</span></li>
      </ol>
    </nav>
  );
}

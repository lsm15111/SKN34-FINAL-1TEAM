import Link from "next/link";
import { notFound } from "next/navigation";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import { StandardDoc } from "@/components/project/StandardDoc";
import { getMyProject } from "@/lib/api/project";
import { getStandard } from "@/lib/api/quote";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import s from "./page.module.css";

export const metadata = { title: "표준견적서" };

// 막 계산하고 왔을 때 맨 위 한 줄 (?done=)
const DONE: Record<string, string> = {
  new: "넣은 집 정보로 계산했어요.",
  newPhoto: "넣은 집 정보 · 사진으로 계산했어요.",
  edit: "고친 집 정보로 다시 계산했어요.",
  economy: "도배 저가형으로 다시 계산했어요.",
};

export default async function StandardPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ done?: string; trade?: string }> }) {
  const { id } = await params;
  const { done, trade } = await searchParams;
  const [p, q] = await Promise.all([getMyProject(id), getStandard(id)]);
  if (!p || !q) notFound();
  const title = projectTitle(p.region, TRADE_ORDER.filter((t) => p.trades[t]));
  // 업체 고르기의 '표준견적서 보기'로 왔으면(?trade=) 그 공정 업체 고르기로 돌아가는 버튼을 둔다
  const back = (trade === "dobae" || trade === "mokgong") && p.trades[trade] ? trade : null;
  const notice = done === "new" ? DONE[p.photos.length || p.plans.length ? "newPhoto" : "new"] : done === "edit" || done === "economy" ? DONE[done] : undefined;

  return (
    <main id="main">
      <ProjectCrumb id={id} title={title} here="표준견적서" />
      <div className={`mj-wrap ${s.layout}`}>
        {notice ? <p className={`mj-notice ${s.done}`} role="status"><span>{notice}</span></p> : null}
        <StandardDoc p={p} q={q} title={title} />
        <aside className={s.side} aria-label="다음 할 일">
          <div className={s.next}>
            {back ? (
              <Link className="mj-btn mj-btn-pri" href={`/projects/${id}/vendors?trade=${back}`}>{tradeLabel(back)} 업체 고르기로 돌아가기</Link>
            ) : (
              <Link className="mj-btn mj-btn-pri" href={`/projects/${id}/vendors`}>업체 고르기</Link>
            )}
            <p><Link className="mj-lnk" href={`/projects/${id}/plan`}>예상 공정표 보기</Link></p>
          </div>
          <div className={s.change}>
            <h2 className={s.changeT}>이 금액이 바뀌는 경우</h2>
            <ul>
              <li>
                면적 · 공간 · 도배 유형을 바꾸면 다시 계산해요. 실측을 요청한 뒤에는 바꿀 수 없어요.
                {p.locked ? null : <><br /><Link className={`mj-lnk ${s.small}`} href={`/start?edit=${id}`}>집 정보 고치기</Link></>}
              </li>
            </ul>
          </div>
        </aside>
      </div>
    </main>
  );
}

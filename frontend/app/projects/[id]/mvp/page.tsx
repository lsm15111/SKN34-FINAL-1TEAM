import { notFound } from "next/navigation";
import { MvpBoard } from "@/components/mvp/MvpBoard";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import { getMyProject } from "@/lib/api/project";
import { getMvpMaterials, getMvpPlans } from "@/lib/api/mvp";
import { projectTitle, TRADE_ORDER } from "@/lib/labels";

export const metadata = { title: "도면 · 자재로 견적 보기" };

// 표준견적서를 도면 수량 · 고른 목공 자재로 더 자세히 보고, 업체 견적이 보통 어느 범위인지 함께 본다.
// 저장하지 않는 미리 보기다. 숫자는 모두 API(계산 엔진)가 만든다.
export default async function MvpPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [p, plans, materials] = await Promise.all([getMyProject(id), getMvpPlans(), getMvpMaterials()]);
  if (!p || !plans || !materials) notFound();
  const title = projectTitle(p.region, TRADE_ORDER.filter((t) => p.trades[t]));

  return (
    <main id="main">
      <ProjectCrumb id={id} title={title} here="도면 · 자재로 견적 보기" />
      <div className="mj-wrap">
        <h1 className="mj-h1">도면 · 자재로 견적 보기</h1>
        <p className="mj-sub">
          비슷한 평면도와 목공 자재를 고르면 표준견적서를 더 자세히 다시 계산해요. 업체 견적이 보통 어느 범위인지도 같이 보여 드려요. 고른 값은 저장하지 않아요.
        </p>
        <MvpBoard projectId={id} dobaeGrade={p.trades.dobae?.grade ?? null} hasMokgong={Boolean(p.trades.mokgong)} plans={plans} materials={materials} />
      </div>
    </main>
  );
}

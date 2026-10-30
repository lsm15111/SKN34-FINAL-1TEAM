import { notFound } from "next/navigation";
import { NotConnected } from "@/components/project/RealProjectHub";
import { gradeLabel } from "@/lib/labels";
import { getProject, isDemoProject } from "@/lib/api/project";
import { listAllVendors } from "@/lib/api/vendor";
import { RequestConfirm } from "@/components/vendors/RequestConfirm";
import { md } from "@/lib/format";

export const metadata = { title: "가견적 요청 확인" };

export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isDemoProject(id)) return <NotConnected id={id} />;
  const p = await getProject(id);
  if (!p) notFound();
  const vendors = (await listAllVendors()).map((v) => ({ id: v.id, name: v.name, response: v.response }));
  const unit = p.complex.types.find((t) => t.id === p.unitTypeId);
  const spaceName = (sid: string) => p.spaces.find((s) => s.id === sid)?.name ?? sid;
  const conditions = [
    { k: "집", v: `${p.complex.name} · ${unit?.py}평형 · 공급 ${p.area.supply} / 전용 ${p.area.jeon}㎡ · ${p.builtYear}년 준공${p.balconyExt ? " · 발코니 확장" : ""}` },
    { k: "시기 · 집 상태", v: `${p.startPlan.date ? `${md(p.startPlan.date)}부터` : "미정"} · ${p.occupied ? "살면서 공사" : "빈집"}` },
    ...(p.trades.dobae ? [{ k: "도배", v: `${p.trades.dobae.spaces.map(spaceName).join(", ")} · ${gradeLabel(p.trades.dobae.grade)}` }] : []),
    ...(p.trades.mokgong ? [{ k: "목공", v: `${p.trades.mokgong.spaces.map(spaceName).join(", ")} · ${p.trades.mokgong.items.join(", ")}` }] : []),
    { k: "사진 · 도면", v: `${p.photos.map((x) => x.name).join(", ") || "없음"} · ${p.floorPlan ? "도면 있음" : "도면 없음"}` },
  ];
  return (
    <main id="main" className="mj-wrap mj-main">
      <RequestConfirm projectId={id} vendors={vendors} conditions={conditions} />
    </main>
  );
}

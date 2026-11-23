// /projects/{id}/vendors — 업체 보기 + 담기(C10 · C12 업체 0곳 · D06 + 옆 AI 칸).
// 가견적 = 업체가 확인한 단가 × 믿집 수량(계산 엔진). 담은 업체는 공사마다 서버에 저장돼요.
// 업체 자세히는 늘 전체 화면이에요(옛 @panel 가로채기 창은 9판 D07과 겹쳐서 지웠어요, dev-08).
import { notFound } from "next/navigation";
import { AiPanel } from "@/components/ai/AiPanel";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { VendorList } from "@/components/vendors/VendorList";
import { getProjectShell } from "@/lib/api/project";
import { getShortlist, getVendorList } from "@/lib/api/shortlist";
import { won } from "@/lib/format";

export const metadata = { title: "업체 보기" };

export default async function VendorsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const [list, shortlist] = await Promise.all([getVendorList(shell.id), getShortlist(shell.id).catch(() => null)]);
  if (!list) notFound();
  const base = `/projects/${shell.id}`;
  const n = list.local.length;
  const desc = n
    ? `${list.area_name} ${n}곳 · 모두 사업자 확인함 · 가견적 낮은 순 · 표준견적서 ${won(list.standard_total)}`
    : undefined;
  const context = n ? `업체 ${n}곳 보는 중` : "업체 보기 보는 중";
  // 업체를 확정한 뒤 담기 띠가 가리킬 다음 할 일(공사 요약 '지금 할 일', 없으면 공사 날짜)
  const todo = shell.todo.find((t) => t.href);
  const next = { label: todo?.label ?? "공사 날짜 보기", href: todo?.href ?? `${base}/schedule` };
  return (
    <>
      <AppHeader only="phone" phone={{ title: "업체 보기", back: `${base}/standard`, action: n ? <AsideOpenButton /> : undefined }} />
      <VendorList
        projectId={shell.id}
        list={list}
        shortlist={shortlist}
        next={next}
        mock={shell.mock}
        head={{ title: "업체 보기", crumbs: [{ label: "내 공사", href: "/my" }, { label: shell.name, href: base }, { label: "업체 보기" }], desc }}
        aside={<AiPanel screen="vendors" projectId={shell.id} context={context} />}
      />
    </>
  );
}

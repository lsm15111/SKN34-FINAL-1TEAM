import { notFound } from "next/navigation";
import { BriefSlot, ChecklistSlot } from "@/components/pro/assistant/Slots";
import { ProHeader } from "@/components/pro/Shell";
import { AcceptForm } from "@/components/pro/visit/AcceptForm";
import { MarkSeen } from "@/components/pro/visit/MarkSeen";
import { PeriodForm } from "@/components/pro/visit/PeriodForm";
import { ProposeForm } from "@/components/pro/visit/ProposeForm";
import { VisitStatus } from "@/components/pro/visit/VisitStatus";
import { approvedVendorGate, getVendorVisit, vendorNow } from "@/lib/api/vendor";

export const metadata = { title: "실측 요청" };

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

// 받은 실측 요청 하나(알림 link: /vendor/requests/{vid}). 상태에 따라:
// 새 요청 → 기간 답하기(V04 · D14, ?decline=1이면 못 받아요 시트 V05) · 고객이 고른 날 → 날짜 수락(V06) · ?step=propose → 다른 날 제안(V07)
// · 그 밖 → 상태 보기. 남의 요청이면 404(있는지도 알리지 않아요).
// v4: 새 요청이면 맨 위에 비서 요청 브리핑(V1), 실측이 잡힌 뒤에는 견적서 체크리스트(V3)를 얹어요(components/pro/assistant).
export default async function VendorRequestPage({ params, searchParams }: { params: Promise<{ visitId: string }>; searchParams: Promise<{ step?: string | string[]; decline?: string | string[] }> }) {
  const { visitId } = await params;
  const sp = await searchParams;
  const me = await approvedVendorGate(`/vendor/requests/${encodeURIComponent(visitId)}`);
  const v = await getVendorVisit(visitId);
  if (!v) notFound();
  const back = "/vendor";
  if (v.status === "requested") {
    return (
      <>
        <ProHeader me={me} phone={{ title: "기간 답하기", back }} />
        {v.new ? <MarkSeen visitId={v.id} /> : null}
        <BriefSlot v={v} now={vendorNow("period")} />
        <PeriodForm v={v} now={vendorNow("period")} openDecline={one(sp.decline) === "1"} />
      </>
    );
  }
  if (v.status === "picked" && one(sp.step) === "propose") {
    return (
      <>
        <ProHeader me={me} phone={{ title: "다른 날 제안", back: `/vendor/requests/${encodeURIComponent(v.id)}` }} />
        <ProposeForm v={v} />
      </>
    );
  }
  if (v.status === "picked") {
    return (
      <>
        <ProHeader me={me} phone={{ title: "날짜 수락", back }} />
        <AcceptForm v={v} now={vendorNow("accept")} />
      </>
    );
  }
  return (
    <>
      <ProHeader me={me} phone={{ title: "실측 요청", back }} />
      {["booked", "visited"].includes(v.status) ? <ChecklistSlot visitId={v.id} /> : null}
      <VisitStatus v={v} now={vendorNow("inbox")} />
    </>
  );
}

import { notFound } from "next/navigation";
import { QuoteForm } from "@/components/pro/quote/QuoteForm";
import { ProHeader } from "@/components/pro/Shell";
import { approvedVendorGate, getQuoteBoard, getVendorVisit, vendorNow } from "@/lib/api/vendor";

export const metadata = { title: "실측 견적서 올리기" };

// 실측 견적서 올리기(V10 v_quote): 실측 확정 · 실측 받음 뒤에 보내요(그 밖이면 서버가 409). 남의 요청이면 404.
export default async function VendorQuotePage({ params }: { params: Promise<{ visitId: string }> }) {
  const { visitId } = await params;
  const me = await approvedVendorGate(`/vendor/requests/${encodeURIComponent(visitId)}/quote`);
  const [v, board] = await Promise.all([getVendorVisit(visitId), getQuoteBoard(visitId)]);
  if (!v || !board) notFound();
  return (
    <>
      <ProHeader me={me} phone={{ title: "실측 견적서 올리기", back: `/vendor/requests/${encodeURIComponent(v.id)}` }} />
      <QuoteForm v={v} board={board} now={vendorNow("quote")} />
    </>
  );
}

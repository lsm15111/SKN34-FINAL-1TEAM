import { notFound } from "next/navigation";
import { PriceForm } from "@/components/pro/prices/PriceForm";
import { ProHeader } from "@/components/pro/Shell";
import { Main } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { approvedVendorGate, getMyPricesV3, getMyProfile } from "@/lib/api/vendor";

// 탭 제목도 공정을 따라요(목공 주소에 '도배 단가'가 뜨지 않게, QA r6 L9)
export async function generateMetadata({ params }: { params: Promise<{ trade: string }> }) {
  return { title: (await params).trade === "mokgong" ? "목공 단가" : "도배 단가" };
}

// 도배 단가(D02 d_price, 1201~1209). 목공 v3 단가표는 아직 없어요(9판 '목공 준비 중'): 지금 할 수 있는 업체 정보로 보내요. 승인된 업체만.
export default async function VendorPricesPage({ params }: { params: Promise<{ trade: string }> }) {
  const { trade } = await params;
  if (trade !== "dobae" && trade !== "mokgong") notFound();
  const me = await approvedVendorGate(`/vendor/prices/${trade}`);
  const header = <ProHeader me={me} phone={{ title: trade === "dobae" ? "도배 단가" : "목공 단가", back: "/vendor/profile" }} />;
  if (trade === "mokgong") {
    return (
      <>
        {header}
        <Main narrow>
          <EmptyState icon="doc" as="h1" title="목공 단가표는 준비 중이에요" action={<Button href="/vendor/profile">업체 정보 채우기</Button>}>지금은 도배만 고객과 이어져요.</EmptyState>
        </Main>
      </>
    );
  }
  const [prices, profile] = await Promise.all([getMyPricesV3("dobae"), getMyProfile().catch(() => null)]);
  if (!prices) {
    return (
      <>
        {header}
        <Main narrow>
          <EmptyState icon="doc" as="h1" title="단가표를 불러오지 못했어요" action={<Button variant="text" arrow href="/vendor/profile">업체 정보</Button>}>잠시 뒤 다시 열어 주세요.</EmptyState>
        </Main>
      </>
    );
  }
  return (
    <>
      {header}
      <PriceForm prices={prices} taxKind={prices.example?.tax_kind ?? profile?.tax_kind ?? "general"} homeLabel={prices.example_home} />
    </>
  );
}

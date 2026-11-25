// /v5/start/standard — 로그인 전 표준견적서(C57 · C58 · C59 · D12 · D13, N1 A).
// 답은 이 기기에만 있어서 화면(브라우저 조각)이 읽어 계산해요. 로그인한 고객은 기본 정보에서 바로 내 공사를 만들어서 거기로 보내요.
import { redirect } from "next/navigation";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { GuestAskButton } from "@/components/start/GuestAside";
import { GuestStandard } from "@/components/v5/start/GuestStandard";
import { MOCK_V3A } from "@/lib/mock/v3a/mode";
import { getSession } from "@/lib/session";
import { getCaps } from "@/lib/v5/caps";

export const metadata = { title: "표준견적서" };

export default async function GuestStandardPage() {
  const [session, { v4 }] = await Promise.all([getSession(), getCaps()]);
  if (session?.role === "customer") redirect("/v5/start");
  return (
    <>
      <AppHeader phone={{ title: "표준견적서", back: "/v5/start", action: <GuestAskButton /> }} />
      <GuestStandard mock={MOCK_V3A} caps={{ v4 }} />
    </>
  );
}

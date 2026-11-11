import { V2App } from "@/components/v2/V2App";
import { requireRole } from "@/lib/session";

export const metadata = { title: "믿집 상담 v2" };

// 커스텀 MVP v10을 옮긴 상담 화면. 스타일 → 집 정보 → 자재 → 견적서 · 공정표를 대화로 고른다.
// 계산 · AI는 백엔드(/mvp/v2/*)가 하고, 화면은 고른 값과 결과만 다룬다. 로그인한 고객만 쓴다.
export default async function V2Page() {
  await requireRole("customer", "/v2");
  return <V2App />;
}

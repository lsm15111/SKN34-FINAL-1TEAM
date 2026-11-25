// v5 사본: 메뉴 · 탭 · 로고 주소는 components/v5/site/nav.ts예요(홈 · 인테리어 받기 · 내 공사는 /v5, 나머지는 dev 주소).
// 폰 아래 탭 바(서버). 고객 5칸(홈 · 내 공사 · 채팅 · 알림 · 내 정보) · 업체 4칸(작업함 · 채팅 · 업체 정보 · 알림).
// 폰(<768)에서만 보이고, 웹은 머리 메뉴가 대신해요. 아래 단추 띠(BottomBar)가 있는 흐름 화면에는 두지 않아요.
// Main 바깥, Main 바로 뒤(<body> 바로 아래)에 둬요. 붙는(sticky) 띠라 자기 자리를 차지해 본문을 가리지 않아요.
import { TABS } from "./nav";
import { TabBarNav } from "./TabBarNav";
import { getShellData } from "@/components/site/who";

export async function TabBar() {
  const { session, unread } = await getShellData();
  const tabs = session ? TABS[session.role] : undefined;
  if (!tabs) return null;
  return <TabBarNav tabs={tabs} counts={{ notify: unread }} role={session!.role} />;
}

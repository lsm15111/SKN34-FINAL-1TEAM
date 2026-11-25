// v5 사본: 메뉴 · 탭 · 로고 주소는 components/v5/site/nav.ts예요(홈 · 인테리어 받기 · 내 공사는 /v5, 나머지는 dev 주소).
// v3 머리(서버). 화면마다 그려요: 웹은 늘 같은 메뉴 머리, 폰은 phone(제목 · 뒤로 · 오른쪽 단추)을 주면 뒤로형, 안 주면 로고형.
// 레이아웃이 웹 머리를 그리고 화면이 폰 머리만 그리고 싶으면 only="web" · only="phone"으로 나눠요(공사 화면 · 채팅 2단).
// 붙는 머리(sticky)라 <body> 바로 아래(다른 칸으로 감싸지 않게) 둬요. 그래야 화면 끝까지 붙어 있어요.
import { HeaderBar, type PhoneHeader } from "./HeaderBar";
import { getShellData } from "@/components/site/who";

export async function AppHeader({ phone, only, admin = false }: { phone?: PhoneHeader; only?: "web" | "phone"; admin?: boolean }) {
  const { session, unread } = await getShellData();
  return <HeaderBar session={session} admin={admin || session?.role === "admin"} unread={unread} phone={phone} only={only} />;
}

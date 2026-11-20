// /guide/* 공통: 찾기 창(Ctrl K) · AI 채팅 창 · 맨 위로 단추를 하나씩 둬요. 백과 안에서 글을 옮겨도 창 · 대화가 그대로예요.
// AI 채팅은 고객만 물어볼 수 있고, 손님은 로그인 안내를 봐요. 업체 · 관리자에게는 'AI 채팅에 묻기'가 없어요.
import type { ReactNode } from "react";
import { GuideAsk, type AskWho } from "@/components/guide/GuideAsk";
import { GuideFind } from "@/components/guide/GuideFind";
import { ToTop } from "@/components/guide/ToTop";
import { getSession } from "@/lib/session";

export default async function GuideLayout({ children }: { children: ReactNode }) {
  const me = await getSession();
  const who: AskWho = !me ? "guest" : me.role === "customer" ? "customer" : "none";
  return (
    <>
      {children}
      <ToTop />
      <GuideFind canAsk={who !== "none"} />
      <GuideAsk who={who} />
    </>
  );
}

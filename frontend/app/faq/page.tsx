// /faq — 자주 묻는 질문(C54): 9판의 6개 질문 · 갈래(전체 · 견적 · 업체 · 실측 · 내 정보, ?c=로 서버에서 거름).
// 질문을 누르면 그 자리에서 답이 펼쳐져요(details). 아래 '표준견적서 받기' 띠는 두지 않아요(11-19, 갈래마다 생겼다 사라져서). 로그인 전 AI 칸 칩(C58)이 #질문 id로 와요 → 그 질문을 펼쳐요(FaqOpen).
// 로그인한 고객은 옆에 AI 칸이 붙어요(공사 없는 화면). 진행 중인 공사를 '○○ 기준' 칩으로 골라 물을 수 있어요.
import Link from "next/link";
import { AiPanel } from "@/components/ai/AiPanel";
import { AppHeader } from "@/components/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { FaqOpen } from "@/components/home/FaqOpen";
import { FAQ_CATS, FAQ_V3 } from "@/components/home/faq";
import { Icon } from "@/components/ui/Icon";
import { getSession } from "@/lib/session";
import s from "./faq.module.css";

export const metadata = { title: "자주 묻는 질문" };

export default async function FaqPage({ searchParams }: { searchParams: Promise<{ c?: string }> }) {
  const [{ c }, session] = await Promise.all([searchParams, getSession()]);
  const member = session?.role === "customer";
  const cat = FAQ_CATS.find((x) => x.key === c)?.key ?? "all";
  const items = cat === "all" ? FAQ_V3 : FAQ_V3.filter((f) => f.cat === cat);
  const body = (
    <>
      <nav aria-label="질문 갈래">
        <ul className={s.cats}>
          {FAQ_CATS.map((x) => (
            <li key={x.key}>
              <Link className={s.cat} href={x.key === "all" ? "/faq" : `/faq?c=${x.key}`} aria-current={x.key === cat ? "page" : undefined}>{x.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
      <section className={s.group} aria-label="질문">
        {items.map((f, i) => (
          <details key={f.id} id={f.id} className={s.acc} open={i === 0}>
            <summary><span>{f.q}</span><Icon name="chevron-down" size={20} /></summary>
            <p>{f.a}</p>
          </details>
        ))}
      </section>
    </>
  );
  return (
    <>
      <AppHeader phone={{ title: "자주 묻는 질문", back: "/", action: member ? <AsideOpenButton /> : undefined }} />
      <Main narrow={!member}>
        <PageHead title="자주 묻는 질문" />
        {member ? <WithAside aside={<AiPanel screen="home" />}>{body}</WithAside> : body}
        <FaqOpen />
      </Main>
    </>
  );
}

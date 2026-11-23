// / 홈(C01 로그인 전 · C40 로그인 뒤 · C41 이어 하기 · D10 웹).
// - 견본 숫자는 서버 계산 엔진 값이에요(lib/api/guest.ts, 1시간 둠). 못 받으면 견본 칸을 숨겨요.
// - 로그인한 고객은 맨 위 '진행 중' 띠(누르면 그 일로)와 아래 탭 바가 붙고, '인테리어 받기'는 이어 하기 / 새 집을 먼저 물어요.
//   로그인 뒤 기기 답 + 진행 중 공사면 /?resume=1로 와서 그 창이 바로 열려요(C41).
import { AppHeader } from "@/components/site/AppHeader";
import { Main } from "@/components/site/Frame";
import { TabBar } from "@/components/site/TabBar";
import { HomeLinks, HowItWorks, ResumeStrip } from "@/components/home/HomeParts";
import { SampleQuote } from "@/components/home/SampleQuote";
import { StartCta } from "@/components/home/StartCta";
import { getSampleStandard } from "@/lib/api/guest";
import type { Ongoing } from "@/lib/guest/api";
import { listMyProjects, nextOf, type ApiProjectItem } from "@/lib/api/project";
import { projectName, stepName } from "@/lib/guest/info";
import { visitState } from "@/lib/labels";
import { MOCK_V3A } from "@/lib/mock/v3a/mode";
import { MOCK_ONGOING } from "@/lib/mock/v3a/project";
import { getSession } from "@/lib/session";
import s from "@/components/home/home.module.css";

type Resume = Ongoing & { status: string; href: string; lead?: string | null; current?: number };

/** 진행 중 공사 하나(가장 최근에 바뀐 것): 고객이 지금 할 일이 있으면 그 일로, 없으면 기다리는 일을 보여요 */
function ongoingOf(list: ApiProjectItem[]): Resume | null {
  const p = list.find((x) => x.phase !== "done");
  if (!p) return null;
  const next = nextOf(p);
  const mine = p.vendors.find((v) => v.next.who === "customer") ?? p.vendors[0];
  const state = mine ? `${mine.vendor_name} ${visitState(mine.status, "customer").label}` : p.todo?.text ?? stepName(p.current);
  const pick = mine && (mine.next.kind === "pick" || mine.next.kind === "proposal");
  const link = p.todo?.link && p.todo.link.startsWith("/") && !p.todo.link.startsWith("//") ? p.todo.link : `/projects/${p.id}`;
  const fallback = pick ? `/projects/${p.id}/visits/${encodeURIComponent(mine.visit_id)}` : link;
  return {
    id: p.id,
    name: projectName(p.emd, p.region, p.trades),
    step: stepName(p.current),
    status: next.task?.label ?? state,
    lead: next.task ? (next.waiting ? "기다리는 중" : "지금 할 일") : null,
    href: (!next.waiting && next.task?.href) || fallback,
    current: next.current,
  };
}

export default async function Home({ searchParams }: { searchParams: Promise<{ bye?: string; mock?: string; resume?: string }> }) {
  const { bye, mock, resume } = await searchParams;
  const [session, std] = await Promise.all([getSession(), getSampleStandard()]);
  const member = session?.role === "customer";
  // 개발 예시: /?mock=member로 로그인 뒤 홈(C40 · C41) 모양을 미리 봐요(운영에서는 꺼져요)
  const preview = MOCK_V3A && mock === "member";
  const ongoing: Resume | null = preview ? MOCK_ONGOING : member ? ongoingOf(await listMyProjects().catch(() => [])) : null;

  return (
    <>
      <AppHeader />
      <Main>
        {bye ? <p className={s.bye} role="status">탈퇴했어요.</p> : null}
        {ongoing ? <ResumeStrip name={ongoing.name} status={ongoing.status} lead={ongoing.lead ?? null} href={ongoing.href} /> : null}
        <div className={s.hero}>
          <section className={`${s.group} ${s.heroText}`} aria-labelledby="hero-t">
            <p className={s.eb}>업체를 만나기 전에</p>
            <h1 id="hero-t" className={s.h}>인테리어,<br />믿집에서 시작해요</h1>
            <div className={s.cta}>
              <StartCta ongoing={ongoing} autoOpen={resume === "1"} />
              <p className={s.note}>{member || preview ? "1분이면 표준견적서가 나와요" : "1분 · 가입 없이 표준견적서를 바로 봐요"}</p>
            </div>
          </section>
          {std ? <SampleQuote std={std} /> : null}
        </div>
        <HowItWorks current={ongoing?.current} />
        <HomeLinks guest={!session && !preview} />
      </Main>
      <TabBar />
    </>
  );
}

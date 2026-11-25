// /v5/projects/{id}/standard — 내 공사 표준견적서(C07 · C60 부분 공사 · D01 + 옆 AI 칸).
// 폰은 머리 'AI 채팅'으로 전체 화면 AI를 열어요(C09). 공급가 · 부가세를 나눠 보이는 곳은 이 합계 칸 하나예요.
// '조건 바꾸기'는 기본 정보 고치기(/start?edit=, 첫 요청 뒤에는 잠긴 화면 C50이라 이름도 '집 정보 보기')로 가요.
// 아래 주 단추는 공사 '지금 할 일'(없으면 업체 보기). 숫자는 모두 계산 엔진 값이에요.
// 전체 도배는 dev와 같이 시장 단가 표준견적서(업체 견적서 중앙값, GET /v2/projects/{id}/market-quote)로 보여요.
// 부분 공사 · 시장 단가를 못 받으면 기존 표준견적서 그대로예요(dev app/projects/[id]/standard와 같은 몫).
import { notFound } from "next/navigation";
import { AiPanel } from "@/components/ai/AiPanel";
import { AppHeader } from "@/components/v5/site/AppHeader";
import { AsideOpenButton } from "@/components/site/AsideSlot";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { StandardSheet } from "@/components/v5/start/StandardSheet";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { MarketSheet, MarketTotal, MarketTrust } from "@/components/v2/market/MarketQuote";
import { getMyMarketQuote } from "@/lib/api/quote";
import { daysCaption } from "@/lib/v5/guest/standard";
import { getProjectShell } from "@/lib/v5/api/project";
import { getStandardView } from "@/lib/v5/api/quote";

export const metadata = { title: "표준견적서" };

export default async function StandardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const shell = await getProjectShell(id);
  if (!shell) notFound();
  const view = await getStandardView(shell);
  if (!view) notFound();
  const market = shell.mock ? null : await getMyMarketQuote(shell.id);
  const base = `/v5/projects/${shell.id}`;
  const changeHref = `/v5/start?edit=${shell.id}`;
  const todo = shell.todo.find((t) => t.href);
  return (
    <>
      <AppHeader only="phone" phone={{ title: "표준견적서", back: base, action: <AsideOpenButton /> }} />
      <Main>
        <PageHead title="표준견적서" crumbs={[{ label: "내 공사", href: "/v5/my" }, { label: shell.name, href: base }, { label: "표준견적서" }]} />
        <WithAside aside={<AiPanel screen="standard" projectId={shell.id} />}>
          {market ? (
            <>
              <MarketTotal q={market} changeHref={changeHref} caption={["부가세 포함", daysCaption(view.days)].filter(Boolean).join(" · ")} />
              <MarketSheet q={market} />
              <MarketTrust q={market} />
            </>
          ) : (
            <StandardSheet view={view} changeHref={changeHref} changeLabel={shell.locked ? "집 정보 보기" : undefined} />
          )}
        </WithAside>
      </Main>
      <BottomBar>
        {view.scope === "partial" ? null : <Button variant="secondary" size="lg" href={`${base}/plan`}>예상 공정표</Button>}
        <Button size="lg" href={todo?.href ?? `${base}/vendors`}>{todo?.label ?? "업체 보기"}</Button>
      </BottomBar>
    </>
  );
}

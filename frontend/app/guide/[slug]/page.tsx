// /guide/[slug] — 백과 글. 없는 글은 404예요. 'AI 채팅에 묻기'는 고객 · 손님에게만 보여요(손님은 로그인 안내).
// 글 속 용어 · 관련 용어를 누르면 글 위에 자세히 칸이 열려요(?term=).
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { Main } from "@/components/site/Frame";
import { ArticleView } from "@/components/guide/ArticleView";
import { OpenTerm } from "@/components/guide/TermDetail";
import { articleBySlug, plain } from "@/lib/guide";
import { getSession } from "@/lib/session";

type Props = { params: Promise<{ slug: string }>; searchParams: Promise<{ term?: string | string[] }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const a = articleBySlug((await params).slug);
  return a ? { title: a.title, description: plain(a.lead) } : { title: "믿집 백과" };
}

export default async function GuideArticlePage({ params, searchParams }: Props) {
  const a = articleBySlug((await params).slug);
  if (!a) notFound();
  const me = await getSession();
  const { term } = await searchParams;
  return (
    <>
      <AppHeader phone={{ title: "믿집 백과", back: "/guide" }} />
      <Main>
        <ArticleView a={a} canAsk={!me || me.role === "customer"} />
        <OpenTerm id={term} />
      </Main>
    </>
  );
}

// /guide/[slug] — 백과 글. 없는 글은 404예요. 'AI 채팅에 묻기'는 고객 · 손님에게만 보여요(손님은 로그인 안내).
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AppHeader } from "@/components/site/AppHeader";
import { Main } from "@/components/site/Frame";
import { ArticleView } from "@/components/guide/ArticleView";
import { articleBySlug, plain } from "@/lib/guide";
import { getSession } from "@/lib/session";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const a = articleBySlug((await params).slug);
  return a ? { title: a.title, description: plain(a.lead) } : { title: "믿집 백과" };
}

export default async function GuideArticlePage({ params }: Props) {
  const a = articleBySlug((await params).slug);
  if (!a) notFound();
  const me = await getSession();
  return (
    <>
      <AppHeader phone={{ title: "믿집 백과", back: "/guide" }} />
      <Main>
        <ArticleView a={a} canAsk={!me || me.role === "customer"} />
      </Main>
    </>
  );
}

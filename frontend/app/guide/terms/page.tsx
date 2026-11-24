// /guide/terms — 용어 사전: 공정 갈래(전체 · 도배 · 목공 · 공통 · 다른 공정) + '그림 있는 것만', 그림 카드 격자.
// 카드를 누르면 ?term=으로 자세히 칸이 열려요(웹 오른쪽 · 폰 아래 시트). 갈래 · 그림 거르기는 주소에 남아 그대로예요.
import type { Metadata } from "next";
import Link from "next/link";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { TermCard } from "@/components/guide/TermCard";
import { OpenTerm } from "@/components/guide/TermDetail";
import { FindButton } from "@/components/guide/Triggers";
import { TERMS, TRADE_LABEL, TRADE_ORDER, termById, type Term, type TradeKey } from "@/lib/guide";
import s from "@/components/guide/guide.module.css";

type Q = { trade?: string; img?: string; term?: string };
type Props = { searchParams: Promise<Q> };

const isTrade = (v: string | undefined): v is TradeKey => !!v && (TRADE_ORDER as string[]).includes(v);
function href(q: { trade?: TradeKey; img?: boolean }) {
  const p = new URLSearchParams();
  if (q.trade) p.set("trade", q.trade);
  if (q.img) p.set("img", "1");
  const v = p.toString();
  return v ? `/guide/terms?${v}` : "/guide/terms";
}
/** 그림 있는 카드 먼저(같은 높이끼리 줄을 이뤄요), 그 안에서는 가나다순 */
const byName = (a: Term, b: Term) => Number(!a.images.length) - Number(!b.images.length) || a.term.localeCompare(b.term, "ko");

export async function generateMetadata({ searchParams }: Props): Promise<Metadata> {
  const t = termById((await searchParams).term ?? "");
  return { title: t ? `${t.term} · 용어 사전` : "용어 사전" };
}

export default async function GuideTermsPage({ searchParams }: Props) {
  const q = await searchParams;
  const trade = isTrade(q.trade) ? q.trade : undefined;
  const img = q.img === "1";
  const pool = TERMS.filter((t) => !img || t.images.length > 0);
  const count = (k?: TradeKey) => pool.filter((t) => !k || t.trade === k).length;
  const groups = (trade ? [trade] : TRADE_ORDER)
    .map((k) => ({ k, items: pool.filter((t) => t.trade === k).sort(byName) }))
    .filter((g) => g.items.length);

  return (
    <>
      <AppHeader phone={{ title: "용어 사전", back: "/guide" }} />
      <Main>
        <PageHead title="용어 사전" crumbs={[{ label: "믿집 백과", href: "/guide" }, { label: "용어 사전" }]} />
        <FindButton label="용어 찾기" />
        <div className={s.filters}>
          <nav aria-label="공정">
            <ul className={s.chips}>
              {[undefined, ...TRADE_ORDER].map((k) => (
                <li key={k ?? "all"}>
                  <Link className={s.chip} href={href({ trade: k, img })} scroll={false} aria-current={k === trade ? "page" : undefined}>
                    {k ? TRADE_LABEL[k] : "전체"} <span className={s.chipN}>{count(k)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <Link className={s.toggle} href={href({ trade, img: !img })} scroll={false} aria-current={img ? "true" : undefined}>
            <i aria-hidden="true" />그림 있는 것만
          </Link>
        </div>

        {groups.length ? (
          groups.map((g) => (
            <section key={g.k} className={s.termSec} aria-labelledby={`tg-${g.k}`}>
              <div className={s.gh}>
                <h2 id={`tg-${g.k}`}>{TRADE_LABEL[g.k]}</h2>
                <span className={s.meta}>{g.items.length}개{g.k === "oos" ? " · 믿집 범위 밖이라 알아 두기로만 적었어요" : ""}</span>
              </div>
              <ul className={s.cards}>
                {g.items.map((t) => <li key={t.id}><TermCard term={t} showTrade={!!trade || g.k === "oos"} /></li>)}
              </ul>
            </section>
          ))
        ) : (
          <p className={s.empty}>맞는 용어가 없어요</p>
        )}

        <OpenTerm id={q.term} />
      </Main>
    </>
  );
}

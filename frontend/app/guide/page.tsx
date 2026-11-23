// /guide — 믿집 백과 첫 화면: 찾기 칸 → '처음이에요' · '찾아볼래요' 나란히 → 많이 찾는 용어 그림 카드.
import Link from "next/link";
import { AppHeader } from "@/components/site/AppHeader";
import { Main } from "@/components/site/Frame";
import { TermCard } from "@/components/guide/TermCard";
import { FindButton } from "@/components/guide/Triggers";
import { Icon } from "@/components/ui/Icon";
import { PATH, TERMS, popularTerms, topicHref, visibleTopics } from "@/lib/guide";
import s from "@/components/guide/guide.module.css";

export const metadata = { title: "믿집 백과" };

export default function GuidePage() {
  const popular = popularTerms();

  return (
    <>
      <AppHeader phone={{ title: "믿집 백과", back: "/" }} />
      <Main>
        <div className={`${s.hero} ${s.heroHome}`}>
          <h1 className={`${s.h1} ${s.phoneHidden}`}>믿집 백과</h1>
          <p className={s.lead}>도배 · 목공을 처음 하는 분을 위한 글과 용어 사전이에요.</p>
          <FindButton />
        </div>

        <div className={s.two}>
          <section className={s.group} aria-labelledby="g-first">
            <div className={s.gh}><h2 id="g-first">처음이에요</h2><span className={s.meta}>순서대로 읽어요</span></div>
            <ol className={s.path}>
              {PATH.map((x, i) => (
                <li key={x.href}><Link href={x.href}><span className={s.num} aria-hidden="true">{i + 1}</span><span>{x.title}</span></Link></li>
              ))}
            </ol>
          </section>
          <section className={s.group} aria-labelledby="g-find">
            <div className={s.gh}><h2 id="g-find">찾아볼래요</h2><span className={s.meta}>주제별로 골라요</span></div>
            <ul className={s.tiles}>
              {visibleTopics().map((t) => (
                <li key={t.key}>
                  <Link className={s.tile} href={topicHref(t)}>
                    <span className={s.tileIc} aria-hidden="true"><Icon name={t.icon} size={20} /></span>
                    <span><b>{t.label}</b><small>{t.desc}</small></span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <section className={s.group} aria-labelledby="g-terms">
          <div className={s.gh}>
            <h2 id="g-terms">많이 찾는 용어</h2>
            <Link className={`${s.more} ${s.moreLink}`} href="/guide/terms">용어 사전 {TERMS.length}개 보기<Icon name="chevron-right" size={16} /></Link>
          </div>
          <ul className={s.cards}>
            {popular.map((t) => <li key={t.id}><TermCard term={t} /></li>)}
          </ul>
        </section>
      </Main>
    </>
  );
}

// 용어 그림 카드(첫 화면 '많이 찾는 용어' · 용어 사전). 그림이 없으면 글 카드로 그려요. 누르면 자세히 칸이 열려요.
import { TRADE_LABEL, termHref, type Term } from "@/lib/guide";
import { TermLink } from "./TermPanel";
import s from "./guide.module.css";

export function TermCard({ term: t, href, showTrade = true }: { term: Term; href?: string; showTrade?: boolean }) {
  const img = t.images.find((x) => x.kind === "입체 그림") ?? t.images[0];
  return (
    <TermLink href={href ?? termHref(t)} className={img ? s.card : `${s.card} ${s.cardText}`} aria-label={`${t.term}: ${t.easy}`}>
      {img ? <img className={s.cardImg} src={img.src} alt="" loading="lazy" width={400} height={300} /> : null}
      <span className={s.cardBody}>
        <span className={s.cardName}>{t.term}</span>
        {t.aliases.length ? <span className={s.cardAlias}>{t.aliases.slice(0, 2).join(" · ")}</span> : null}
        <span className={s.cardEasy}>{t.easy}</span>
        {showTrade ? (
          <span className={s.cardTags}>
            <span className={t.oos ? `${s.tag} ${s.tagOos}` : s.tag}>{TRADE_LABEL[t.trade]}</span>
          </span>
        ) : null}
      </span>
    </TermLink>
  );
}

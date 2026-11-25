// 용어 자세히 칸 속(서버): 쉬운 말 → 그림 → 참고 · 어디에 쓰나요 · 자세히 → 업체에 물어볼 것 → 나오는 글 → 출처.
// 다른 공정(범위 밖) 용어는 '알아 두기'로만 적었다고 밝혀요.
import Link from "next/link";
import { CHECKED, TRADE_LABEL, articleHref, articlesWithTerm, termById, type Term } from "@/lib/guide";
import { TermPanel } from "./TermPanel";
import s from "./guide.module.css";

/** 주소 ?term=의 용어 칸. 백과 화면마다 맨 끝에 두면 보던 화면 위에 열려요. 없는 용어면 그리지 않아요 */
export function OpenTerm({ id }: { id?: string | string[] }) {
  const t = typeof id === "string" ? termById(id) : undefined;
  if (!t) return null;
  return (
    <TermPanel id={t.id} label={`${t.term} 자세히`} head={<TermHead term={t} />}>
      <TermDetail term={t} nameId="term-name" />
    </TermPanel>
  );
}

export function TermHead({ term: t }: { term: Term }) {
  return (
    <>
      <span className={t.oos ? `${s.tag} ${s.tagOos}` : s.tag}>{TRADE_LABEL[t.trade]}</span>
      {t.oos ? <span className={`${s.tag} ${s.tagOos}`}>믿집 범위 밖</span> : null}
    </>
  );
}

export function TermDetail({ term: t, nameId }: { term: Term; nameId: string }) {
  const arts = articlesWithTerm(t);
  return (
    <>
      <div className={s.docHead}>
        <h2 id={nameId} className={s.detName}>{t.term}</h2>
        {t.aliases.length ? <p className={s.mute}>현장에서는 {t.aliases.map((a) => `'${a}'`).join(" · ")}라고도 해요</p> : null}
      </div>
      <p className={s.detEasy}>{t.easy}</p>
      {t.oos ? <p className={`${s.box} ${s.pit}`}>믿집은 지금 도배 · 목공만 다뤄요. 이 공정은 알아 두기로만 짧게 적었어요.</p> : null}
      {t.images.length ? (
        <div className={s.detImgs}>
          {t.images.map((im) => (
            <span key={im.src} className={s.detImg}>
              <img src={im.src} alt={`${t.term} ${im.kind}`} loading="lazy" width={400} height={300} />
              <small>{im.kind}</small>
            </span>
          ))}
        </div>
      ) : null}
      {t.tip ? <section className={s.kv}><h3>참고</h3><p>{t.tip}</p></section> : null}
      {t.use ? <section className={s.kv}><h3>어디에 쓰나요</h3><p>{t.use}</p></section> : null}
      {t.detail ? <section className={s.kv}><h3>자세히</h3><p>{t.detail}</p></section> : null}
      {t.ask ? <section className={`${s.kv} ${s.kvAsk}`}><h3>업체에 물어볼 것</h3><p>{t.ask}</p></section> : null}
      {arts.length ? (
        <section className={s.detRel}>
          <h3>이 용어가 나오는 글</h3>
          <ul className={s.links}>
            {arts.map((a) => <li key={a.slug}><Link href={articleHref(a.slug)}>{a.title}</Link></li>)}
          </ul>
        </section>
      ) : null}
      {t.sources.length ? (
        <section className={s.src}>
          <h3>출처 · {CHECKED}</h3>
          <ul>
            {t.sources.map((x) => (
              <li key={x.title}>{x.url ? <a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}<span className="mj-sr"> 새 창</span></a> : x.title}{x.publisher ? ` · ${x.publisher}` : ""}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

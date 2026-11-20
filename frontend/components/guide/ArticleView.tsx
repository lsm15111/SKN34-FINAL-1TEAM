// 백과 글(서버). 틀: 결론(lead) → 이 글에서 알 수 있어요 → 본문 → 놓치기 쉬운 것 → 믿집에서는 → 확인할 것 → 관련 용어 → 출처.
// 배치: 넓은 웹(≥1280) 왼쪽 글 목록 · 본문 · 오른쪽 '이 글에서', 웹(≥1024) 목록 · 본문, 그 아래는 본문만(위 '이 글에서' 펼침 · 아래 '백과 글 더 보기').
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { CHECKED, IMG_NOTE, NAV_GROUPS, neighbors, readMinutes, termByName, termHref, type Article } from "@/lib/guide";
import type { Block } from "@/lib/guide/types";
import { ArticleToc } from "./ArticleToc";
import { CopyChecks } from "./CopyChecks";
import { GuideNav } from "./GuideNav";
import { Rich } from "./Rich";
import { TermLink } from "./TermPanel";
import { AskButton } from "./Triggers";
import s from "./guide.module.css";

function BlockView({ b }: { b: Block }) {
  if (b.t === "p") return <p className={s.p}><Rich text={b.text} /></p>;
  if (b.t === "list") return <ul className={s.ul}>{b.items.map((x, i) => <li key={i}><Rich text={x} /></li>)}</ul>;
  if (b.t === "steps") {
    return (
      <ol className={s.ol}>
        {b.items.map((x, i) => (
          <li key={i}>
            <span className={s.olNo} aria-hidden="true">{i + 1}</span>
            <span><b>{x.title}</b> <Rich text={x.text} /></span>
          </li>
        ))}
      </ol>
    );
  }
  const t = termByName(b.term);
  const imgs = (t?.images ?? []).filter((im) => b.kinds.includes(im.kind));
  if (!t || !imgs.length) return null;
  return (
    <figure className={s.fig}>
      {imgs.map((im) => <img key={im.src} src={im.src} alt={`${t.term} ${im.kind}`} loading="lazy" width={400} height={300} />)}
      <figcaption>{b.caption} · {IMG_NOTE}</figcaption>
    </figure>
  );
}

export function ArticleView({ a, canAsk }: { a: Article; canAsk: boolean }) {
  const group = NAV_GROUPS.find((g) => g.slugs.includes(a.slug))?.title;
  const terms = a.terms.map((n) => termByName(n)).filter((t) => t !== undefined);
  const { prev, next } = neighbors(a.slug);
  const toc = [
    ...a.sections.map((x) => ({ id: x.id, title: x.title })),
    ...(a.pitfall ? [{ id: "a-pitfall", title: "놓치기 쉬운 것" }] : []),
    ...(a.mijip ? [{ id: "a-mijip", title: "믿집에서는" }] : []),
    ...(a.checks.length ? [{ id: "a-checks", title: "확인할 것" }] : []),
  ];

  return (
    <div className={s.art}>
      <div className={s.navCol}><GuideNav current={a.slug} /></div>

      <article className={s.doc} aria-labelledby="a-title">
        <header className={s.docHead}>
          <p className={s.crumbs}>
            <Link href="/guide">믿집 백과</Link>
            {group ? <><span aria-hidden="true">›</span><span>{group}</span></> : null}
          </p>
          <h1 id="a-title" className={s.h1}>{a.title}</h1>
          <p className={s.docLead}><Rich text={a.lead} /></p>
          <p className={s.docMeta}><span>읽는 데 {readMinutes(a)}분</span><span>{CHECKED}</span></p>
        </header>

        <details className={s.phoneToc}>
          <summary>이 글에서</summary>
          <div className={s.phoneTocBody}>
            <ol className={s.tocPlain}>
              {toc.map((x) => <li key={x.id}><a href={`#${x.id}`}>{x.title}</a></li>)}
            </ol>
            {canAsk ? <AskButton block /> : null}
          </div>
        </details>

        {a.learn.length ? (
          <section className={`${s.box} ${s.learn}`} aria-labelledby="a-learn">
            <h2 id="a-learn">이 글에서 알 수 있어요</h2>
            <ul>{a.learn.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </section>
        ) : null}

        {a.sections.map((x) => (
          <section key={x.id} id={x.id} className={s.sec} aria-labelledby={`${x.id}-h`}>
            <h2 id={`${x.id}-h`}>{x.title}</h2>
            {x.blocks.map((b, i) => <BlockView key={i} b={b} />)}
          </section>
        ))}

        {a.pitfall ? (
          <section id="a-pitfall" className={`${s.box} ${s.pit}`} aria-labelledby="a-pitfall-h">
            <h2 id="a-pitfall-h">놓치기 쉬운 것</h2>
            <p><Rich text={a.pitfall} /></p>
          </section>
        ) : null}

        {a.mijip ? (
          <section id="a-mijip" className={`${s.box} ${s.mj}`} aria-labelledby="a-mijip-h">
            <h2 id="a-mijip-h">믿집에서는</h2>
            <p><Rich text={a.mijip.text} /></p>
            {a.mijip.link ? <div><Button href={a.mijip.link.href} variant="weak" size="sm" arrow>{a.mijip.link.label}</Button></div> : null}
          </section>
        ) : null}

        {a.checks.length ? (
          <section id="a-checks" className={s.sec} aria-labelledby="a-checks-h">
            <h2 id="a-checks-h">확인할 것</h2>
            <ul id="a-checks-list" className={s.checks}>{a.checks.map((x, i) => <li key={i}><span><Rich text={x} /></span></li>)}</ul>
            <CopyChecks lines={a.checks.map((x) => x.replace(/\[\[([^\]]+)\]\]/g, "$1"))} target="a-checks-list" />
          </section>
        ) : null}

        {terms.length ? (
          <section className={s.sec} aria-labelledby="a-terms-h">
            <h2 id="a-terms-h" className={s.h3}>관련 용어</h2>
            <ul className={s.rel}>
              {terms.map((t) => <li key={t.id}><TermLink className={s.relLink} href={termHref(t)}>{t.term}</TermLink></li>)}
            </ul>
          </section>
        ) : null}

        {a.sources.length ? (
          <section className={s.src} aria-labelledby="a-src-h">
            <h2 id="a-src-h">출처 · {CHECKED}</h2>
            <ul>
              {a.sources.map((x) => (
                <li key={x.title}>
                  {x.url ? <a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}<span className="mj-sr"> 새 창</span></a> : x.title}
                  {x.publisher ? ` · ${x.publisher}` : ""}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {prev || next ? (
          <nav className={s.pager} aria-label="앞 · 뒤 글">
            {prev ? <Link href={`/guide/${prev.slug}`}><small>앞 글</small><b>{prev.title}</b></Link> : null}
            {next ? <Link className={s.next} href={`/guide/${next.slug}`}><small>다음 글</small><b>{next.title}</b></Link> : null}
          </nav>
        ) : null}
      </article>

      <div className={s.tocCol}><ArticleToc items={toc} canAsk={canAsk} /></div>

      <details className={`${s.phoneToc} ${s.phoneNav}`}>
        <summary>백과 글 더 보기</summary>
        <div className={s.phoneTocBody}><GuideNav current={a.slug} /></div>
      </details>
    </div>
  );
}

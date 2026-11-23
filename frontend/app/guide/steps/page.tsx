// /guide/steps — 믿집으로 하는 순서(공사 화면 6단계와 같은 이름). 첫 단계만 펼쳐 두고, 나머지는 눌러서 펼쳐요.
// 실측 뒤는 '그리고'(→) · '또는'으로 이어지는 길을 보여요. 내 공사 단계에 맞춰 펼치기는 보류예요(feat-v3-baekgwa-project-link).
import Link from "next/link";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Icon } from "@/components/ui/Icon";
import { STEPS, articleBySlug, articleHref } from "@/lib/guide";
import s from "@/components/guide/guide.module.css";

export const metadata = { title: "믿집으로 하는 순서" };

export default function GuideStepsPage() {
  return (
    <>
      <AppHeader phone={{ title: "믿집으로 하는 순서", back: "/guide" }} />
      <Main narrow>
        <PageHead title="믿집으로 하는 순서" crumbs={[{ label: "믿집 백과", href: "/guide" }, { label: "믿집으로 하는 순서" }]} />
        <section className={s.group} aria-label="단계">
          <ol className={s.stepList}>
            {STEPS.map((st, i) => {
              const arts = st.slugs.map((x) => articleBySlug(x)).filter((a) => a !== undefined);
              return (
                <li key={st.name}>
                  <details className={s.step} open={i === 0}>
                    <summary>
                      <span className={s.stepNo} aria-hidden="true">{i + 1}</span>
                      <span className={s.stepName}>
                        <b><span className="mj-sr">{i + 1}단계 </span>{st.name}</b>
                        <span>{st.desc}</span>
                      </span>
                      <span className={s.stepOpen} aria-hidden="true" />
                    </summary>
                    <div className={s.stepBody}>
                      {st.flow ? (
                        <ol className={s.flow} aria-label="실측 뒤 이어지는 일">
                          {st.flow.map((f) => <li key={f.label}>{f.label}{f.or ? <> <em>또는</em> {f.or}</> : null}</li>)}
                        </ol>
                      ) : null}
                      {arts.length ? (
                        <ul className={s.links}>
                          {arts.map((a) => <li key={a.slug}><Link href={articleHref(a.slug)}>{a.title}<Icon name="chevron-right" size={16} /></Link></li>)}
                        </ul>
                      ) : null}
                    </div>
                  </details>
                </li>
              );
            })}
          </ol>
        </section>
      </Main>
    </>
  );
}

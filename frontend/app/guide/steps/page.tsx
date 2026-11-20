// /guide/steps — 믿집으로 하는 순서(공사 화면 6단계와 같은 이름). 지금 단계만 펼쳐 두고, 나머지는 눌러서 펼쳐요.
// 지금 단계: ?s=1~6 → 진행 중인 내 공사(고객) → 없으면 1단계. 실측 뒤는 '그리고'(→) · '또는'으로 이어지는 길을 보여요.
import Link from "next/link";
import { AppHeader } from "@/components/site/AppHeader";
import { Main, PageHead } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { STEPS, articleBySlug, articleHref } from "@/lib/guide";
import { listMyProjectsV3 } from "@/lib/api/schedule";
import { projectName, stepIndex } from "@/lib/guest/info";
import { getSession } from "@/lib/session";
import s from "@/components/guide/guide.module.css";

export const metadata = { title: "믿집으로 하는 순서" };

export default async function GuideStepsPage({ searchParams }: { searchParams: Promise<{ s?: string }> }) {
  const { s: q } = await searchParams;
  const me = await getSession();
  const mine = me?.role === "customer" ? await listMyProjectsV3().catch(() => []) : [];
  const now = mine.find((p) => p.phase !== "done");
  const asked = Number(q);
  const cur = Number.isInteger(asked) && asked >= 1 && asked <= STEPS.length ? asked - 1 : now ? stepIndex(now.current) : 0;
  const mark = !!now || q !== undefined;

  return (
    <>
      <AppHeader phone={{ title: "믿집으로 하는 순서", back: "/guide" }} />
      <Main narrow>
        <PageHead title="믿집으로 하는 순서" crumbs={[{ label: "믿집 백과", href: "/guide" }, { label: "믿집으로 하는 순서" }]} />
        {now ? (
          <div className={s.band}>
            <span><b>{projectName(now.emd, now.region, now.trades)}</b> · 지금 {cur + 1}단계</span>
            <Button className={s.go} href={`/projects/${now.id}`} variant="text" arrow>내 공사로</Button>
          </div>
        ) : null}
        <section className={s.group} aria-label="단계">
          <ol className={s.stepList}>
            {STEPS.map((st, i) => {
              const done = mark && i < cur;
              const isNow = mark && i === cur;
              const arts = st.slugs.map((x) => articleBySlug(x)).filter((a) => a !== undefined);
              return (
                <li key={st.name}>
                  <details className={[s.step, done ? s.stepDone : null, isNow ? s.stepNow : null].filter(Boolean).join(" ")} open={i === cur}>
                    <summary>
                      <span className={s.stepNo} aria-hidden="true">{done ? <Icon name="check" size={18} /> : i + 1}</span>
                      <span className={s.stepName}>
                        <b>
                          <span className="mj-sr">{i + 1}단계 </span>{st.name}
                          {isNow ? <span className={`${s.tag} ${s.tagNow}`}>지금</span> : done ? <span className="mj-sr"> (지났어요)</span> : null}
                        </b>
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

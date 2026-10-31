// 실제로 만든 프로젝트의 진행 현황. 저장된 답과 올린 사진 · 도면을 API에서 읽어 보여 준다.
// 예상 공정표 · 표준견적서는 상담에서 보고, 업체 고르기(가견적 후보)는 실제 API로 잇는다. 그 밖 단계는 '연결 전'으로 알린다.
import { Fragment } from "react";
import Link from "next/link";
import { ProjectTrack } from "./ProjectTrack";
import type { ApiProject } from "@/lib/api/project";
import { TRADE_KEYS, WHEN_LABEL, budgetLabel, gradeLabel, mokLabel, sizeLabel } from "@/lib/labels";
import { TRADE_LABEL } from "@/lib/types";
import { dateSeoul, md } from "@/lib/format";

export function RealProjectHub({ p, step }: { p: ApiProject; step: number }) {
  const name = (id: string) => p.spaces.find((s) => s.id === id)?.name ?? "";
  const { dobae, mokgong } = p.trades;
  // 고른 공정과 기본정보에 보일 한 줄 (도배는 유형, 목공은 항목도)
  const picked = TRADE_KEYS.flatMap((t) => {
    const tr = p.trades[t];
    if (!tr) return [];
    const where = tr.spaces.map(name).join(" · ");
    const text = t === "dobae" && dobae ? `${gradeLabel(dobae.grade)} · ${where}` : t === "mokgong" && mokgong ? `${where} · ${mokgong.items.map(mokLabel).join(" · ")}` : where;
    return [{ t, label: TRADE_LABEL[t], text }];
  });
  // 공정 이름이 많으면 버튼이 폰 너비를 넘어서 둘까지만 버튼에 적는다 (전체는 기본정보에 있다)
  const consult = picked.length <= 2 ? `${picked.map((x) => x.label).join(" · ")} 상담 받기` : `고른 공정 ${picked.length}개 상담 받기`;
  const when = p.when.kind === "date" && p.when.start
    ? ` · ${md(p.when.start)}${p.when.end && p.when.end !== p.when.start ? ` ~ ${md(p.when.end)}` : ""}`
    : p.when.kind === "movein" && p.when.start ? ` · ${md(p.when.start)}` : "";
  const bySpace = p.spaces.map((s) => ({ s, files: p.photos.filter((ph) => ph.space_id === s.id) })).filter((x) => x.files.length);

  return (
    <main id="main" className="mj-wrap mj-main">
      <div className="mj-split">
        <div className="mj-col">
          <section className="mj-panel" aria-labelledby="now-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
            <ProjectTrack now={step} />
            <span className="mj-eyebrow">지금 단계</span>
            <h1 id="now-h" className="mj-h2">프로젝트를 만들었어요</h1>
            <p className="mj-sub">{p.photos.length || p.plans.length ? "답과 사진 · 도면을" : "답을"} 저장했어요. 예상 공정표와 표준견적서는 상담에서 볼 수 있어요.</p>
            <div className="mj-btn-row">
              {picked.length ? <Link href={`/consult?project=${p.id}`} className="mj-btn mj-btn-pri">{consult}</Link> : null}
              <Link href={`/projects/${p.id}/vendors`} className="mj-btn mj-btn-sec">가견적 받을 업체 보기</Link>
              <Link href="/projects/p1" className="mj-btn mj-btn-sec">예시 프로젝트로 흐름 보기</Link>
            </div>
          </section>

          {bySpace.length || p.plans.length ? (
            <section aria-labelledby="ph-h" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h2 id="ph-h" className="mj-h2">올린 사진 · 도면</h2>
              {bySpace.map(({ s, files }) => (
                <div key={s.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <h3 className="mj-h3">{s.name} <span className="mj-small mj-num">{files.length}장</span></h3>
                  <ul className="mj-thumbs" style={{ padding: 0 }}>
                    {files.map((f, i) => (
                      <li key={f.file_id} className="mj-thumb-li">
                        <a className="mj-thumb" href={`/api/files/${f.file_id}`} target="_blank" rel="noreferrer">
                          <img src={`/api/files/${f.file_id}`} alt={`${s.name} 사진 ${i + 1}`} />
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              {p.plans.length ? (
                <p className="mj-small">도면 {p.plans.map((fid, i) => <a key={fid} href={`/api/files/${fid}`} target="_blank" rel="noreferrer" style={{ marginRight: 8 }}>{i + 1}번 보기</a>)}</p>
              ) : null}
            </section>
          ) : null}
        </div>

        <aside className="mj-aside mj-panel" aria-labelledby="info-h">
          <h2 id="info-h" className="mj-h3">기본정보</h2>
          <dl className="mj-kv">
            <dt>지역</dt><dd>{p.region}</dd>
            <dt>집 종류</dt><dd>아파트{p.built_year ? ` · ${p.built_year}년 준공` : ""}</dd>
            <dt>평수</dt><dd className="mj-num">{sizeLabel(p.size)}{p.balcony_ext ? " · 발코니 확장" : ""}</dd>
            <dt>시기</dt><dd>{WHEN_LABEL[p.when.kind]}{when}</dd>
            <dt>집 상태</dt><dd>{p.occupied ? "살면서 공사" : "빈집"}</dd>
            <dt>예산</dt><dd>{budgetLabel(p.budget)}</dd>
            {picked.map((x) => <Fragment key={x.t}><dt>{x.label}</dt><dd>{x.text}</dd></Fragment>)}
            <dt>사진 · 도면</dt><dd>사진 {p.photos.length}장 · {p.plans.length ? `도면 ${p.plans.length}개` : "도면 없음"}</dd>
          </dl>
          <p className="mj-tiny">만든 날 {md(dateSeoul(p.created_at))}</p>
        </aside>
      </div>
    </main>
  );
}

/** 실제 프로젝트의 예상 공정표 · 표준견적서 화면. 상담에서 보여 주므로 상담으로 잇는다 (진행 현황과 같은 안내) */
export function SeeInConsult({ id, title }: { id: string; title: string }) {
  return (
    <main id="main" className="mj-wrap mj-main">
      <section className="mj-panel" aria-labelledby="ic-h" style={{ maxWidth: 640 }}>
        <h1 id="ic-h" className="mj-h2">{title}</h1>
        <p className="mj-sub">예상 공정표와 표준견적서는 상담에서 볼 수 있어요.</p>
        <div className="mj-btn-row">
          <Link href={`/consult?project=${id}`} className="mj-btn mj-btn-pri">상담에서 보기</Link>
          <Link href={`/projects/${id}`} className="mj-btn mj-btn-sec">진행 현황으로</Link>
        </div>
      </section>
    </main>
  );
}

/** 실제 프로젝트에서 아직 API가 없는 단계 화면 */
export function NotConnected({ id }: { id: string }) {
  return (
    <main id="main" className="mj-wrap mj-main">
      <section className="mj-panel" aria-labelledby="nc-h" style={{ maxWidth: 640 }}>
        <h1 id="nc-h" className="mj-h2">아직 연결 전이에요</h1>
        <p className="mj-sub">이 단계는 아직 이 프로젝트에 연결되지 않았어요. 예시 프로젝트에서 어떻게 보이는지 볼 수 있어요.</p>
        <div className="mj-btn-row">
          <Link href={`/projects/${id}`} className="mj-btn mj-btn-pri">진행 현황으로</Link>
          <Link href="/projects/p1" className="mj-btn mj-btn-sec">예시 프로젝트 보기</Link>
        </div>
      </section>
    </main>
  );
}

"use client";
// 자재 단계 · 정리 (v10 matStep · setMatFull · summaryText · copySummary · finish).
import { useEffect, useRef, useState } from "react";
import { type Cat, manwon, priceText, STYLES, TIERS } from "@/components/v2/data";
import { bot, F, quick, toast } from "@/components/v2/engine";
import { autoPick, fillPicks, matOf, scopeCats, setStep } from "@/components/v2/flow";
import { matSrcs, Photo } from "@/components/v2/photo";
import { DATA, S, useV2 } from "@/components/v2/store";
import { MatCard } from "./MatCard";
import { listReset, loadMok, M, redraw } from "./state";

export async function matStep() {
  await loadMok(); // 목공 처음 자재(등급별)를 알아야 추천을 맞출 수 있다
  setStep("materials");
  if (!M.cardId) autoPick();
  else fillPicks();
  M.full = false;
  M.cat = M.cat && scopeCats().some((c) => c.id === M.cat) ? M.cat : scopeCats()[0].id;
  listReset();
  const id = ++M.cardId;
  redraw(true);
  await bot(`${TIERS[S.tier]}으로 골라 뒀어요. 바꿀 것만 눌러 주세요.`, <MatCard key={`mat${id}`} id={id} />);
  quick([
    ["다 골랐어요", () => finish()],
    ["추천 비교해 주세요", () => F.askCompare(M.cat)],
    ["자재 크게 보기", () => setMatFull(true)],
  ]);
  if (matchMedia("(max-width: 760px)").matches) setMatFull(true);
}

/** 자재 고르기 전용 화면: 대화 속 카드를 화면 전체로 띄운다. 닫으면 대화의 그 자리로 돌아온다 */
export function setMatFull(on: boolean) {
  if (!M.cardId || M.full === !!on) return;
  M.full = !!on;
  redraw();
}

/** 자재 화면 모듈 변수를 처음으로 (처음부터 누를 때) */
export function resetMaterials() {
  M.cardId = 0;
  M.cat = null;
  M.full = false;
  listReset();
}

export function summaryText() {
  const st = STYLES.find((s) => s.id === S.style);
  const lines = [
    "[믿집 인테리어 정리]",
    [
      st ? `스타일 ${st.ko}` : null,
      S.info.pyeong ? `${S.info.pyeong}평` : null,
      S.info.region || null,
      S.info.living === "living" ? "살면서 공사" : S.info.living === "vacant" ? "빈집" : null,
      S.budget ? `예산 ${manwon(S.budget)}` : null,
      TIERS[S.tier],
    ]
      .filter(Boolean)
      .join(" / "),
    "",
  ];
  for (const c of scopeCats()) {
    const m = DATA.materials.find((x) => x.id === S.picks[c.id]);
    lines.push(`- ${c.ko}: ${m ? `${m.brand} ${m.name} (${priceText(m.price)})` : "아직 안 골랐어요"}`);
  }
  lines.push("", "가격은 자재값이고 실측 뒤 달라질 수 있어요.");
  return lines.join("\n");
}

function Swatch({ c }: { c: Cat }) {
  const m = matOf(S.picks[c.id]);
  if (!m)
    return (
      <div className="sw">
        <div className="sw-empty">{c.ko}</div>
        <span><em>{c.ko}</em>아직이에요</span>
      </div>
    );
  return (
    <div className="sw">
      <Photo srcs={matSrcs(m)} alt={m.name} />
      <span><em>{c.ko}</em>{m.name}</span>
    </div>
  );
}

function FinishCard({ toQuote }: { toQuote: boolean }) {
  useV2();
  const [fb, setFb] = useState<string | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (fb != null) ta.current?.select();
  }, [fb]);
  const cats = scopeCats();
  const st = STYLES.find((s) => s.id === S.style);
  const copy = () => {
    const t = summaryText();
    const fallback = () => {
      setFb(t);
      toast("글이 선택됐어요. 복사해 주세요");
    };
    try {
      navigator.clipboard.writeText(t).then(() => toast("요약을 복사했어요. 업체에게 붙여 넣어 보내세요"), fallback);
    } catch {
      fallback();
    }
  };
  return (
    <div className="card">
      <div>
        <h3>고른 내용</h3>
        <p className="muted">{[st?.ko, TIERS[S.tier], S.info.pyeong ? `${S.info.pyeong}평` : null, `${cats.length}개 공정`].filter(Boolean).join(" · ")}</p>
      </div>
      <details className="fin-mats">
        <summary>{`고른 자재 ${cats.filter((c) => S.picks[c.id]).length}개 보기`}</summary>
        <div className="swatches">{cats.map((c) => <Swatch key={c.id} c={c} />)}</div>
      </details>
      <div className="row">
        {toQuote ? null : <button type="button" className="btn btn-pri" onClick={() => F.quoteStep()}>표준견적서 보기</button>}
        <button type="button" className="btn" onClick={copy}>요약 복사</button>
        <button type="button" className="btn-text" onClick={() => F.askReview()}>
          <span className="spark" aria-hidden="true">✦</span>총평 받기
        </button>
      </div>
      {fb != null ? <textarea ref={ta} className="copy-fallback" readOnly rows={6} aria-label="요약 글" value={fb} /> : null}
      <p className="muted">가격은 자재값이고 실측 뒤 달라질 수 있어요.</p>
    </div>
  );
}

export async function finish(toQuote = false) {
  setMatFull(false);
  setStep("done");
  redraw();
  await bot(null, <FinishCard toQuote={toQuote} />);
  if (toQuote) return F.quoteStep();
  quick([
    ["표준견적서 보기", () => F.quoteStep()],
    ["공정표 보기", () => F.schedStep()],
    ["자재 다시 고르기", () => matStep()],
  ]);
}

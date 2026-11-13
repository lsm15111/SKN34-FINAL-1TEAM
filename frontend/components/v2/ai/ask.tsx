"use client";
// AI 상담 (v10 askClaude · askAboutStyle · askAboutMat · askCompare · askPhotos · askReview · agentAnswer · nextButton).
// 질문 · 고객 상태 · 자료만 서버(/v2/ask)에 보낸다. 지시문 · 입구 관문 · 숫자 검사는 서버가 한다.
// AI 답 메시지는 글이 바뀌는 말풍선(live) 하나로 두고, 끝나면 근거 · 다음 버튼 · '보드에 담았어요'를 붙인다.
import { useState } from "react";
import { CAT, type Material, type Style } from "../data";
import { addMsg, bot, busy, F, live, me, type MsgHandle, quick, refreshFeed } from "../engine";
import { recommend, STEP_NAMES, stepFn } from "../flow";
import { DATA, S } from "../store";
import { quoteBody } from "../doc/api";
import { materialsFor, profileOf } from "./context";
import { type AskOut, localClaude, runAsk, toImageBlock } from "./llm";
import { cleanMarks, nextStepOf } from "./route";
import { ragSources } from "./Sources";
import { type After, claudeTools } from "./tools";

type Bub = { text: string; typing: boolean };
type Live = { use: () => Bub; set: (b: Bub) => void };

function AiBubble({ lv }: { lv: Live }) {
  const b = lv.use();
  return (
    <div className="bubble ai">
      {b.typing ? (
        <span className="typing">
          <i />
          <i />
          <i />
        </span>
      ) : (
        b.text
      )}
    </div>
  );
}

/** 방금 붙인 메시지로 내린다 (v10 el.scrollIntoView nearest) */
function scrollLast() {
  setTimeout(() => {
    const ms = document.querySelectorAll(".msgs .msg");
    ms[ms.length - 1]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, 60);
}

/** 단계 이름으로 그 단계를 열 수 있는지 (v10 STEP_FN[id]) */
const hasStep = (id: string) => (id === "guide" ? !!F.guideStep : !!(STEP_NAMES[id] && F[STEP_NAMES[id]]));

function NextBtn({ step, ko }: { step: string; ko: string }) {
  const [done, setDone] = useState(false);
  return (
    <p className="next-btn">
      <button
        type="button"
        className="btn"
        disabled={done}
        onClick={() => {
          setDone(true);
          stepFn(step)();
        }}
      >
        {`${ko} 열기 →`}
      </button>
    </p>
  );
}
function nextButton(t: string, opened?: string) {
  const n = nextStepOf(t);
  if (!n || n.step === opened || !hasStep(n.step)) return null;
  return <NextBtn step={n.step} ko={n.ko} />;
}

/* 질문 종류: 서버 입구 관문(팀 의도 분류)이 정한 것 */
const INTENT_KO: Record<string, string> = { orchestrator: "일반 안내", trade: "도배 · 목공 상담", quote_explanation: "견적 · 공사비", schedule: "공정 순서 · 기간" };

type AskErr = { code?: string; name?: string; message?: string; text?: string };
function errMsg(e: AskErr) {
  return e?.code === "rate_limited" || e?.code === "too_many_attempts"
    ? "질문이 많아요. 잠시 뒤 다시 물어봐 주세요."
    : e?.code === "cancelled" || e?.name === "AbortError"
      ? e.text || "질문을 멈췄어요."
      : e?.message
        ? `답을 만들지 못했어요. ${e.message}`
        : "답을 만들지 못했어요. 다시 물어봐 주세요.";
}

/** 서버 숫자 검사로 뺀 문장이 있으면 이유를 접어서 보인다 */
function droppedNote(el: MsgHandle, dropped: string[]) {
  if (!dropped.length) return;
  el.append(
    <details className="srcs">
      <summary>{`확인 안 된 문장 ${dropped.length}개를 뺐어요`}</summary>
      <ul>{dropped.map((d, i) => <li key={i}>{d}</li>)}</ul>
    </details>,
  );
}

export async function askClaude(q: string, { label, images, withPhotos }: { label?: string; images?: boolean; withPhotos?: boolean } = {}) {
  if (busy.asking) return;
  // 기다리기 전에 먼저 잡아 둔다: 빠르게 두 번 보내도 질문이 겹치지 않게
  const ctl = new AbortController();
  busy.asking = ctl;
  refreshFeed();
  if (label) {
    if (!S.typed) {
      S.typed = true;
      F.collapseRail?.();
    }
    me(label);
  }
  const local = await localClaude();
  if (!local) {
    if (busy.asking === ctl) busy.asking = null;
    refreshFeed();
    if (!ctl.signal.aborted) await bot("지금은 AI 답변을 쓸 수 없어요. 버튼으로 이어서 진행해 주세요.");
    return;
  }
  if (ctl.signal.aborted) return;
  const lv = live<Bub>({ text: "", typing: true });
  const el = addMsg("bot", <AiBubble lv={lv} />);
  scrollLast();
  const applied: string[] = [], after: After = {};
  let out: AskOut | null = null, shown = "";
  const show = (t: string) => {
    shown = t;
    lv.set({ text: t, typing: false });
  };
  try {
    const sendPhotos = images || (withPhotos && (S.photos.length || S.refs.length));
    const files = sendPhotos ? [...S.photos, ...S.refs].map((p) => p.file).slice(0, 2) : [];
    const imgs: string[] = [];
    for (const f of files) {
      try {
        imgs.push(await toImageBlock(f));
      } catch {}
    }
    const body = { kind: "chat" as const, message: q, profile: profileOf(), quote: quoteBody(), materials: materialsFor(q), images: imgs };
    out = await runAsk(body, claudeTools(applied, after), ctl.signal);
    show(cleanMarks(out.text));
  } catch (err) {
    show(errMsg(err as AskErr));
  } finally {
    if (busy.asking === ctl) busy.asking = null;
    refreshFeed();
  }
  if (ctl.signal.aborted) return; // '처음부터'로 끊긴 질문은 새 대화에 아무것도 붙이지 않는다
  if (out?.gate === "out") {
    quick([
      ["표준견적서 받기", () => stepFn("quote")()],
      ["무엇을 물어볼 수 있어요?", () => askClaude("믿집 상담에서 무엇을 물어볼 수 있어요?")],
    ]);
    return;
  }
  if (out) droppedNote(el, out.dropped);
  const src = ragSources(out);
  if (src) el.append(src);
  const nb = nextButton(shown, after.step);
  if (nb) el.append(nb);
  if (applied.length) el.append(<p className="applied">{"✓ 보드에 담았어요 · " + [...new Set(applied)].join(" · ")}</p>);
  const it = out?.intent;
  if (!images && it && it.confidence >= 0.7 && INTENT_KO[it.label]) el.append(<p className="route-chip muted">{`질문 종류: ${INTENT_KO[it.label]}`}</p>);
  // 이어 물을 질문: 서버가 답할 수 있는지 검색해 본 것만 보낸다 (없으면 버튼을 띄우지 않는다)
  const sug = images ? [] : out?.suggest || [];
  if (sug.length) quick(sug.map((x) => [x.text, () => askClaude(x.text)] as [string, () => void]));
  if (after.step && hasStep(after.step)) stepFn(after.step)();
}

export function askAboutStyle(st: Style) {
  return askClaude(`'${st.ko}' 스타일을 우리 집 조건에 맞춰 설명해 줘. 장점, 주의할 점, 이 스타일에 어울리는 믿집 자재 2~3개(이름으로)를 알려 줘.`, { label: `${st.ko}, 우리 집에 어때요?` });
}
export function askAboutMat(m: Material) {
  const same = DATA.materials.filter((x) => x.cat === m.cat && x.id !== m.id).map((x) => x.name).join(", ");
  return askClaude(`믿집 자료의 '${m.brand} ${m.name}'(id ${m.id})이 우리 집에 맞는지 알려 줘. 같은 ${CAT[m.cat]?.ko} 후보(${same})와 비교해 어떤 사람에게 좋은지, 실측 때 물어볼 것 하나도.`, { label: `${m.name}, 괜찮을까요?` });
}
export function askCompare(cat: string) {
  F.setMatFull?.(false);
  const r = recommend(cat).map((m) => `${m.name}(id ${m.id})`).join(", ");
  return askClaude(`${CAT[cat]?.ko} 추천 3가지 ${r}를 비교해서 각각 어떤 집에 좋은지와 내 조건이면 무엇이 좋을지 알려 줘.`, { label: `${CAT[cat]?.ko} 추천 비교` });
}
export function askPhotos() {
  return askClaude("올린 사진을 보고 지금 집 상태에서 눈에 띄는 점과, 공사 범위나 자재를 고를 때 참고할 점을 알려 줘. 참고 사진이 있으면 어떤 스타일에 가까운지도.", { label: "사진 보고 조언해 주세요", images: true });
}
export function askReview() {
  return askClaude("지금까지 고른 스타일 · 등급 · 자재 조합을 보고 서로 잘 어울리는지, 바꾸면 좋을 것, 견적 받기 전에 확인할 것을 짧게 정리해 줘.", { label: "총평해 주세요" });
}

/** 에이전트 공통 (견적 설명 · 공정표 상담이 부른다). 지시문 · 계산 · 숫자 검사는 서버가 한다.
    실패하면 "설명을 만들지 못했어요" */
export async function agentAnswer({ label, ask, kind, quote, plan }: {
  label?: string | null;
  ask: string;
  kind: "quote_explanation" | "schedule";
  quote?: unknown;
  plan?: unknown;
}) {
  if (busy.asking) return;
  const ctl = new AbortController();
  busy.asking = ctl;
  refreshFeed();
  if (label) me(label);
  const local = await localClaude();
  if (ctl.signal.aborted) return;
  const lv = live<Bub>({ text: "", typing: true });
  const el = addMsg("bot", <AiBubble lv={lv} />);
  scrollLast();
  const fail = "설명을 만들지 못했어요. 계산 결과는 견적서에서 그대로 볼 수 있어요.";
  if (!local) {
    if (busy.asking === ctl) busy.asking = null;
    refreshFeed();
    lv.set({ text: fail, typing: false });
    return;
  }
  const after: After = {};
  let out: AskOut | null = null;
  try {
    out = await runAsk({ kind, message: ask, quote, plan }, [], ctl.signal);
  } catch {
    out = null;
  } finally {
    if (busy.asking === ctl) busy.asking = null;
    refreshFeed();
  }
  if (ctl.signal.aborted) return;
  lv.set({ text: out ? cleanMarks(out.text) : fail, typing: false });
  if (out) droppedNote(el, out.dropped);
  const src = ragSources(out);
  if (src) el.append(src);
  return { text: out?.text || "", after, cons: out?.cons ?? null, failed: !out || out.failed };
}

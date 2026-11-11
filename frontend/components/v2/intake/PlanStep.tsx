"use client";
// 5-2. 도면 (v10 planStep · openPlanPicker · pp9Apply · qtyCard · pickInFlow · 보드 '도면으로 수량').
// 평면도 목록과 수량은 백엔드(/mvp/plans · /mvp/plans/{id}/qty)가 만든다. 화면은 받은 값을 보여 주기만 한다.
import { errorText } from "@/lib/backend/client";
import { useEffect, useRef, useState } from "react";
import { flashBoard } from "../Board";
import { PLANS } from "../data";
import { bot, F, me, openOverlay } from "../engine";
import { setStep } from "../flow";
import { asset, S, touch, useV2 } from "../store";
import {
  fetchQty,
  loadPlans,
  type PlanBrief,
  planById,
  planGuess,
  type PlanQty,
  plansState,
  PP9_BANDS,
  pp9Area,
  pp9Band,
  pp9Fmt,
  pp9Guess,
  pp9Kinds,
  pp9ScopeKo,
  pp9Sub,
  pp9Title,
  rollsOf,
} from "./plans";

type PickOpts = { expanded: boolean };
type OnPick = (p: PlanBrief, o: PickOpts) => void;

/** 백엔드 수량을 받아 오는 작은 훅 */
function useQty(id: string, expanded: boolean, kinds: string[] | null) {
  const [r, setR] = useState<{ key: string; q?: PlanQty; err?: string } | null>(null);
  const key = `${id}|${expanded}|${kinds?.join(",") ?? ""}`;
  useEffect(() => {
    let on = true;
    fetchQty(id, expanded, kinds).then(
      (q) => on && setR({ key, q }),
      (e) => on && setR({ key, err: errorText(e) }),
    );
    return () => {
      on = false;
    };
    // kinds는 key에 들어 있다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return r && r.key === key ? r : null;
}

/* ---------- 도면 고르기 겹창 ---------- */
function PlanOne({ p, onPick, close, back }: { p: PlanBrief; onPick?: OnPick; close: () => void; back: () => void }) {
  const [expanded, setExpanded] = useState(S.plan?.id === p.id ? S.plan.expanded !== false : true);
  const [big, setBig] = useState(false);
  // 공간 목록은 수량 응답(spaces)에서 읽는다
  const r = useQty(p.id, true, null);
  const rooms = (r?.q?.spaces || []).filter((s) => s.kind !== "balcony" && s.kind !== "utility");
  return (
    <div className="pp9-one">
      <div className="pp9-left">
        <button type="button" className="pp9-big" aria-label="도면 크게 보기" aria-pressed={big} onClick={() => setBig(!big)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={asset(p.img) ?? undefined} alt={`${pp9Title(p)} 평면도`} />
        </button>
        <p className="muted pp9-zoom">도면을 누르면 크게 보여요.</p>
      </div>
      <div className="pp9-right">
        <dl className="pp9-facts">
          <dt>단지</dt>
          <dd>{p.name}</dd>
          <dt>지역</dt>
          <dd>{p.region}</dd>
          <dt>타입</dt>
          <dd>{p.type}</dd>
          <dt>면적</dt>
          <dd>{`전용 ${p.excl_m2 ?? "-"}㎡ · 공급 ${p.supply_m2}㎡(${p.supply_py}평)`}</dd>
          <dt>구조</dt>
          <dd>{pp9Sub(p)}</dd>
        </dl>
        <div className="pp9-rooms">
          <b>
            {`도면에서 읽은 공간 ${rooms.length}곳`}
            <small className="muted"> · 안쪽 길이(벽 두께 뺌)</small>
          </b>
          {r?.err ? <p className="err">{r.err}</p> : !r ? <p className="muted">불러오는 중이에요…</p> : null}
          <ul>
            {rooms.map((s) => (
              <li key={s.id}>
                <span>{s.ko}</span>
                <span className="pp9-num">
                  {`${pp9Fmt(s.w_m)} × ${pp9Fmt(s.d_m)}m`}
                  {s.sure === "low" ? <em> 추정</em> : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
        {p.has_ext ? (
          <label className="chk pp9-ext">
            <input type="checkbox" checked={expanded} onChange={(e) => setExpanded(e.target.checked)} />
            발코니를 확장했어요
            <small className="muted"> (대부분의 집이 확장했어요. 도면의 점선 부분)</small>
          </label>
        ) : (
          <p className="muted">확장 전 기본형 도면이에요. 발코니를 확장했다면 실측 때 늘어난 만큼 더해요.</p>
        )}
        <p className="muted">{`출처: ${p.src}${p.stage ? " · 사업시행인가 단계 도면이라 실제 준공 평면과 다를 수 있어요" : " 공고 평면도"}. 치수는 벽 가운데 기준이라 안쪽 길이로 바꿔 계산해요.`}</p>
        <div className="row">
          <button
            type="button"
            className="btn btn-pri"
            onClick={() => {
              close();
              onPick?.(p, { expanded });
            }}
          >
            이 도면이 우리 집이에요
          </button>
          <button type="button" className="btn" onClick={back}>목록으로</button>
        </div>
      </div>
    </div>
  );
}

function PlanPicker({ onPick, close }: { onPick?: OnPick; close: () => void }) {
  const [band, setBand] = useState(pp9Guess());
  const [q, setQ] = useState("");
  const [cur, setCur] = useState<PlanBrief | null>(null);
  const [plans, setPlans] = useState<PlanBrief[] | null>(plansState.list);
  const [err, setErr] = useState<string | null>(null);
  const x = useRef<HTMLButtonElement>(null);
  const inp = useRef<HTMLInputElement>(null);
  const curRef = useRef(cur);
  curRef.current = cur;
  useEffect(() => {
    if (!plans)
      loadPlans().then(
        (ls) => setPlans(ls),
        (e) => setErr(errorText(e)),
      );
    (inp.current ?? x.current)?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (curRef.current) setCur(null);
        else close();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const match = (p: PlanBrief) => (band === "all" || pp9Band(p) === band) && (!q || `${p.name} ${p.region} ${p.type}`.replace(/\s/g, "").includes(q.replace(/\s/g, "")));
  const reg = (S.info?.region || "").split(/\s+/).filter(Boolean);
  const hit = (p: PlanBrief) => reg.filter((r) => p.region.includes(r)).length; // 지역 말이 많이 맞을수록 위
  const ls = (plans || []).filter(match).sort((a, b) => hit(b) - hit(a) || Number(a.excl_m2 ?? 0) - Number(b.excl_m2 ?? 0));
  return (
    <div
      className="sheet-bg lk-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="sheet lk-sheet pp9-sheet" role="dialog" aria-modal="true" aria-labelledby="pp9-t">
        <div className="lk-head">
          <h3 id="pp9-t">{cur ? pp9Title(cur) : "우리 단지 도면 찾기"}</h3>
          <button ref={x} type="button" className="x" aria-label="닫기" onClick={close}>×</button>
        </div>
        <div className="lk-body pp9-body">
          {cur ? (
            <PlanOne key={cur.id} p={cur} onPick={onPick} close={close} back={() => setCur(null)} />
          ) : (
            <>
              <p className="muted">{S.info?.pyeong ? `입력한 ${S.info.pyeong}평에 가까운 도면부터 보여 드려요.` : "단지 이름으로 찾거나 평형대로 골라 보세요."}</p>
              <input
                ref={inp}
                className="inp pp9-q"
                type="search"
                placeholder="단지 이름이나 지역 (예: 청라, 효천, 나주)"
                aria-label="단지 이름이나 지역"
                value={q}
                onChange={(e) => {
                  const v = e.target.value;
                  setQ(v);
                  if (v.trim() && band !== "all") setBand("all"); // 이름으로 찾을 땐 평형대를 풀어 줌
                }}
              />
              <div className="chips" role="group" aria-label="평형대">
                {PP9_BANDS.map(([b, ko]) => (
                  <button key={b} type="button" className="chip" aria-pressed={band === b} onClick={() => setBand(b)}>{ko}</button>
                ))}
              </div>
              <p className="muted pp9-count" aria-live="polite">{ls.length ? `도면 ${ls.length}개` : ""}</p>
              {err ? <p className="err">{err}</p> : !plans ? <p className="muted">불러오는 중이에요…</p> : null}
              <ul className="pp9-grid">
                {ls.length ? (
                  ls.map((p) => (
                    <li key={p.id}>
                      <button type="button" className="pp9-card" aria-current={S.plan?.id === p.id} onClick={() => setCur(p)}>
                        <span className="pp9-ph">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={asset(p.img) ?? undefined} alt="" loading="lazy" />
                        </span>
                        <span className="pp9-cap">
                          <b>{pp9Title(p)}</b>
                          <span>{p.region}</span>
                          <span className="pp9-num">{pp9Area(p)}</span>
                          <small>{pp9Sub(p)}</small>
                        </span>
                      </button>
                    </li>
                  ))
                ) : plans ? (
                  <li className="pp9-none">
                    <p>맞는 도면이 없어요.</p>
                    <p className="muted">단지 이름을 줄여 찾거나, 평형대를 &apos;전체&apos;로 바꿔 보세요. 도면이 없으면 도면 파일을 올리거나 비슷한 구조로 고를 수 있어요.</p>
                  </li>
                ) : null}
              </ul>
              <p className="pp9-src">LH · iH 입주자 모집공고 · 분양 카탈로그와 서울시 정비사업 정보몽땅에 공개된 평면도예요. 같은 단지 · 같은 타입이어도 발코니 확장이나 구조 변경으로 다를 수 있어요.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function openPlanPicker({ onPick }: { onPick?: OnPick } = {}) {
  openOverlay((close) => <PlanPicker onPick={onPick} close={close} />);
}

/* 고른 도면을 상태에 넣는다 (평형이 비었으면 공급 평형) */
export function pp9Apply(p: PlanBrief, o: PickOpts) {
  S.plan = { kind: "apt", id: p.id, name: pp9Title(p), url: asset(p.img) ?? undefined, expanded: o.expanded };
  if (!S.info.pyeong) S.info.pyeong = p.supply_py;
  touch();
  flashBoard();
}

/* ---------- 도면 수량 카드 ---------- */
function QtyCard({ p, expanded: ex0 = true, next = false }: { p: PlanBrief; expanded?: boolean; next?: boolean }) {
  const [done, setDone] = useState(false);
  const [expanded, setExpanded] = useState(ex0);
  const [kinds] = useState(() => pp9Kinds());
  const [scopeKo] = useState(() => pp9ScopeKo());
  const r = useQty(p.id, expanded, kinds);
  useEffect(() => {
    if (S.plan?.id === p.id && S.plan.expanded !== expanded) {
      S.plan.expanded = expanded;
      touch();
    }
  }, [expanded, p.id]);
  const t = r?.q;
  const tile = (k: string, v: string, s?: string) => (
    <div className="pp9-tile" key={k}>
      <span>{k}</span>
      <b className="pp9-num">{v}</b>
      {s ? <small>{s}</small> : null}
    </div>
  );
  return (
    <div className={`card pp9-qty${done ? " done" : ""}`}>
      <div className="pp9-qh">
        <b>{pp9Title(p)}</b>
        <span className="muted">{`${pp9Area(p)} · ${!p.has_ext ? "기본형 도면" : expanded ? "발코니 확장" : "발코니 확장 안 함"} · 범위 ${scopeKo}`}</span>
      </div>
      {p.has_ext ? (
        <div className="pp9-opts">
          <label className="chk">
            <input type="checkbox" checked={expanded} disabled={done} onChange={(e) => setExpanded(e.target.checked)} />
            발코니 확장
          </label>
        </div>
      ) : null}
      {!r ? (
        <p className="muted">수량을 계산하는 중이에요…</p>
      ) : r.err || !t ? (
        <p className="err">{r.err}</p>
      ) : (
        <>
          <div className="pp9-tiles">
            {tile("벽지 바를 면적", `${pp9Fmt(t.paper_m2)}㎡`, `벽 ${pp9Fmt(t.wall_m2)} · 천장 ${pp9Fmt(t.ceiling_m2)}㎡`)}
            {tile("벽지 (실크)", `${rollsOf(t, "silk")}롤`, "폭 1.06m · 한 롤 약 16.5㎡")}
            {tile("벽지 (합지)", `${rollsOf(t, "hapji")}롤`, "폭 0.53m · 한 롤 약 6.6㎡")}
            {tile("초배지", `${pp9Fmt(t.primer_m2)}㎡`, "벽지 밑에 바르는 종이")}
            {tile("천장 몰딩", `${pp9Fmt(t.molding_m)}m`, `2.4m짜리 ${t.molding_pcs}개`)}
            {tile("걸레받이", `${pp9Fmt(t.base_m)}m`, `2.4m짜리 ${t.base_pcs}개`)}
            {tile("방문", `${t.doors}개`, `문선 ${pp9Fmt(t.casing_m)}m`)}
          </div>
          <details className="pp9-more">
            <summary>공간별로 보기</summary>
            <div className="tbl">
              <table>
                <thead>
                  <tr>{["공간", "안쪽 크기(벽 두께 뺌)", "벽", "천장", "몰딩", "걸레받이"].map((x) => <th key={x}>{x}</th>)}</tr>
                </thead>
                <tbody>
                  {t.spaces.filter((s) => s.papered).map((s) => (
                    <tr key={s.id}>
                      <td>
                        {s.ko}
                        {s.kind === "kitchen" ? <small className="muted"> 절반</small> : null}
                        {s.sure === "low" ? <em className="pp9-low"> 추정</em> : null}
                      </td>
                      <td className="num">{`${pp9Fmt(s.w_m)} × ${pp9Fmt(s.d_m)}m`}</td>
                      <td className="num">{`${pp9Fmt(s.wall_m2)}㎡`}</td>
                      <td className="num">{t.ceiling ? `${pp9Fmt(s.ceiling_m2)}㎡` : "-"}</td>
                      <td className="num">{`${pp9Fmt(s.molding_m)}m`}</td>
                      <td className="num">{`${pp9Fmt(s.base_m)}m`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">{kinds ? `상담에서 고른 범위(${scopeKo})만 셌어요. 욕실 · 발코니 · 다용도실은 벽지를 바르지 않아 뺐어요.` : "욕실 · 발코니 · 다용도실은 벽지를 바르지 않아 뺐어요."}</p>
          </details>
          <details className="pp9-more">
            <summary>이렇게 계산했어요</summary>
            <ul className="pp9-assume">{t.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            {t.low.length ? <p className="muted">{`도면 글씨가 작아 그림 비율로 추정한 곳: ${t.low.join(", ")}`}</p> : null}
          </details>
        </>
      )}
      <p className="pp9-note">실측 전 어림이에요. 업체가 실측할 때 방마다 다시 재요.</p>
      {next ? (
        <div className="row">
          <button
            className="btn btn-pri"
            type="button"
            disabled={done}
            onClick={() => {
              setDone(true);
              me("자재 고르기");
              F.matStep();
            }}
          >
            자재 고르기
          </button>
          <button
            className="btn-text"
            type="button"
            disabled={done}
            onClick={() =>
              openPlanPicker({
                onPick: (np, no) => {
                  setDone(true);
                  pickInFlow(np, no);
                },
              })
            }
          >
            다른 도면 고르기
          </button>
        </div>
      ) : null}
    </div>
  );
}

/* 상담 흐름에서 고름 → 수량 카드 */
async function pickInFlow(p: PlanBrief, o: PickOpts) {
  pp9Apply(p, o);
  me(`${pp9Title(p)} 도면`);
  await bot(`${pp9Title(p)} 도면으로 필요한 자재 수량을 계산했어요.`, <QtyCard p={p} expanded={o.expanded} next />);
}

/** 내 집 보드 '도구'의 도면으로 수량 */
export async function planQtyTool() {
  if (S.plan?.kind === "apt") {
    const p = await loadPlans().then(() => planById(S.plan?.id), () => null);
    if (p) {
      await bot("고른 도면의 필요 수량이에요.", <QtyCard p={p} expanded={S.plan?.expanded !== false} />);
      return;
    }
  }
  openPlanPicker({
    onPick: (p, o) => {
      pp9Apply(p, o);
      bot(`${pp9Title(p)} 도면으로 필요한 자재 수량을 계산했어요.`, <QtyCard p={p} expanded={o.expanded} />);
    },
  });
}

/* ---------- 도면 단계 ---------- */
function PlanCard() {
  useV2();
  const [done, setDone] = useState(false);
  const [file, setFile] = useState<{ url?: string; name: string } | null>(null);
  const [note] = useState(() => {
    const g = planGuess();
    return (g && !S.plan ? `${S.info.pyeong}평에 맞춰 ${PLANS.find((x) => x.id === g)?.ko}를 골라 뒀어요. ` : "") + "베이: 햇빛 드는 쪽에 나란히 있는 방 · 거실 수예요.";
  });
  const [count, setCount] = useState(plansState.list?.length ?? null);
  useEffect(() => {
    if (count == null) loadPlans().then((ls) => setCount(ls.length), () => {});
  }, [count]);
  const pressedId = S.plan ? S.plan.id : planGuess();
  return (
    <div className={`card${done ? " done" : ""}`}>
      <div className="drop pp9-find">
        <b>우리 단지 도면</b>
        <button
          type="button"
          className="btn btn-pri btn-sm"
          disabled={done}
          onClick={() =>
            openPlanPicker({
              onPick: (pl, o) => {
                setDone(true);
                pickInFlow(pl, o);
              },
            })
          }
        >
          {count != null ? `도면 찾기 (${count}개)` : "도면 찾기"}
        </button>
        <p>단지 · 타입을 고르면 벽지 · 몰딩 · 걸레받이 · 방문 수량을 바로 계산해요.</p>
      </div>
      <div className="drop">
        <b>평면도</b>
        <label className="btn btn-sm" htmlFor="up-plan">파일 올리기</label>
        <input
          type="file"
          id="up-plan"
          accept="image/*,application/pdf"
          className="sr"
          disabled={done}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const url = f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined;
            S.plan = { kind: "file", name: f.name, url };
            setFile({ url, name: f.name });
            touch();
            flashBoard();
          }}
        />
        <div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {file ? file.url ? <img src={file.url} alt="올린 도면" style={{ maxHeight: 180, borderRadius: 8 }} /> : <p className="muted">{file.name}</p> : null}
        </div>
      </div>
      <div className="field">
        <span className="lbl">없으면 비슷한 구조</span>
        <div className="plans" role="group" aria-label="비슷한 구조">
          {PLANS.map((p) => (
            <button
              key={p.id}
              type="button"
              className="plan"
              aria-pressed={pressedId === p.id}
              disabled={done}
              onClick={() => {
                S.plan = { kind: "type", id: p.id, name: p.ko };
                setFile(null);
                touch();
                flashBoard();
              }}
            >
              <svg className="plan-svg" viewBox="0 0 160 100" aria-hidden="true" dangerouslySetInnerHTML={{ __html: p.svg }} />
              <span>
                <b>{p.ko}</b>
                <br />
                <small>{p.sub}</small>
              </span>
            </button>
          ))}
        </div>
        <p className="plan-note">{note}</p>
      </div>
      <div className="row">
        <button
          className="btn btn-pri"
          type="button"
          disabled={done}
          onClick={() => {
            const g = planGuess();
            if (!S.plan && g) {
              const gp = PLANS.find((x) => x.id === g);
              if (gp) S.plan = { kind: "type", id: gp.id, name: gp.ko };
              touch();
            }
            setDone(true);
            me(S.plan ? (S.plan.kind === "file" ? "도면 올림" : S.plan.name) : "다음");
            F.matStep();
          }}
        >
          자재 고르기
        </button>
        <button
          className="btn-text gray"
          type="button"
          disabled={done}
          onClick={() => {
            setDone(true);
            me("건너뛸게요");
            F.matStep();
          }}
        >
          건너뛰기
        </button>
      </div>
    </div>
  );
}
export async function planStep() {
  setStep("plan");
  loadPlans().catch(() => {});
  await bot("도면이 있나요?", <PlanCard />);
}

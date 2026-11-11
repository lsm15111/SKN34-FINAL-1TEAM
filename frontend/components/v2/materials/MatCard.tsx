"use client";
// 자재 카드 (v10 refreshMat · matCardEl · matListEl · matRowEl · addCatBox). 대화에 한 번 붙이고 touch()마다 다시 그린다.
// 크게 보기(mat-full)는 가장 최근 카드에만 걸린다. 가격은 자재 판매가 글(priceText)만 보인다.
import { useEffect, useLayoutEffect, useRef } from "react";
import { CAT, CATS, type Material, priceText, SORTS, TIER_ORDER, TIERS, unitShort } from "@/components/v2/data";
import { clearQuick, F, me } from "@/components/v2/engine";
import { priceFlags, recommend, scopeCats, sortMats } from "@/components/v2/flow";
import { matSrcs, Photo } from "@/components/v2/photo";
import { DATA, S, useV2 } from "@/components/v2/store";
import { addCat, dropCat, goCat, recWhy, selectMat, setAllTier } from "./actions";
import { MokPanel } from "./MokPanel";
import { openCompare, openSheet } from "./Sheets";
import { CMP, keepSlots, LIST_STEP, M, redraw } from "./state";

function MatTile({ m }: { m: Material }) {
  const on = S.picks[m.cat] === m.id;
  const why = recWhy(m);
  return (
    <div
      className="mcard"
      role="button"
      tabIndex={0}
      aria-pressed={on}
      aria-label={`${m.name} ${priceText(m.price)} ${on ? "고름" : "고르기"}`}
      onClick={() => selectMat(m)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectMat(m);
        }
      }}
    >
      <Photo srcs={matSrcs(m)} alt={m.name}>
        <span className="sel" aria-hidden="true">✓</span>
      </Photo>
      <div className="in">
        <span className="brand">{m.brand}</span>
        <span className="nm">{m.name}</span>
        {why ? <span className="why">{why}</span> : null}
        <div className="meta">
          <span className="price">{priceText(m.price, false)}</span>
          <span className={`tier tier-${m.tier}`}>{TIERS[m.tier]}</span>
        </div>
        <div className="meta">
          <span className="flag">{priceFlags(m) || (m.price?.unit ? `/ ${m.price.unit.replace(/\(.*\)/, "").trim()}` : "")}</span>
          <button
            type="button"
            className="btn-text"
            style={{ minHeight: 40 }}
            onClick={(e) => {
              e.stopPropagation();
              openSheet(m);
            }}
          >
            자세히
          </button>
        </div>
      </div>
    </div>
  );
}

function MatRow({ m }: { m: Material }) {
  const on = S.picks[m.cat] === m.id;
  const u = unitShort(m);
  return (
    <div className="mrow" aria-current={on}>
      <div
        className="mrow-main"
        role="button"
        tabIndex={0}
        aria-label={`${m.name} 자세히`}
        onClick={() => openSheet(m)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openSheet(m);
          }
        }}
      >
        <Photo srcs={matSrcs(m)} alt={m.name} />
        <div className="tx">
          <div className="mtop">
            <span className={`tier tier-${m.tier}`}>{TIERS[m.tier]}</span>
            <span className="brand">{m.brand}</span>
          </div>
          <div className="nm">{m.name}</div>
          {(m.tags || []).length ? <div className="tags">{m.tags.slice(0, 2).map((t) => <span key={t} className="tag">{t}</span>)}</div> : null}
        </div>
        <div className="pr">
          <b>{priceText(m.price, false)}</b>
          {u ? <small>{"/ " + u}</small> : null}
        </div>
      </div>
      <button type="button" className="pick" aria-pressed={on} aria-label={on ? `${m.name} 고름` : `${m.name} 고르기`} onClick={() => selectMat(m)}>
        {on ? "✓" : "+"}
      </button>
    </div>
  );
}

/** 추천 밖 자재 목록: 등급 거르기 · 꼬리표 · 찾기 · 정렬 · 더 보기 */
function MatList({ rest }: { rest: Material[] }) {
  const cnt: Record<string, number> = { all: rest.length };
  for (const t of TIER_ORDER) cnt[t] = rest.filter((m) => m.tier === t).length;
  if (M.filter !== "all" && !cnt[M.filter]) M.filter = "all";
  const picked = rest.find((m) => S.picks[m.cat] === m.id);
  const q = M.query.trim().toLowerCase();
  const tagCnt: Record<string, number> = {};
  for (const m of rest) for (const t of m.tags || []) tagCnt[t] = (tagCnt[t] || 0) + 1;
  if (M.tag && !tagCnt[M.tag]) M.tag = null;
  const list = sortMats(
    rest.filter(
      (m) => m !== picked && (M.filter === "all" || m.tier === M.filter) && (!M.tag || (m.tags || []).includes(M.tag)) && (!q || `${m.brand} ${m.name}`.toLowerCase().includes(q)),
    ),
    M.sort,
  );
  const shown = list.slice(0, M.show);
  const run = (v: string) => {
    M.query = v;
    M.show = LIST_STEP;
    redraw();
  };
  return (
    <section className="mlist-wrap" aria-label="다른 자재">
      <div className="sec-head">
        <h4>다른 자재<small className="num">{`${rest.length}개`}</small></h4>
        <select
          className="sort"
          aria-label="정렬"
          value={M.sort}
          onChange={(e) => {
            M.sort = e.target.value;
            redraw();
          }}
        >
          {Object.entries(SORTS).map(([k, ko]) => <option key={k} value={k}>{ko}</option>)}
        </select>
      </div>
      {rest.length > 8 ? (
        <input
          key={M.cat ?? ""}
          className="inp msearch"
          type="search"
          placeholder="이름 · 브랜드로 찾기"
          aria-label="자재 찾기"
          defaultValue={M.query}
          enterKeyHint="search"
          onInput={(e) => {
            if (!(e.nativeEvent as InputEvent).isComposing) run(e.currentTarget.value);
          }}
          onCompositionEnd={(e) => run(e.currentTarget.value)}
        />
      ) : null}
      <div className="seg" role="group" aria-label="등급으로 보기">
        {([["all", "전체"], ...TIER_ORDER.map((t) => [t, TIERS[t]])] as [string, string][])
          .filter(([k]) => cnt[k])
          .map(([k, ko]) => (
            <button
              key={k}
              type="button"
              aria-pressed={M.filter === k}
              onClick={() => {
                M.filter = k;
                M.show = LIST_STEP;
                redraw();
              }}
            >
              {ko}
              <span className="n">{cnt[k]}</span>
            </button>
          ))}
      </div>
      {Object.keys(tagCnt).length > 1 ? (
        <div className="tagrow" role="group" aria-label="꼬리표로 거르기">
          {Object.entries(tagCnt)
            .sort((a, b) => b[1] - a[1])
            .map(([t, n]) => (
              <button
                key={t}
                type="button"
                className="chip sm"
                aria-pressed={M.tag === t}
                onClick={() => {
                  M.tag = M.tag === t ? null : t;
                  M.show = LIST_STEP;
                  redraw();
                }}
              >
                {t}
                <span className="n">{n}</span>
              </button>
            ))}
        </div>
      ) : null}
      {picked ? (
        <div className="pinned">
          <span className="lbl">고른 자재</span>
          <div className="mlist"><MatRow m={picked} /></div>
        </div>
      ) : null}
      {shown.length ? (
        <div className="mlist">{shown.map((m) => <MatRow key={m.id} m={m} />)}</div>
      ) : (
        <p className="muted empty">맞는 자재가 없어요. 거르기를 풀어 보세요.</p>
      )}
      {list.length > shown.length ? (
        <button
          type="button"
          className="btn more"
          onClick={() => {
            M.show += LIST_STEP;
            redraw();
          }}
        >
          {`${Math.min(LIST_STEP, list.length - shown.length)}개 더 보기`}
          <small>{`${shown.length}/${list.length}`}</small>
        </button>
      ) : null}
    </section>
  );
}

function AddCatBox() {
  const have = new Set(scopeCats().map((c) => c.id));
  return (
    <div className="addbox">
      <span className="lbl">더할 공정</span>
      <div className="chips">
        {CATS.filter((c) => !have.has(c.id)).map((c) => (
          <button key={c.id} type="button" className="chip sm" onClick={() => addCat(c.id)}>{"+ " + c.ko}</button>
        ))}
      </div>
    </div>
  );
}

function MatBody({ cat }: { cat: string }) {
  if (cat === "carpentry") return <MokPanel />;
  const c = CAT[cat];
  const recs = keepSlots(cat, recommend(cat));
  const recIds = new Set(recs.map((m) => m.id));
  const rest = DATA.materials.filter((m) => m.cat === cat && !recIds.has(m.id));
  const cmp = CMP[cat] || [];
  return (
    <div className="mat-body" role="tabpanel">
      <div className="sec-head">
        <h4>추천<small>{c.what}</small></h4>
        <span className="head-acts">
          {recs.length > 1 ? (
            <button type="button" className="btn-text" onClick={() => openCompare(cmp.length > 1 ? cmp : recs.map((m) => m.id))}>표로 비교</button>
          ) : null}
          {recs.length > 1 ? (
            <button type="button" className="btn-text" onClick={() => F.askCompare(cat)}>
              <span className="spark" aria-hidden="true">✦</span>AI 비교
            </button>
          ) : null}
        </span>
      </div>
      {recs.length ? <div className="mgrid">{recs.map((m) => <MatTile key={m.id} m={m} />)}</div> : <p className="muted">준비 중이에요.</p>}
      {cmp.length ? (
        <div className="cmp-bar">
          <span>{`비교에 ${cmp.length}개 담음`}</span>
          <button type="button" className="btn btn-sm" disabled={cmp.length < 2} onClick={() => openCompare(cmp)}>표로 보기</button>
          <button
            type="button"
            className="btn-text gray"
            onClick={() => {
              CMP[cat] = [];
              redraw();
            }}
          >
            비우기
          </button>
        </div>
      ) : null}
      {rest.length ? <MatList rest={rest} /> : null}
    </div>
  );
}

/** 대화에 붙는 자재 카드. id가 가장 최근 카드면 크게 보기 · Esc를 맡는다 */
export function MatCard({ id }: { id: number }) {
  useV2();
  const ref = useRef<HTMLDivElement>(null);
  const cur = id === M.cardId;
  const full = cur && M.full;
  const was = useRef(full);

  /* 크게 보기: 몸 스크롤 잠금(v10 body.mat-open) · 열면 맨 위로 · 닫으면 그 자리로 */
  useEffect(() => {
    const el = ref.current;
    if (full) {
      if (el) el.scrollTop = 0;
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      was.current = true;
      return () => {
        document.body.style.overflow = prev;
      };
    }
    if (was.current) {
      was.current = false;
      el?.scrollIntoView({ block: "nearest" });
    }
  }, [full]);
  /* 크게 보기에서 공정 탭이 머리 아래에 붙도록 머리 높이를 넘긴다 */
  useLayoutEffect(() => {
    const el = ref.current, hd = el?.querySelector<HTMLElement>(".mat-head");
    if (el && hd && full) el.style.setProperty("--mat-head-h", hd.offsetHeight + "px");
  });
  useEffect(() => {
    if (!cur) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && M.full && !document.querySelector(".sheet-bg")) F.setMatFull(false);
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [cur]);

  const cats = scopeCats();
  if (!M.cat || !cats.some((c) => c.id === M.cat)) M.cat = cats[0].id;
  const cat = M.cat;
  const n = cats.filter((x) => S.picks[x.id]).length;
  const c = CAT[cat];
  const idx = cats.findIndex((x) => x.id === cat);
  const next = cats[idx + 1];
  return (
    <div ref={ref} className={"card mat" + (full ? " mat-full" : "")} role={full ? "dialog" : undefined} aria-label={full ? "자재 고르기" : undefined}>
      <div className="mat-head">
        <h3>자재<small className="num">{`${n}/${cats.length}`}</small></h3>
        <div className="seg lg" role="group" aria-label="전체 등급">
          {TIER_ORDER.map((t) => (
            <button key={t} type="button" aria-pressed={S.tier === t} onClick={() => setAllTier(t)}>{TIERS[t]}</button>
          ))}
        </div>
        <button type="button" className="btn btn-sm mat-expand" onClick={() => F.setMatFull(!full)}>{full ? "대화로 돌아가기" : "크게 보기"}</button>
      </div>
      <div className="tabs" role="tablist" aria-label="공정">
        {cats.map((x) => (
          <button key={x.id} type="button" role="tab" aria-selected={x.id === cat} onClick={() => goCat(x.id)}>
            {S.picks[x.id] ? <span className="ck" aria-label="고름">✓</span> : null}
            {x.ko}
          </button>
        ))}
        {cats.length < CATS.length ? (
          <button
            type="button"
            className="add"
            aria-expanded={M.add}
            onClick={() => {
              M.add = !M.add;
              redraw();
            }}
          >
            + 공정
          </button>
        ) : null}
      </div>
      {M.add ? <AddCatBox /> : null}
      <MatBody key={cat} cat={cat} />
      <div className="mat-foot">
        <button type="button" className="btn-text gray" onClick={() => dropCat(cat)}>{`${c.ko} 빼기`}</button>
        {next ? <button type="button" className="btn btn-sm mat-next" onClick={() => goCat(next.id)}>{`${next.ko} →`}</button> : null}
        <button
          type="button"
          className={"btn btn-pri btn-sm" + (next ? "" : " mat-next")}
          onClick={() => {
            clearQuick();
            me("다 골랐어요");
            F.finish(true);
          }}
        >
          다 골랐어요 · 견적 보기
        </button>
      </div>
    </div>
  );
}

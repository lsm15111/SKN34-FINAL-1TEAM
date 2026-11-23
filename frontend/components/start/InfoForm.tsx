"use client";
// 기본 정보(C02 · C03 · D11): '어떤 공사 · 우리 집 · 희망' 세 묶음. 웹 ≥1024는 오른쪽 '넣은 내용' 요약 칸.
// - 손님: 답은 이 기기에만 저장돼요(mj_guest_v3). '표준견적서 보기'를 누르면 가입 없이 /start/standard로 가요(N1 A).
// - 로그인한 고객: 같은 답으로 POST /projects(Idempotency-Key = 기기 답의 key) → 내 공사 표준견적서로 가요.
// - 고치기(?edit=): 그 공사 값을 채우고 PATCH /projects/{id}(첫 요청 뒤에는 서버가 409 locked, 화면은 C50).
//   대화 안 '우리 집 정보' 창(/projects/{id}/home)은 같은 고치기에 after(저장 뒤 갈 곳: 대화) · focus(처음 초점 칸)를 줘요.
//   고치기에는 v4 첫 대화가 묻는 철거 범위 · 직접 할 일 칸도 있어요(같은 PATCH, 칩 이름 · 순서는 첫 대화 · 서버 project/diy.py와 같아요).
// - 검사는 '표준견적서 보기'를 누를 때 한 번(I6 B): 맨 위 '고칠 칸이 n개 있어요' + 칸 아래 오류 + 첫 틀린 칸으로 옮겨 가요.
// - 금액은 서버 계산 엔진이 세요. 여기서는 단위만 바꿔요(평 → ㎡ 넣기 도움 · 만 원 → 원).
// - 칸 아래 도움말 · 저장 안내 · 아래 띠 요약 줄은 두지 않아요(11-19 사용자 결정: 화면을 가볍게).
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead, type Crumb } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { Segmented } from "@/components/ui/Segmented";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { DEMOLITION } from "@/lib/api/assistant";
import type { Region } from "@/lib/api/project";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { dateShort } from "@/lib/format";
import {
  DIY_CHIPS, DIY_FIELD_ID, EMPTY_DRAFT, ERROR_NAME, ERROR_ORDER, FACES, checkDraft, chipsFor, diyFromPicks, diyPicks, onChips, placeText, roomsOf, scopeOf,
  spaceLabel, summaryRows, toEditBody, toHomeInfo, type Demolition, type Face, type InfoDraft, type InfoErrors, type RoomRule, type SpaceKind,
} from "@/lib/guest/info";
import { clearGuest, draftOf, readGuest, writeGuest } from "@/lib/guest/store";
import { DateSheet } from "./DateSheet";
import { PyeongSheet } from "./PyeongSheet";
import { RegionSheet } from "./RegionSheet";
import s from "./info.module.css";

export type InfoMode = "guest" | "member" | "edit";
/** 처음 초점을 줄 칸(오류 칸 + 방 개수 · 시작 희망일 · 고치기의 철거 범위 · 직접 할 일) */
export type InfoFocus = keyof InfoErrors | "rooms" | "start" | "demolition" | "diy";

const FIELD_ID: Record<keyof InfoErrors, string> = {
  spaces: "inf-spaces", faces: "inf-faces", region: "inf-region", area: "inf-area", occupied: "inf-occupied", grade: "inf-grade", budget: "inf-budget",
};
const FOCUS_ID: Record<InfoFocus, string> = { ...FIELD_ID, rooms: "inf-rooms", start: "inf-start", demolition: "inf-demolition", diy: DIY_FIELD_ID };

/** 칸 묶음(id)의 첫 입력 · 단추에 초점을 주고 가운데로 보여요 */
function focusBox(id: string) {
  const box = document.getElementById(id);
  const el = box?.matches("input, button") ? box : box?.querySelector<HTMLElement>("input:not([disabled]), button");
  el?.focus();
  box?.scrollIntoView({ block: "center" });
}

export function InfoForm({ regions, roomRule, today, mode, projectId, initial, mock, crumbs, after, focus }: {
  regions: Region[];
  /** 방 개수 칸 범위 · 평형 기본값 표(서버 계산 엔진) */
  roomRule: RoomRule;
  /** 웹 이동 경로(마지막 줄은 이 화면) */
  crumbs: Crumb[];
  /** 오늘(서울 날짜, 서버 값) */
  today: string;
  mode: InfoMode;
  projectId?: string;
  /** 고치기: 그 공사의 저장된 값 */
  initial?: InfoDraft;
  /** 개발 예시(NEXT_PUBLIC_MJ_MOCK) */
  mock: boolean;
  /** 고치기: 저장 뒤 갈 곳(대화 안 창이면 대화로 돌아가 창을 닫아요). 없으면 표준견적서. 있으면 단추 이름은 '저장' */
  after?: string;
  /** 처음 초점을 줄 칸(보드의 '우리 집' 줄을 눌러 열었을 때) */
  focus?: InfoFocus;
}) {
  const router = useRouter();
  const [d, setD] = useState<InfoDraft>(initial ?? EMPTY_DRAFT);
  const [ready, setReady] = useState(mode === "edit");
  const [dirty, setDirty] = useState(false);
  const [tried, setTried] = useState(false);
  const [errors, setErrors] = useState<InfoErrors>({});
  const [sheet, setSheet] = useState<null | "pyeong" | "region" | "date">(null);
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  /** 준비 중 칩(목공 · 아파트 밖 주거)을 눌렀을 때 그 자리에 보일 한 줄: 지금 되는 범위로 이끌어요(QA r6 M4 · M18) */
  const [soon, setSoon] = useState<{ at: "trade" | "house"; text: string } | null>(null);
  const sumRef = useRef<HTMLDivElement>(null);
  const budgetRef = useRef<HTMLInputElement>(null);

  // 이 기기에 둔 답을 이어서 채워요(고치기는 그 공사 값)
  useEffect(() => {
    if (mode === "edit") return;
    const g = readGuest();
    if (g) setD(draftOf(g));
    setReady(true);
  }, [mode]);
  // 바꿀 때마다 이 기기에 저장해요(손님 · 새 공사). 고치기는 저장하지 않아요
  useEffect(() => { if (ready && dirty && mode !== "edit") writeGuest(d); }, [d, ready, dirty, mode]);
  // 한 번 눌러 본 뒤로는 고칠 때마다 오류를 다시 맞춰요(칸을 떠날 때는 검사하지 않아요)
  useEffect(() => { if (tried) setErrors(checkDraft(d)); }, [d, tried]);

  const set = (patch: Partial<InfoDraft>) => { setD((p) => ({ ...p, ...patch })); setDirty(true); setFormErr(null); };

  const focusField = (k: InfoFocus) => focusBox(FOCUS_ID[k]);
  // 보드에서 고른 칸으로 처음 초점을 옮겨요(창이 열리며 제목에 준 초점 뒤에)
  useEffect(() => {
    if (!focus) return;
    const t = window.setTimeout(() => focusBox(FOCUS_ID[focus]), 60);
    return () => window.clearTimeout(t);
  }, [focus]);

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (busy) return;
    const err = checkDraft(d);
    setErrors(err);
    setTried(true);
    setFormErr(null);
    const first = ERROR_ORDER.find((k) => err[k]);
    if (first) { requestAnimationFrame(() => focusField(first)); return; }
    if (mode === "guest") {
      writeGuest(d);
      router.push("/start/standard");
      return;
    }
    setBusy(true);
    try {
      if (mode === "edit" && projectId) {
        if (!mock) await call("PATCH", `/projects/${encodeURIComponent(projectId)}`, toEditBody(d));
        // 대화 안 창이면 창을 닫고 대화로(이 창 주소를 대화 주소로 바꿔요). 저장(PATCH)이 보드 · 집 정보 카드를 다시 읽게 해요
        if (after) router.replace(after, { scroll: false });
        else router.push(`/projects/${projectId}/standard`);
        router.refresh();
        return;
      }
      const g = writeGuest(d);
      if (mock) {
        const { MOCK_PROJECT } = await import("@/lib/mock/v3a/mode");
        clearGuest();
        router.push(`/projects/${d.scope === "partial" ? MOCK_PROJECT.part : MOCK_PROJECT.full}/standard`);
        return;
      }
      const p = await call<Schemas["ProjectOut"]>("POST", "/projects", toHomeInfo(d), { "Idempotency-Key": g.key });
      clearGuest();
      router.push(`/projects/${p.id}/standard`);
    } catch (er) {
      setFormErr(errorText(er));
      setBusy(false);
    }
  }

  const rooms = roomsOf(d, roomRule);
  const chips = chipsFor(rooms, roomRule);
  const on = onChips(d, chips);
  // 방 개수를 바꾸면 칩이 늘거나 줄어요. 새로 생긴 방 칩은 켜진 채로 와요
  const setRooms = (n: number) => {
    const next = chipsFor(n, roomRule);
    const added = next.filter((k) => !chips.includes(k));
    set({ rooms: n, ...scopeOf([...on, ...added], d.faces, next) });
  };

  const errKeys = ERROR_ORDER.filter((k) => errors[k]);
  const place = placeText(regions, d);
  const cta = after ? "저장" : d.scope === "partial" ? "부분 표준견적서 보기" : "표준견적서 보기";
  const ctaLabel = busy ? "저장하는 중" : cta;

  return (
    <>
      <Main>
      <PageHead title="기본 정보" crumbs={crumbs} />
      <div className={s.layout}>
        <form id="info-form" className={s.form} onSubmit={submit} noValidate aria-label="기본 정보">
          {tried && errKeys.length ? (
            <div ref={sumRef} className={s.summary} role="alert">
              <Icon name="error" size={18} />
              <p>고칠 칸이 {errKeys.length}개 있어요 · {errKeys.map((k) => ERROR_NAME[k]).join(" · ")}</p>
            </div>
          ) : null}

          <section className={s.group} aria-labelledby="g-what">
            <h2 id="g-what" className={s.grp}>어떤 공사</h2>
            <div className={s.cols}>
              <ChoiceChips legend="공사 종류" value="dobae" onChange={() => {}} onSoon={() => setSoon({ at: "trade", text: "목공은 준비 중이에요. 지금은 도배 견적만 받을 수 있어요." })} options={[{ value: "dobae", label: "도배" }, { value: "mokgong", label: "목공", soon: true }]} />
              {soon?.at === "trade" ? <p className={s.meta} role="status">{soon.text}</p> : null}
            </div>
          </section>

          <section className={s.group} aria-labelledby="g-home">
            <h2 id="g-home" className={s.grp}>우리 집</h2>
            <ChoiceChips legend="주거 종류" value="apt" onChange={() => {}} onSoon={() => setSoon({ at: "house", text: "지금은 아파트만 견적을 받을 수 있어요." })} options={[
              { value: "apt", label: "아파트" }, { value: "villa", label: "빌라 · 다세대", soon: true }, { value: "officetel", label: "오피스텔", soon: true }, { value: "house", label: "단독주택", soon: true },
            ]} />
            {soon?.at === "house" ? <p className={s.meta} role="status">{soon.text}</p> : null}
            <div className={s.f}>
              <p className={s.fl} id="inf-region-l">지역</p>
              <button id={FIELD_ID.region} type="button" className={errors.region ? `${s.pick} ${s.bad}` : s.pick} aria-labelledby="inf-region-l inf-region-v" aria-describedby={errors.region ? "inf-region-e" : undefined} aria-invalid={errors.region ? true : undefined} onClick={() => setSheet("region")}>
                <span id="inf-region-v" className={place ? undefined : s.ph}>{place || "지역 고르기"}</span>
                <Icon name="chevron-down" size={18} />
              </button>
              {errors.region ? <p id="inf-region-e" className={s.err}><Icon name="error" size={16} />{errors.region}</p> : null}
            </div>
          </section>

          <section className={s.group} aria-labelledby="g-area">
            <h2 id="g-area" className={s.fl}>면적</h2>
            <div className={s.cols}>
              <Segmented legend="면적 기준" hideLegend value={d.basis} onChange={(v) => set({ basis: v === "exclusive" ? "exclusive" : "supply" })} options={[{ value: "supply", label: "공급면적" }, { value: "exclusive", label: "전용면적" }]} />
              <Field id={FIELD_ID.area} label={`${d.basis === "exclusive" ? "전용" : "공급"}면적(㎡)`} hideLabel unit="㎡" num value={d.area} error={errors.area} maxLength={8}
                onChange={(e) => set({ area: e.target.value })} />
            </div>
            <div className={s.gh}>
              <Button variant="text" onClick={() => setSheet("pyeong")}>평으로 넣기</Button>
            </div>
            <div id={FOCUS_ID.rooms}>
              <ChoiceChips legend="방 개수" value={String(rooms)} onChange={(v) => setRooms(Number(v))}
                options={Array.from({ length: roomRule.max - roomRule.min + 1 }, (_, i) => { const n = roomRule.min + i; return { value: String(n), label: `${n}개` }; })} />
            </div>
            <div id={FIELD_ID.occupied}>
              <ChoiceChips legend="공사할 때 집은" value={d.occupied === null ? null : d.occupied ? "yes" : "no"} error={errors.occupied} onChange={(v) => set({ occupied: v === "yes" })}
                options={[{ value: "yes", label: "사는 중" }, { value: "no", label: "빈 집" }]} />
            </div>
          </section>

          <section className={s.group} aria-labelledby="g-where">
            <h2 id="g-where" className={s.grp}>도배할 곳</h2>
            <div id={FIELD_ID.spaces}>
              <ChoiceChips multiple legend="공간" value={on} error={errors.spaces} onChange={(v) => set(scopeOf(v as SpaceKind[], d.faces, chips))}
                options={chips.map((k) => ({ value: k, label: spaceLabel(k) }))} />
            </div>
            <div id={FIELD_ID.faces}>
              <ChoiceChips multiple legend="면" value={d.faces} error={errors.faces} onChange={(v) => set(scopeOf(on, v as Face[], chips))}
                options={FACES.map((x) => ({ value: x.key, label: x.label }))} />
            </div>
            {mode === "edit" ? (
              <div id={FOCUS_ID.demolition}>
                <ChoiceChips legend="철거 범위" value={d.demolition ?? null} onChange={(v) => set({ demolition: v as Demolition })}
                  options={DEMOLITION.map((x) => ({ value: x.key, label: x.label }))} />
              </div>
            ) : null}
          </section>

          <section className={s.group} aria-labelledby="g-want">
            <h2 id="g-want" className={s.grp}>희망</h2>
            <div className={s.cols}>
              <div className={s.f} id={FIELD_ID.grade}>
                <ChoiceChips legend="벽지" value={d.grade} error={errors.grade} onChange={(v) => set({ grade: v as InfoDraft["grade"] })} options={[{ value: "economy", label: "합지" }, { value: "basic", label: "실크" }]} />
              </div>
              <div className={s.f}>
                <Field ref={budgetRef} id={FIELD_ID.budget} label="예산" unit="만 원" num inputMode="numeric" value={d.budget} error={errors.budget} maxLength={7}
                  onChange={(e) => set({ budget: e.target.value })} />
                <ChoiceChips multiple legend="예산을 모르면" hideLegend value={d.budget.trim() ? [] : ["unknown"]} options={[{ value: "unknown", label: "아직 몰라요" }]}
                  onChange={(v) => (v.includes("unknown") ? set({ budget: "" }) : budgetRef.current?.focus())} />
              </div>
            </div>
          </section>

          <section className={s.group} aria-labelledby="inf-start-l">
            <div className={s.cols}>
              <div className={s.f}>
                <p className={s.fl} id="inf-start-l">공사 시작 희망일</p>
                <button id={FOCUS_ID.start} type="button" className={s.pick} aria-labelledby="inf-start-l inf-start-v" onClick={() => setSheet("date")}>
                  <span id="inf-start-v" className={d.start ? "mj-num" : s.ph}>{d.start ? dateShort(d.start, today) : "날짜 고르기"}</span>
                  <Icon name="chevron-down" size={18} />
                </button>
                {/* 예산 칸처럼 '아직 몰라요'는 날짜 칸 바로 아래(같은 묶음)에 둬요 */}
                <ChoiceChips multiple legend="시작일을 모르면" hideLegend value={d.start ? [] : ["unknown"]} options={[{ value: "unknown", label: "아직 몰라요" }]}
                  onChange={(v) => (v.includes("unknown") ? set({ start: null }) : setSheet("date"))} />
              </div>
            </div>
          </section>

          {mode === "edit" ? (
            <section className={s.group} aria-labelledby="g-diy">
              <h2 id="g-diy" className={s.grp}>직접 할 일</h2>
              <div id={FOCUS_ID.diy}>
                <ChoiceChips multiple legend="직접 할 일" hideLegend value={diyPicks(d.diy)} onChange={(v) => set({ diy: diyFromPicks(v, diyPicks(d.diy)) })}
                  options={DIY_CHIPS} />
              </div>
            </section>
          ) : null}

          {formErr ? <p className={s.formErr} role="alert"><Icon name="error" size={18} />{formErr}</p> : null}
        </form>

        <aside className={s.aside} aria-labelledby="inf-sum">
          <h2 id="inf-sum" className={s.eb}>넣은 내용</h2>
          <dl className={s.rows}>
            {summaryRows(d, { fullRegion: place, rooms }).map((r) => (
              <div key={r.label} className={s.row}>
                <dt>{r.label}{r.sub ? <span>{r.sub}</span> : null}</dt>
                <dd className="mj-num">{r.value || "—"}</dd>
              </div>
            ))}
          </dl>
          <Button type="submit" form="info-form" size="lg" block busy={busy}>{ctaLabel}</Button>
        </aside>
      </div>
      </Main>

      <div className={s.phoneBar}>
        <BottomBar>
          <Button type="submit" form="info-form" size="lg" busy={busy}>{ctaLabel}</Button>
        </BottomBar>
      </div>

      <PyeongSheet open={sheet === "pyeong"} basis={d.basis} onClose={() => setSheet(null)} onApply={(m2, basis) => { set({ area: m2, basis }); setSheet(null); }} />
      <RegionSheet open={sheet === "region"} regions={regions} value={{ sido: d.sido, sgg: d.sgg }} onClose={() => setSheet(null)} onApply={(p) => { set({ ...p, emd: "" }); setSheet(null); }} />
      <DateSheet open={sheet === "date"} value={d.start} today={today} onClose={() => setSheet(null)} onApply={(day) => { set({ start: day }); setSheet(null); }} />
    </>
  );
}

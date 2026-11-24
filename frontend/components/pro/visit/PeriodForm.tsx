"use client";
// 기간 답하기(V04 v_period 폰 · D14 d_period 웹) + 못 받아요 · 이유(V05 v_decline).
// 업체가 갈 수 있는 기간(+ 빼는 날)과 '고객이 고르면 바로 확정'을 보내요 → POST /vendor/visits/{vid}/window(멱등 키).
// 고객이 고를 수 있는 반나절 수는 계산 엔진이 세요: 고른 기간이 바뀌면 GET /vendor/visits/{vid}?start=&end=&excluded=의 open_count를 보여요(D14 '… 반나절 8칸').
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { Badge } from "@/components/ui/Badge";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { BigFigure } from "@/components/ui/Money";
import { OptionRow, Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import type { VendorVisitV3 } from "@/lib/api/vendor";
import { call, errorText } from "@/lib/backend/client";
import { dateSeoul, dueText, halfDayText, rangeText } from "@/lib/format";
import { DECLINE_LABEL } from "@/lib/labels";
import { MOCK } from "@/lib/mock/v3c/mode";
import { enc, newKey, send } from "../send";
import { LOC_NOTE } from "../text";
import { Eyebrow, Group, PhoneOnly, Row, Rows, Small, TwoCol, WebOnly } from "../ui/parts";
import { Switch } from "@/components/ui/Switch";
import { DiyFact, FactsKV, factLine, occ, VisitPhotos, visitTitle } from "./facts";
import { PeriodCalendar, PeriodLegend, type Period } from "./PeriodCalendar";
import s from "./visit.module.css";

const INSTANT_DESC = "켜면 고객이 고른 반나절은 열어 둔 다른 요청 기간에서 바로 빠져요. 끄면 한 번 더 수락해요.";
const PICK_NOTE = "고객이 7일 안에 고르지 않으면 이 기간이 풀려 다른 요청에 다시 열려요.";

export function PeriodForm({ v, now, openDecline }: { v: VendorVisitV3; now: string; openDecline?: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [p, setP] = useState<Period>({ start: v.window?.start ?? null, end: v.window?.end ?? null, excluded: v.window?.excluded ?? [] });
  const [instant, setInstant] = useState(v.window?.instant ?? v.instant_default ?? true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newKey);
  const [decline, setDecline] = useState(false);
  // ?decline=1(알림 · 작업함에서 바로 '못 받아요')은 그린 뒤에 열어요(처음 그릴 때 연 창은 개발 모드 두 번 그리기에서 바로 닫혀요)
  useEffect(() => { if (openDecline) setDecline(true); }, [openDecline]);
  const ready = !!(p.start && p.end);
  const sendLabel = ready ? `${rangeText(p.start!, p.end!)} 보내기` : "기간 보내기";
  const exText = p.excluded.length ? `${p.excluded.map((d) => `${Number(d.slice(8, 10))}일`).join(" · ")} 빼고` : null;
  const openCount = useOpenCount(v.id, p);
  const countText = openCount != null ? `고객이 고를 수 있는 반나절 ${openCount}칸` : null;

  async function sendWindow() {
    if (busy) return;
    if (!ready) { setErr(p.start ? "끝나는 날을 눌러 주세요." : "갈 수 있는 기간의 시작 · 끝을 눌러 주세요."); return; }
    setErr(null);
    setBusy(true);
    try {
      await send("POST", `/vendor/visits/${enc(v.id)}/window`, { start: p.start, end: p.end, excluded: p.excluded, instant }, { idem });
      toast.show("기간을 보냈어요. 고객이 날짜를 고르면 알림으로 알려 드려요.");
      router.push("/vendor?tab=waiting");
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  const sendBtn = (size: "lg" | "sm") => <Button size={size} onClick={sendWindow} busy={busy} aria-describedby={err ? "period-err" : undefined}>{busy ? "보내는 중" : sendLabel}</Button>;
  const declineBtn = (size: "lg" | "sm") => <Button size={size} variant="secondary" onClick={() => setDecline(true)} disabled={busy}>못 받아요</Button>;

  return (
    <>
      <Main>
        <PageHead
          title="기간 답하기"
          crumbs={[{ label: "작업함", href: "/vendor" }, { label: visitTitle(v) }]}
          desc={v.reply_due_at ? `${dueText(v.reply_due_at, { now })} 답해요` : undefined}
        />
        <TwoCol
          sideLabel="보낼 기간"
          sideWebOnly
          main={
            <>
              <WebOnly>
                <Group>
                  <div className={s.titleRow}><h2 className={s.vt}>{visitTitle(v)} · {occ(v)}</h2><Badge tone="now">새 실측 요청</Badge></div>
                  <FactsKV v={v} />
                  <DiyFact v={v} />
                  <Small>{LOC_NOTE}</Small>
                  <VisitPhotos v={v} />
                </Group>
              </WebOnly>
              <Group>
                <PhoneOnly>
                  <Eyebrow>{factLine(v)}</Eyebrow>
                  <DiyFact v={v} />
                  <Small>{LOC_NOTE}</Small>
                </PhoneOnly>
                <h2 className={s.calT}>갈 수 있는 기간</h2>
                <PeriodLegend />
                <PeriodCalendar
                  label="갈 수 있는 기간 고르기"
                  value={p}
                  onChange={(x) => { setP(x); setErr(null); }}
                  today={dateSeoul(now)}
                  wish={v.wish_start && v.wish_end ? { from: v.wish_start, to: v.wish_end } : null}
                  taken={v.taken}
                  month={p.start ?? v.wish_start}
                  wide
                />
                <Small>시작 · 끝을 누르고, 안 되는 날은 한 번 더 눌러요.</Small>
                {err ? <p id="period-err" className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
              </Group>
              <PhoneOnly>
                <Group>
                  <Switch label="고객이 고르면 바로 확정" desc={INSTANT_DESC} checked={instant} onChange={setInstant} />
                  <Small>{PICK_NOTE}</Small>
                </Group>
              </PhoneOnly>
            </>
          }
          side={
            <Group>
              <Eyebrow>보낼 기간</Eyebrow>
              <BigFigure size="mid" caption={[exText ?? (ready ? "빼는 날 없음" : null), countText].filter(Boolean).join(" · ") || undefined}>{ready ? rangeText(p.start!, p.end!, { weekday: true }) : "기간을 골라 주세요"}</BigFigure>
              <Switch label="고객이 고르면 바로 확정" desc={INSTANT_DESC} checked={instant} onChange={setInstant} />
              <Small>{PICK_NOTE}</Small>
              <div className={s.acts}>{declineBtn("sm")}{sendBtn("sm")}</div>
              <hr className={s.sep} />
              <Eyebrow>이미 잡힌 실측</Eyebrow>
              {v.taken.length ? (
                <Rows label="이미 잡힌 실측">
                  {v.taken.map((t) => (
                    <Row
                      key={`${t.visit_id}-${t.day}-${t.half}-${t.seat}`}
                      label={halfDayText(t.day, t.half)}
                      sub={t.kind === "hold" ? `${t.area_label} · 잡아 둠${t.hold_until ? ` · ${dueText(t.hold_until, { now })} 답해요` : ""}` : t.area_label}
                      value={<Badge tone={t.kind === "hold" ? "wait" : "ok"}>{t.kind === "hold" ? "수락할 차례" : "확정"}</Badge>}
                      href={t.kind === "hold" ? `/vendor/requests/${enc(t.visit_id)}` : undefined}
                    />
                  ))}
                </Rows>
              ) : <Small>아직 잡힌 실측이 없어요.</Small>}
              {/* CF-75: 색만으로 가리키지 않아요 */}
              <Small>{"'잡힘' 반나절은 고객이 고를 수 없어요."}</Small>
            </Group>
          }
        />
      </Main>
      <div className={s.phoneBar}>
        <BottomBar>{declineBtn("lg")}{sendBtn("lg")}</BottomBar>
      </div>
      <DeclineSheet open={decline} onClose={() => setDecline(false)} visitId={v.id} />
    </>
  );
}

type Why = keyof typeof DECLINE_LABEL;
/** 못 받아요 · 이유(V05). 이유 3가지는 지금 코드 그대로예요. 되돌릴 수 없어요 */
export function DeclineSheet({ open, onClose, visitId }: { open: boolean; onClose: () => void; visitId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [why, setWhy] = useState<Why | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newKey);
  async function go() {
    if (busy) return;
    if (!why) { setErr("못 받는 이유를 하나 골라 주세요."); return; }
    if (why === "other" && !note.trim()) { setErr("그 밖이면 이유를 한 줄로 적어 주세요."); return; }
    setBusy(true);
    try {
      await send("POST", `/vendor/visits/${enc(visitId)}/decline`, { code: why, note: why === "other" ? note.trim() : null }, { idem });
      toast.show("못 받는다고 고객에게 알렸어요.");
      onClose();
      router.push("/vendor?tab=done");
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }
  return (
    <Sheet
      open={open}
      onClose={() => !busy && onClose()}
      dismissible={!busy}
      title="이번 요청을 못 받는다고 할까요?"
      actions={<Button size="lg" block onClick={go} busy={busy}>{busy ? "보내는 중" : "못 받는다고 알리기"}</Button>}
    >
      <div role="radiogroup" aria-label="못 받는 이유" className={s.opts}>
        {(Object.keys(DECLINE_LABEL) as Why[]).map((k) => (
          <OptionRow key={k} selected={why === k} onClick={() => { setWhy(k); setErr(null); }}>{DECLINE_LABEL[k]}</OptionRow>
        ))}
      </div>
      {why === "other" ? <Field label="그 밖 이유" placeholder="그 밖이면 한 줄로 적어요" maxLength={200} value={note} onChange={(e) => { setNote(e.target.value); setErr(null); }} /> : null}
      {/* CF-13 */}
      <Small>고객에게 알리고, 고객은 다른 업체를 담을 수 있어요.</Small>
      {err ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
    </Sheet>
  );
}

/** 고른 기간으로 엔진이 센 '고객이 고를 수 있는 반나절' 수(저장하지 않는 읽기). 예시 모드 · 기간이 덜 골라졌으면 null */
function useOpenCount(visitId: string, p: Period): number | null {
  const [count, setCount] = useState<number | null>(null);
  // 기간 · 빼는 날을 글 하나로 묶어 바뀔 때만 다시 물어요
  const key = p.start && p.end ? [p.start, p.end, ...p.excluded].join("|") : "";
  useEffect(() => {
    if (MOCK || !key) { setCount(null); return; }
    const [start, end, ...excluded] = key.split("|");
    const qs = new URLSearchParams({ start, end });
    excluded.forEach((d) => qs.append("excluded", d));
    let live = true;
    const t = setTimeout(() => {
      call<VendorVisitV3>("GET", `/vendor/visits/${enc(visitId)}?${qs.toString()}`)
        .then((x) => { if (live) setCount(x.open_count ?? null); })
        .catch(() => { if (live) setCount(null); });
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [visitId, key]);
  return count;
}

"use client";
// 실측 견적서 올리기(V10 v_quote): 업체 양식 파일(PDF · 엑셀 · 사진) + 칸 4개(견적 금액 · 부가세 · 공사 기간 · 유효기간) + '포함됐나요?' 4가지.
// 공급가 · 부가세 · 합계는 계산 엔진이 만들어요: 임시 저장(PUT …/quote)한 값으로만 '믿집 계산'을 보여요(화면은 더하지 않아요).
// 금액 · 부가세를 바꾸면 잠시 뒤 임시 저장해서 다시 계산해요. 보내기 → PUT 뒤 POST …/quote/send(멱등 키). 확정된 견적서는 바뀌지 않아요.
// 실측 날 전에는 보낼 수 없어요(서버도 실측한 날이 오늘 뒤면 받지 않아요): 칸을 끄고 언제부터 되는지 위 안내 · 단추로 알려요(QA r6 M1).
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { CalcBox } from "@/components/ui/CalcBox";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { Field, SelectField } from "@/components/ui/Field";
import { FileDrop } from "@/components/ui/FileDrop";
import { Icon } from "@/components/ui/Icon";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";
import type { VendorQuoteBoard, VendorVisitV3 } from "@/lib/api/vendor";
import { errorText, type Schemas } from "@/lib/backend/client";
import { MOCK } from "@/lib/mock/v3c/mode";
import { dateSeoul, dateShort, dueText, halfDayText, won } from "@/lib/format";
import { enc, newKey, send, upload } from "../send";
import { VAT_MODE_LABEL } from "../text";
import { FileRow } from "@/components/ui/FileRow";
import { Eyebrow, Group, Lead, Row, Rows, Small } from "../ui/parts";
import { Segmented } from "@/components/ui/Segmented";
import { occ, visitTitle } from "../visit/facts";
import s from "./quote.module.css";

type QFile = Schemas["QuoteFileOut"];
type Draft = Schemas["QuoteDraftIn"];
type Vat = "included" | "excluded" | "exempt";
const DOC_OK = /\.(pdf|xlsx?|csv|jpe?g|png|heic|webp)$/i;
const WARRANTY = [{ value: "6", label: "6개월" }, { value: "12", label: "1년" }, { value: "24", label: "2년" }];
const digits = (v: string) => v.replace(/\D/g, "").slice(0, 10);
const money = (v: string) => (v ? Number(v).toLocaleString("ko-KR") : "");

export function QuoteForm({ v, board, now }: { v: VendorVisitV3; board: VendorQuoteBoard; now: string }) {
  const router = useRouter();
  const toast = useToast();
  const d = board.draft;
  const simplified = board.tax_kind === "simplified";
  // 간이과세는 서버가 부가세 방식을 보지 않고 낸 금액을 그대로 합계로 세요(included · 0%). 고르지 않게 '포함'으로 두고 간이 안내를 보여요
  // (추가 금액 ExtraForm과 같아요). 면세는 서버가 방식을 하나만 줘요
  const fixedVat: Vat | null = simplified ? "included" : board.vat_modes.length === 1 ? (board.vat_modes[0] as Vat) : null;
  const [files, setFiles] = useState<QFile[]>(d?.files ?? []);
  const [amount, setAmount] = useState(d?.entered_amount != null ? String(d.entered_amount) : "");
  const [vat, setVat] = useState<Vat | null>((fixedVat ?? (d?.vat_mode as Vat | null)) ?? null);
  const [days, setDays] = useState(d?.days != null ? String(d.days) : "");
  const [valid, setValid] = useState(d?.valid_until ?? "");
  const [incl, setIncl] = useState<string[]>([d?.incl_removal ? "removal" : "", d?.incl_waste ? "waste" : "", d?.paper_spec ? "spec" : "", d?.warranty_months ? "warranty" : ""].filter(Boolean));
  const [spec, setSpec] = useState(d?.paper_spec ?? "");
  const [warranty, setWarranty] = useState(d?.warranty_months ? String(d.warranty_months) : "12");
  const [calc, setCalc] = useState<{ amount: number | null; vat: string | null; supply: number | null; vatWon: number | null; total: number | null }>({ amount: d?.entered_amount ?? null, vat: d?.vat_mode ?? null, supply: d?.supply ?? null, vatWon: d?.vat ?? null, total: d?.total ?? null });
  const [err, setErr] = useState<Record<string, string | undefined>>({});
  const [busy, setBusy] = useState<"save" | "send" | null>(null);
  const [uploading, setUploading] = useState(false);
  const [idem] = useState(newKey);
  const amountRef = useRef<HTMLInputElement>(null);
  const daysRef = useRef<HTMLInputElement>(null);
  const validRef = useRef<HTMLInputElement>(null);
  const b = v.booked;
  const today = dateSeoul(now);
  /** 실측 날 전: 칸을 끄고 보내기를 막아요. 그 사이 할 수 있는 일은 채팅으로 고객과 시각 맞추기예요 */
  const early = b ? b.day > today : false;
  const chatHref = v.thread_id ? `/chat/${enc(v.thread_id)}` : null;
  /** 잠시 뒤 임시 저장(믿집 계산)이 실패했을 때 그 까닭(칸 아래 '잠시 뒤 …' 대신) */
  const [calcErr, setCalcErr] = useState<string | null>(null);

  const body = (): Draft => ({
    file_ids: files.map((f) => f.file_id),
    measured_on: b?.day ?? null,
    entered_amount: amount ? Number(amount) : null,
    vat_mode: vat,
    days: days ? Number(days) : null,
    valid_until: valid || null,
    incl_removal: incl.includes("removal") ? true : null,
    incl_waste: incl.includes("waste") ? true : null,
    paper_spec: incl.includes("spec") && spec.trim() ? spec.trim() : null,
    warranty_months: incl.includes("warranty") ? Number(warranty) : null,
  });
  async function save(): Promise<boolean> {
    const out = await send<VendorQuoteBoard>("PUT", `/vendor/visits/${enc(v.id)}/quote`, body());
    const dr = out?.draft;
    if (dr) setCalc({ amount: dr.entered_amount, vat: dr.vat_mode, supply: dr.supply, vatWon: dr.vat, total: dr.total });
    return true;
  }

  // 금액 · 부가세가 바뀌면 잠시 뒤 임시 저장 → 계산 엔진 값으로 '믿집 계산'을 바꿔요
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!amount || !vat) return;
    const t = setTimeout(() => { save().then(() => setCalcErr(null), (e) => setCalcErr(errorText(e))); }, 800);
    return () => clearTimeout(t);
  }, [amount, vat]);
  // 간이과세는 방식과 상관없이 같은 값이라(앞서 다른 방식으로 저장한 임시본도) 방식은 견주지 않아요
  const calcFresh = calc.amount != null && String(calc.amount) === amount && (simplified || calc.vat === vat) && calc.total != null;

  async function pick(list: File[]) {
    const room = board.files_max - files.length;
    if (room <= 0) { setErr((e) => ({ ...e, files: `파일은 ${board.files_max}개까지 올릴 수 있어요.` })); return; }
    const bad = list.find((f) => !DOC_OK.test(f.name));
    if (bad) { setErr((e) => ({ ...e, files: `${bad.name} · PDF · 엑셀 · 사진만 올릴 수 있어요.` })); return; }
    setErr((e) => ({ ...e, files: undefined }));
    setUploading(true);
    try {
      const got: QFile[] = [];
      for (const f of list.slice(0, room)) {
        const o = await upload("quote_doc", f);
        got.push({ file_id: o.id, filename: o.filename, content_type: o.content_type, size: o.size, sort: files.length + got.length });
      }
      setFiles((x) => [...x, ...got]);
    } catch (e) {
      setErr((x) => ({ ...x, files: errorText(e) }));
    } finally {
      setUploading(false);
    }
  }

  function check(): boolean {
    const e: Record<string, string> = {};
    if (!files.length) e.files = "견적서 파일을 올려 주세요.";
    if (!amount || Number(amount) <= 0) e.amount = "견적 금액을 원 단위로 넣어 주세요.";
    if (!vat) e.vat = "부가세를 어떻게 적었는지 골라 주세요.";
    if (!days || Number(days) < 1 || Number(days) > board.days_max) e.days = `공사 기간을 1~${board.days_max}일로 넣어 주세요.`;
    if (!valid) e.valid = "유효기간을 골라 주세요.";
    else if (valid < today) e.valid = "유효기간은 오늘 뒤로 골라 주세요.";
    setErr(e);
    if (e.amount) amountRef.current?.focus();
    else if (e.days) daysRef.current?.focus();
    else if (e.valid) validRef.current?.focus();
    return !Object.keys(e).length;
  }

  async function onSave() {
    if (busy) return;
    setBusy("save");
    try { await save(); toast.show("임시 저장했어요."); } catch (e) { setErr((x) => ({ ...x, form: errorText(e) })); } finally { setBusy(null); }
  }
  async function onSend() {
    if (busy || uploading || !check()) return;
    setBusy("send");
    try {
      await save();
      await send("POST", `/vendor/visits/${enc(v.id)}/quote/send`, undefined, { idem });
      toast.show("견적서를 보냈어요. 고객이 확정하면 알림으로 알려 드려요.");
      router.push("/vendor?tab=waiting");
    } catch (e) {
      setErr((x) => ({ ...x, form: errorText(e) }));
      setBusy(null);
    }
  }

  const due = board.quote_due_at; // 장부 기한 그대로(실측 확정 때 '다음 일' 기한은 실측 반나절이 끝나는 때라 달라요)
  return (
    <>
      <Main narrow>
        <PageHead title="실측 견적서 올리기" crumbs={[{ label: "작업함", href: "/vendor" }, { label: visitTitle(v), href: `/vendor/requests/${enc(v.id)}` }, { label: "실측 견적서" }]} />
        <Lead title={`${visitTitle(v)} · ${occ(v)}`} sub={[b ? `실측 ${halfDayText(b.day, b.half)}` : null, v.estimate_total != null ? `가견적 ${won(v.estimate_total)}` : null].filter(Boolean).join(" · ")} />
        {early && b ? (
          <Notice>{`${dateShort(b.day)} 실측 뒤에 올려요`}{due ? ` · ${dueText(due, { now })}` : ""}</Notice>
        ) : due ? <Small red>{dueText(due, { now })} 올려요 · 실측 + 3일</Small> : null}

        <fieldset className={s.lock} disabled={early}>
          <Group>
            <Eyebrow as="h2">견적서 파일</Eyebrow>
            {files.map((f) => (
              <FileRow
                key={f.file_id}
                name={f.filename}
                size={f.size}
                action={<Button variant="text" gray onClick={() => setFiles((x) => x.filter((y) => y.file_id !== f.file_id))} aria-label={`${f.filename} 빼기`}>빼기</Button>}
              />
            ))}
            <FileDrop kind="doc" label="견적서 파일 올리기" types="PDF · 엑셀 · 사진" busy={uploading} error={err.files} onFiles={pick} disabled={early} />
          </Group>

          <Group>
            <Field ref={amountRef} label={simplified ? "받을 금액" : "견적 금액"} unit="원" num inputMode="numeric" value={money(amount)} error={err.amount} onChange={(e) => { setAmount(digits(e.target.value)); setErr((x) => ({ ...x, amount: undefined })); }} />
            {fixedVat ? (
              <Small>{simplified ? "간이과세라 부가세를 따로 붙이지 않아요. 적은 금액이 고객이 보는 금액이에요." : `부가세 ${VAT_MODE_LABEL[fixedVat]}`}</Small>
            ) : (
              <>
                <Segmented legend="부가세" options={(board.vat_modes as Vat[]).map((m) => ({ value: m, label: VAT_MODE_LABEL[m] ?? m }))} value={vat} onChange={(x) => { setVat(x as Vat); setErr((e) => ({ ...e, vat: undefined })); }} />
                {err.vat ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err.vat}</p> : null}
              </>
            )}
            {calcFresh ? (
              <CalcBox tone="form" lines={[{ terms: [{ n: calc.supply ?? 0, unit: "원", label: "공급가" }, "+", { n: calc.vatWon ?? 0, unit: "원", label: "부가세" }], result: { n: calc.total ?? 0, unit: "원" } }]} />
            ) : calcErr && amount && vat ? <p className={s.err} role="alert"><Icon name="error" size={16} />{calcErr}</p>
            : amount && vat ? <Small>잠시 뒤 임시 저장하면 믿집 계산(공급가 · 부가세 · 합계)이 보여요.</Small> : null}
            <div className={s.two}>
              <Field ref={daysRef} label="공사 기간" unit="일" num inputMode="numeric" value={days} error={err.days} onChange={(e) => { setDays(digits(e.target.value).slice(0, 3)); setErr((x) => ({ ...x, days: undefined })); }} />
              <Field ref={validRef} label="유효기간" type="date" min={today} value={valid} error={err.valid} onChange={(e) => { setValid(e.target.value); setErr((x) => ({ ...x, valid: undefined })); }} />
            </div>
            {/* CF-40: '칩' 대신 쉬운 말 */}
            <ChoiceChips
              multiple
              legend="포함됐나요? · 고객 비교 화면에 함께 보여요"
              options={[{ value: "removal", label: "기존 벽지 철거" }, { value: "waste", label: "폐기물 처리" }, { value: "spec", label: "벽지 제조사 · 규격" }, { value: "warranty", label: "하자 보수 기간" }]}
              value={incl}
              onChange={setIncl}
            />
            {incl.includes("spec") || incl.includes("warranty") ? (
              <div className={s.two}>
                {incl.includes("spec") ? <Field label="벽지 제조사 · 규격" maxLength={60} value={spec} onChange={(e) => setSpec(e.target.value)} /> : null}
                {incl.includes("warranty") ? <SelectField label="하자 보수" options={WARRANTY} value={warranty} onChange={(e) => setWarranty(e.target.value)} /> : null}
              </div>
            ) : null}
          </Group>
        </fieldset>
        {/* CF-38: '버전' 대신 쉬운 말. 보낸 견적서가 있을 때만(처음 보낼 때는 '다시 올리기'가 없어요) */}
        {board.sent.length ? <Small>다시 올리면 고객에게 새 견적서가 보여요. 고객이 확정한 견적서는 바뀌지 않아요.</Small> : null}
        {err.form ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err.form}</p> : null}

        {board.sent.length ? (
          <Group flush>
            <Eyebrow as="h2">보낸 견적서</Eyebrow>
            <Rows label="보낸 견적서">
              {board.sent.map((q) => (
                <Row
                  key={q.id}
                  label={`${q.version}판 · ${q.sent_at ? `${dateShort(q.sent_at)}에 보냄` : "보냄"}`}
                  sub={[q.days ? `공사 ${q.days}일` : null, q.valid_until ? `${dateShort(q.valid_until)}까지 유효` : null].filter(Boolean).join(" · ") || undefined}
                  value={q.total != null ? won(q.total) : "—"}
                />
              ))}
            </Rows>
            {/* 고객이 지금 보는 판(최신)의 파일: 올린 사람만 열 수 있는 /api/files 주소예요 */}
            <div className={s.sentFiles}>
              {board.sent[0].files.map((f) => (
                <FileRow key={f.file_id} name={f.filename} size={f.size} note={`${board.sent[0].version}판`} href={MOCK ? undefined : `/api/files/${enc(f.file_id)}`} />
              ))}
            </div>
          </Group>
        ) : null}
      </Main>
      <BottomBar>
        {early && b ? (
          <>
            {chatHref ? <Button size="lg" variant="secondary" href={chatHref}>채팅 열기</Button> : null}
            <Button size="lg" disabled>{`${dateShort(b.day)}부터 보내요`}</Button>
          </>
        ) : (
          <>
            <Button size="lg" variant="secondary" onClick={onSave} busy={busy === "save"} disabled={busy === "send"}>{busy === "save" ? "저장하는 중" : "임시 저장"}</Button>
            <Button size="lg" onClick={onSend} busy={busy === "send" || uploading} disabled={busy === "save"}>{busy === "send" ? "보내는 중" : "고객에게 보내기"}</Button>
          </>
        )}
      </BottomBar>
    </>
  );
}

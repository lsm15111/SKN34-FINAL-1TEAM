"use client";
// 업체 정보 · 기본(V15 v_profile): 한 줄 소개 · 다니는 지역 · 실측 출장비 · 연락 방법 · 통화 시간 · 세금 · 바로 확정 기본값 · 반나절당 받는 실측 수 · 등록 · 보험
// · 자주 묻는 답 5가지(고객 업체 자세히에 보여요. 서버 vendor_faqs는 있었는데 고칠 칸이 없었어요, QA r6 M12).
// 잠정 결정: 세금에 간이과세(L02) · 반나절당 받는 실측 수 1~3, 기본 2(L03) · 실내건축업 등록을 비우면 고객 화면에 아무것도 안 보여요(L05).
// 저장 → PUT /vendor/profile(updated_at으로 먼저 저장한 곳이 있으면 409). 통화 시작 · 끝은 한 칸에 한 줄씩(8판).
import { useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { Field, SelectField, TextArea } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import type { ProfileV3, Region } from "@/lib/api/vendor";
import { errorText } from "@/lib/backend/client";
import { CONTACT_LABEL, type ContactMethod } from "@/lib/labels";
import { FAQ_LABEL } from "@/components/vendors/text";
import { send } from "../send";
import { TAX_KINDS } from "../text";
import { Eyebrow, Group, Small } from "../ui/parts";
import { Segmented } from "@/components/ui/Segmented";
import { Switch } from "@/components/ui/Switch";
import { profileBody } from "./body";
import s from "./Profile.module.css";

type Area = { sido: string; sgg: string; label: string };
type Tax = "general" | "simplified" | "exempt";
type FaqKey = (typeof FAQ_LABEL)[number]["key"];
const TIMES = Array.from({ length: 33 }, (_, i) => { const m = 6 * 60 + i * 30; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; });
const digits = (v: string) => v.replace(/\D/g, "").slice(0, 7);
const labelOf = (regions: Region[], sido: string, sgg: string) => {
  const r = regions.find((x) => x.id === sido);
  const g = r?.groups.find((x) => x.items.includes(sgg));
  return g?.prefix ? `${g.prefix} ${sgg}` : sgg;
};

export function BasicForm({ profile, regions, tabs }: { profile: ProfileV3; regions: Region[]; tabs: ReactNode }) {
  const router = useRouter();
  const toast = useToast();
  const hasIntro = "intro" in profile;
  const [intro, setIntro] = useState(profile.intro ?? "");
  const [areas, setAreas] = useState<Area[]>(profile.areas.map((a) => ({ sido: a.sido, sgg: a.sgg, label: a.label })));
  const [pickOpen, setPickOpen] = useState(false);
  const [sido, setSido] = useState(profile.areas[0]?.sido ?? regions[0]?.id ?? "seoul");
  const [feeMode, setFeeMode] = useState<"free" | "paid">((profile.visit_fee ?? 0) > 0 ? "paid" : "free");
  const [fee, setFee] = useState(profile.visit_fee ? String(profile.visit_fee) : "");
  const [refund, setRefund] = useState(profile.visit_fee_refund);
  const [contact, setContact] = useState<ContactMethod>((profile.contact_method as ContactMethod) ?? "phone");
  const [contactUrl, setContactUrl] = useState(profile.contact_url ?? "");
  const [callStart, setCallStart] = useState(profile.call_start ?? "09:00");
  const [callEnd, setCallEnd] = useState(profile.call_end ?? "18:00");
  const [tax, setTax] = useState<Tax>((profile.tax_kind as Tax) ?? "general");
  const [instant, setInstant] = useState(profile.instant_default ?? true);
  const [cap, setCap] = useState(String(profile.visit_capacity ?? 2));
  const [license, setLicense] = useState(profile.interior_license ?? "");
  const [insurance, setInsurance] = useState(profile.insurance ?? "");
  const [faq, setFaq] = useState<Record<FaqKey, string>>(() => Object.fromEntries(FAQ_LABEL.map(({ key }) => [key, profile.faqs.find((f) => f.key === key)?.answer ?? ""])) as Record<FaqKey, string>);
  const [err, setErr] = useState<Record<string, string | undefined>>({});
  const [busy, setBusy] = useState(false);
  const feeRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const region = regions.find((r) => r.id === sido);
  const needUrl = contact === "kakao" || contact === "web";

  function toggleArea(sd: string, sgg: string, on: boolean) {
    setAreas((xs) => (on ? (xs.some((a) => a.sido === sd && a.sgg === sgg) ? xs : [...xs, { sido: sd, sgg, label: labelOf(regions, sd, sgg) }]) : xs.filter((a) => !(a.sido === sd && a.sgg === sgg))));
    setErr((e) => ({ ...e, areas: undefined }));
  }

  async function save() {
    if (busy) return;
    const e: Record<string, string> = {};
    if (!areas.length) e.areas = "다니는 지역을 하나 이상 골라 주세요.";
    if (feeMode === "paid" && !(Number(fee) > 0)) e.fee = "출장비를 원 단위로 넣어 주세요.";
    if (needUrl && contactUrl.trim() && !/^https?:\/\//i.test(contactUrl.trim())) e.url = "주소를 https://로 시작하게 넣어 주세요.";
    if (callStart >= callEnd) e.call = "통화 끝을 통화 시작보다 늦게 골라 주세요.";
    setErr(e);
    if (e.fee) { feeRef.current?.focus(); return; }
    if (e.url) { urlRef.current?.focus(); return; }
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      await send("PUT", "/vendor/profile", profileBody(profile, {
        areas: areas.map((a) => ({ sido: a.sido, sgg: a.sgg })),
        visit_fee: feeMode === "paid" ? Number(fee) : 0,
        visit_fee_refund: feeMode === "paid" && refund,
        contact_method: contact,
        contact_url: needUrl ? contactUrl.trim() || null : null,
        call_start: callStart,
        call_end: callEnd,
        tax_kind: tax,
        instant_default: instant,
        visit_capacity: Number(cap),
        interior_license: license.trim() || null,
        insurance: insurance.trim() || null,
        faqs: FAQ_LABEL.map(({ key }) => ({ key, answer: faq[key].trim() })).filter((f) => f.answer),
        ...(hasIntro ? { intro: intro.trim() || null } : {}),
      }));
      toast.show("저장했어요.");
      router.refresh();
    } catch (er) {
      setErr({ form: errorText(er) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Main narrow>
        <PageHead title="업체 정보" crumbs={[{ label: "업체 정보", href: "/vendor/profile" }, { label: "기본" }]} />
        {tabs}
        <Group>
          {hasIntro ? <Field label="한 줄 소개" maxLength={60} value={intro} onChange={(e) => setIntro(e.target.value)} /> : null}
          <div className={s.areaRow}>
            <ChoiceChips
              multiple
              legend="다니는 지역"
              options={areas.map((a) => ({ value: `${a.sido}/${a.sgg}`, label: a.sgg }))}
              value={areas.map((a) => `${a.sido}/${a.sgg}`)}
              onChange={(next) => setAreas((xs) => xs.filter((a) => next.includes(`${a.sido}/${a.sgg}`)))}
              error={err.areas}
            />
            <Button variant="text" icon="plus" onClick={() => setPickOpen(true)}>더하기</Button>
          </div>
        </Group>
        <Group>
          <Segmented legend="실측 출장비" options={[{ value: "free", label: "무료" }, { value: "paid", label: "받아요" }]} value={feeMode} onChange={(x) => { setFeeMode(x as "free" | "paid"); setErr((e) => ({ ...e, fee: undefined })); }} />
          {feeMode === "paid" ? <Field ref={feeRef} label="출장비" unit="원" num inputMode="numeric" value={fee ? Number(fee).toLocaleString("ko-KR") : ""} error={err.fee} onChange={(e) => setFee(digits(e.target.value))} /> : null}
          <Switch label="계약하면 출장비를 빼 줘요" desc="출장비를 받을 때만 켜요" checked={feeMode === "paid" && refund} onChange={setRefund} disabled={feeMode !== "paid"} />
        </Group>
        <Group>
          <ChoiceChips legend="연락 방법" options={(Object.keys(CONTACT_LABEL) as ContactMethod[]).map((k) => ({ value: k, label: CONTACT_LABEL[k] }))} value={contact} onChange={(x) => setContact(x as ContactMethod)} />
          {needUrl ? <Field ref={urlRef} label={contact === "kakao" ? "카카오톡 채널 주소" : "홈페이지 상담 주소"} optional type="url" inputMode="url" maxLength={300} value={contactUrl} error={err.url} onChange={(e) => setContactUrl(e.target.value)} /> : null}
          <SelectField label="통화 시작" options={TIMES.map((t) => ({ value: t, label: t }))} value={callStart} onChange={(e) => { setCallStart(e.target.value); setErr((x) => ({ ...x, call: undefined })); }} />
          <SelectField label="통화 끝" options={TIMES.map((t) => ({ value: t, label: t }))} value={callEnd} error={err.call} onChange={(e) => { setCallEnd(e.target.value); setErr((x) => ({ ...x, call: undefined })); }} />
        </Group>
        <Group>
          <Segmented legend="세금" options={TAX_KINDS as { value: Tax; label: string }[]} value={tax} onChange={(x) => setTax(x as Tax)} />
          {tax === "simplified" ? <Small>간이과세는 부가세를 따로 붙이지 않아요. 단가 · 견적 금액을 받을 금액 그대로 넣어요.</Small> : null}
          <Field label="실내건축업 등록" optional maxLength={60} value={license} hint="비우면 고객 화면에 보이지 않아요" onChange={(e) => setLicense(e.target.value)} />
          <Field label="보험" optional maxLength={60} value={insurance} onChange={(e) => setInsurance(e.target.value)} />
        </Group>
        <Group>
          <Switch label="고객이 고르면 바로 확정" desc="기간을 답할 때 처음 켜 둘 값이에요. 요청마다 바꿀 수 있어요." checked={instant} onChange={setInstant} />
          <Segmented legend="한 반나절에 받을 실측 수" options={[{ value: "1", label: "1건" }, { value: "2", label: "2건" }, { value: "3", label: "3건" }]} value={cap} onChange={setCap} />
          <Small>같은 반나절에 이만큼까지 고객이 고를 수 있어요. 시각은 확정 뒤 채팅으로 정해요.</Small>
        </Group>
        <Group>
          <Eyebrow as="h2">자주 묻는 답</Eyebrow>
          {FAQ_LABEL.map(({ key, label }) => (
            <TextArea key={key} label={label} optional rows={2} maxLength={200} value={faq[key]} onChange={(e) => setFaq((x) => ({ ...x, [key]: e.target.value }))} />
          ))}
        </Group>
        {err.form ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err.form}</p> : null}
      </Main>
      <BottomBar>
        <Button size="lg" block onClick={save} busy={busy}>{busy ? "저장하는 중" : "저장"}</Button>
      </BottomBar>

      <Sheet open={pickOpen} onClose={() => setPickOpen(false)} title="다니는 지역 더하기">
        <SelectField label="시 · 도" options={regions.map((r) => ({ value: r.id, label: r.name }))} value={sido} onChange={(e) => setSido(e.target.value)} />
        {region?.groups.map((g) => (
          <ChoiceChips
            key={g.label || g.prefix}
            multiple
            legend={g.label || `${region.name} 시 · 군 · 구`}
            options={g.items.map((it) => ({ value: it, label: it }))}
            value={areas.filter((a) => a.sido === sido && g.items.includes(a.sgg)).map((a) => a.sgg)}
            onChange={(next) => g.items.forEach((it) => toggleArea(sido, it, next.includes(it)))}
          />
        ))}
        <Small>고른 지역 {areas.length}곳 · 저장을 눌러야 바뀌어요.</Small>
      </Sheet>
    </>
  );
}

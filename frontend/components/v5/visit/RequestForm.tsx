"use client";
// 실측 일정 요청서(C13 · D08). 담은 업체에 같은 요청(희망 기간 · 사진)을 한 번에 보내요.
// 희망 기간 초안은 계산 엔진 값(GET …/visits/draft: 공사 시작 − 28일 ~ − 14일)이고 고객이 달력에서 바꿔요.
// 보내면 그때 고른 벽지의 가견적이 고정되고 기본 정보가 잠겨요(서버). 검사는 보낼 때 한 번(I6 B), 첫 틀린 곳으로 옮겨 가요.
// 사진은 POST /files(kind photo, 위치 정보는 서버가 지움) 뒤 id만 보내요. AI 초안 카드(D08)는 옆 AI 칸(B5)이 그려요.
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { errorText } from "@/lib/backend/client";
import type { Schemas } from "@/lib/v5/types";
import type { VisitDraft } from "@/lib/api/visit";
import { dateShort, rangeText, won } from "@/lib/v5/format";
import { gradeLabel } from "@/lib/v5/labels";
import { send, upload } from "@/lib/mock/v3b/client";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { Calendar } from "@/components/ui/Calendar";
import { FileDrop } from "@/components/ui/FileDrop";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { Eyebrow, Group, GroupHead } from "@/components/project/Kit";
import s from "./visit.module.css";

type Created = Schemas["VisitCreateOut"];
type Photo = { key: string; id: string | null; name: string; url: string };

/** 보내지 못한 업체 까닭(VisitCreateOut.failed.code) */
const FAILED: Record<string, string> = {
  unavailable: "지금 믿집에서 일할 수 없는 업체예요",
  already: "이미 요청한 업체예요",
  not_shortlisted: "담지 않은 업체예요",
  no_estimate: "가견적 준비 중이라 보낼 수 없어요",
  paper_unsupported: "고른 벽지를 안 하는 업체예요",
  blocked_retry: "두 번 답이 없어 이 공사에는 더 요청할 수 없어요",
};

export function RequestForm({ projectId, projectName, draft, today, aside }: {
  projectId: string;
  projectName: string;
  draft: VisitDraft;
  today: string;
  aside: ReactNode;
}) {
  const router = useRouter();
  const toast = useToast();
  const ids = { cal: useId(), vendors: useId(), wishErr: useId(), vendorErr: useId() };
  const [range, setRange] = useState<{ from: string; to?: string } | null>(draft.wish_start && draft.wish_end ? { from: draft.wish_start, to: draft.wish_end } : null);
  const [calOpen, setCalOpen] = useState(!draft.wish_start);
  const [picked, setPicked] = useState<string[]>(draft.vendors.map((v) => v.vendor_id));
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [photoErr, setPhotoErr] = useState<string | null>(null);
  const [wishErr, setWishErr] = useState<string | null>(null);
  const [vendorErr, setVendorErr] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ name: string; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const firstCheck = useRef<HTMLInputElement>(null);
  const calRef = useRef<HTMLDivElement>(null);
  const photosRef = useRef(photos);
  useEffect(() => { photosRef.current = photos; }, [photos]);
  // 미리 보기 주소(blob:)는 화면을 떠날 때 돌려줘요
  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  const pid = encodeURIComponent(projectId);
  const n = picked.length;

  function toggle(id: string) {
    setPicked((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
    setVendorErr(null);
  }

  async function addPhotos(files: File[]) {
    setPhotoErr(null);
    setUploading(true);
    for (const f of files) {
      const key = crypto.randomUUID();
      const url = URL.createObjectURL(f);
      setPhotos((xs) => [...xs, { key, id: null, name: f.name, url }]);
      try {
        const up = await upload(f, "photo");
        setPhotos((xs) => xs.map((p) => (p.key === key ? { ...p, id: up.id } : p)));
      } catch (e) {
        URL.revokeObjectURL(url);
        setPhotos((xs) => xs.filter((p) => p.key !== key));
        setPhotoErr(errorText(e));
      }
    }
    setUploading(false);
  }
  function removePhoto(key: string) {
    setPhotos((xs) => {
      const p = xs.find((x) => x.key === key);
      if (p) URL.revokeObjectURL(p.url);
      return xs.filter((x) => x.key !== key);
    });
  }

  async function submit() {
    setFailed([]);
    // 보낼 때 한 번 검사하고 첫 틀린 곳으로 옮겨 가요(I6 B)
    const wishBad = !range ? "희망 기간을 골라 주세요." : !range.to ? "희망 기간이 끝나는 날도 골라 주세요." : null;
    const vendorBad = n === 0 ? "보낼 업체를 한 곳 이상 골라 주세요." : null;
    setWishErr(wishBad);
    setVendorErr(vendorBad);
    if (wishBad) { setCalOpen(true); requestAnimationFrame(() => calRef.current?.focus()); return; }
    if (vendorBad) { firstCheck.current?.focus(); return; }
    if (uploading) { setPhotoErr("사진을 올리는 중이에요. 다 올라간 뒤 보내 주세요."); return; }
    setBusy(true);
    try {
      const body = { trade: "dobae" as const, vendor_ids: picked, wish_start: range!.from, wish_end: range!.to!, photo_file_ids: photos.flatMap((p) => (p.id ? [p.id] : [])) };
      const out = await send<Created>("POST", `/projects/${pid}/visits`, body, { step: "sent", result: { created: [], failed: [] } });
      if (out.failed.length) {
        const name = (id: string) => draft.vendors.find((v) => v.vendor_id === id)?.name ?? "업체";
        setFailed(out.failed.map((f) => ({ name: name(f.vendor_id), text: FAILED[f.code] ?? "보내지 못했어요" })));
        if (out.created.length) toast.show(`${out.created.length}곳에 보냈어요`);
        router.refresh();
        return;
      }
      toast.show("실측 일정 요청을 보냈어요");
      router.push(`/v5/projects/${pid}/visits`);
      router.refresh();
    } catch (e) {
      setVendorErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const wishText = range ? (range.to ? rangeText(range.from, range.to, { weekday: true }) : `${dateShort(range.from)}~`) : "아직 안 골랐어요";

  return (
    <>
      <Main>
        <PageHead title="실측 일정 요청" crumbs={[{ label: "내 공사", href: "/v5/my" }, { label: projectName, href: `/v5/projects/${pid}` }, { label: "실측 일정 요청" }]} />
        <WithAside aside={aside}>
          <div className={s.reqCols}>
            <Group label="희망 기간">
              <Eyebrow as="h2">희망 기간</Eyebrow>
              <GroupHead>
                <p className={`${s.bigText} mj-num`}>{wishText}</p>
                <Button variant="text" className={s.calToggle} aria-expanded={calOpen} aria-controls={ids.cal} onClick={() => setCalOpen((v) => !v)}>{calOpen ? "접기" : "바꾸기"}</Button>
              </GroupHead>
              <div id={ids.cal} ref={calRef} tabIndex={-1} className={calOpen ? `${s.calBox} ${s.calOn}` : s.calBox}>
                {/* 희망 기간은 내일부터예요(서버 규칙): 오늘 칸은 꺼 둬요. 내일 날짜를 화면이 셈하지 않으려고 오늘을 '안 됨'으로 표시해요(QA r6 L15) */}
                <Calendar mode="range" label="희망 기간 고르기" today={today} month={range?.from ?? today} value={range} marks={{ [today]: ["unavailable"] }} onChange={(v) => { setRange(v); setWishErr(null); }} />
              </div>
              {wishErr ? <p id={ids.wishErr} className={s.err} role="alert"><Icon name="error" size={16} />{wishErr}</p> : null}
            </Group>

            <div className={s.reqSide}>
              <Group list label="보낼 업체">
                <Eyebrow as="h2" pad>보낼 업체</Eyebrow>
                <div role="group" aria-label="보낼 업체" aria-describedby={vendorErr ? ids.vendorErr : undefined}>
                  {draft.vendors.map((v, i) => (
                    <label key={v.vendor_id} className={s.checkRow}>
                      <input ref={i === 0 ? firstCheck : undefined} type="checkbox" className={s.checkInput} checked={picked.includes(v.vendor_id)} onChange={() => toggle(v.vendor_id)} />
                      <span className={s.checkBox} aria-hidden="true"><Icon name="check" size={16} strokeWidth={3} /></span>
                      <span className={s.checkText}>
                        <b>{v.name}</b>
                        <span className="mj-num">{v.estimate_total != null ? `가견적 ${won(v.estimate_total)}` : "가견적 준비 중"} · {gradeLabel(v.grade)}</span>
                      </span>
                    </label>
                  ))}
                </div>
                {vendorErr ? <p id={ids.vendorErr} className={s.err} role="alert"><Icon name="error" size={16} />{vendorErr}</p> : null}
                {failed.length ? (
                  <ul className={s.failList} role="alert">
                    {failed.map((f) => <li key={f.name}><b>{f.name}</b> · {f.text}</li>)}
                  </ul>
                ) : null}
              </Group>

              <Group label="사진">
                <p className={s.fieldLabel}>사진 <span>(선택)</span></p>
                {photos.length ? (
                  <ul className={s.thumbs} aria-label="올린 사진">
                    {photos.map((p, i) => (
                      <li key={p.key} className={s.thumb}>
                        {/* 고른 사진 미리 보기(blob:) */}
                        <img src={p.url} alt={`올린 사진 ${i + 1}`} />
                        {p.id ? null : <span className={s.thumbBusy}>올리는 중</span>}
                        <button type="button" className={s.thumbX} aria-label={`${i + 1}번째 사진 빼기`} onClick={() => removePhoto(p.key)}><Icon name="close" size={16} /></button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <FileDrop kind="photo" label="집 사진 올리기" onFiles={addPhotos} busy={uploading} error={photoErr} />
              </Group>
            </div>
          </div>
        </WithAside>
      </Main>
      <BottomBar>
        <Button size="lg" onClick={submit} busy={busy}>{busy ? "보내는 중" : n > 0 ? `고른 ${n}곳에 요청 보내기` : "요청 보내기"}</Button>
      </BottomBar>
    </>
  );
}

"use client";
// 리뷰 쓰기(C39): 별점(꼭) · 칩 4개 · 글 · 기준 줄은 B2a ReviewFields, 사진 칸 · 보내기는 여기 → POST /projects/{id}/deals/{did}/review → 업체 상세 리뷰로.
// 공사 끝을 확인한 고객만 써요(서버가 막아요, 두 번째는 409). 검사는 올릴 때 한 번(I6 B), 사진은 위치 정보를 지운 새 그림만 저장돼요(서버).
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { send, upload } from "@/lib/mock/v3b/client";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { FileDrop } from "@/components/ui/FileDrop";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { Main } from "@/components/site/Frame";
import { Group } from "@/components/project/Kit";
import { checkReview, EMPTY_REVIEW, REVIEW_PHOTOS_MAX as PHOTO_MAX, ReviewFields, reviewBody, type ReviewDraft, type ReviewError } from "@/components/review/ReviewFields";
import s from "@/components/schedule/v3.module.css";

type Photo = { id: string; name: string; url: string };

/** 화면 본문(Main) · 아래 단추 띠까지 그려요(띠는 Main 바로 뒤에 붙어야 해서요). top: 제목 · 업체 줄, after: 묶음 뒤 줄 */
export function ReviewForm({ projectId, dealId, vendorId, top, after }: { projectId: string; dealId: string; vendorId: string | null; top?: React.ReactNode; after?: React.ReactNode }) {
  const router = useRouter();
  const toast = useToast();
  const formId = useId();
  const [draft, setDraft] = useState<ReviewDraft>(EMPTY_REVIEW);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<{ field?: ReviewError | null; photo?: string; all?: string }>({});
  const [busy, setBusy] = useState(false);
  const starRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const urls = useRef<string[]>([]);

  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);

  async function addFiles(files: File[]) {
    const room = PHOTO_MAX - photos.length;
    if (room <= 0) { setErr((e) => ({ ...e, photo: `사진은 ${PHOTO_MAX}장까지 올려요.` })); return; }
    const pick = files.filter((f) => f.type.startsWith("image/")).slice(0, room);
    if (!pick.length) { setErr((e) => ({ ...e, photo: "사진 파일(JPG · PNG · HEIC)만 올려요." })); return; }
    setErr((e) => ({ ...e, photo: undefined }));
    setUploading(true);
    try {
      for (const f of pick) {
        const r = await upload(f, "review_photo");
        const url = URL.createObjectURL(f);
        urls.current.push(url);
        setPhotos((ps) => [...ps, { id: r.id, name: r.filename, url }]);
      }
    } catch (e) {
      setErr((x) => ({ ...x, photo: errorText(e) }));
    } finally {
      setUploading(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const bad = checkReview(draft);
    setErr({ field: bad });
    if (bad?.field === "rating") { starRef.current?.querySelector<HTMLElement>("[role=radio]")?.focus(); return; }
    if (bad?.field === "body") { bodyRef.current?.focus(); return; }
    setBusy(true);
    try {
      await send(
        "POST",
        `/projects/${encodeURIComponent(projectId)}/deals/${encodeURIComponent(dealId)}/review`,
        reviewBody(draft, photos.map((p) => p.id)),
        { step: "reviewed" },
      );
      toast.show("리뷰를 올렸어요");
      router.push(vendorId ? `/v5/projects/${encodeURIComponent(projectId)}/vendors/${encodeURIComponent(vendorId)}` : `/v5/projects/${encodeURIComponent(projectId)}`);
      router.refresh();
    } catch (x) {
      setErr({ all: errorText(x) });
      setBusy(false);
    }
  }

  const photoBox = (
    <div className={s.photos}>
      <FileDrop label="리뷰 사진 올리기" onFiles={addFiles} busy={uploading} error={err.photo} disabled={photos.length >= PHOTO_MAX} />
      {photos.length ? (
        <ul className={s.thumbs} aria-label="올린 사진">
          {photos.map((p, i) => (
            <li key={p.id} className={s.thumb}>
              <img src={p.url} alt={`올린 사진 ${i + 1}: ${p.name}`} />
              <button type="button" className={s.thumbX} aria-label={`올린 사진 ${i + 1} 빼기`} onClick={() => setPhotos((ps) => ps.filter((x) => x.id !== p.id))}><Icon name="close" size={16} /></button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );

  return (
    <>
      <Main narrow>
        {top}
        <Group>
          <form id={formId} className={s.sheetBody} noValidate onSubmit={submit} aria-label="리뷰 쓰기">
            <div ref={starRef}>
              <ReviewFields
                ref={bodyRef}
                value={draft}
                onChange={(d) => { setDraft(d); if (err.field) setErr((x) => ({ ...x, field: null })); }}
                error={err.field}
                photos={photoBox}
              />
            </div>
            {err.all ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err.all}</p> : null}
          </form>
        </Group>
        {after}
      </Main>
      <BottomBar>
        <Button size="lg" type="submit" form={formId} busy={busy}>{busy ? "올리는 중" : "리뷰 올리기"}</Button>
      </BottomBar>
    </>
  );
}

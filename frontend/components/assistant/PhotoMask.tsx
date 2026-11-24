"use client";
// 받은 견적서 사진 가리기(고정 선 3: 연락처 · 개인정보는 LLM · 업체로 보내지 않아요).
// - 고른 사진을 캔버스에 그리고(휴대폰 방향 반영, 긴 변 2000px 아래), 고객이 이름 · 주소 · 전화번호 위를 끌어 검은 상자로 가려요.
//   손가락 · 마우스 모두 포인터 이벤트 하나로 받아요(새 의존성 없음). [되돌리기]는 마지막 상자를 지워요.
// - '개인정보를 가렸어요'를 확인해야 [올리기]가 켜져요. 상자를 그려 넣은 새 그림(JPEG)만 POST /files(chat_photo)로 올리고 원본은
//   올리지 않아요. 서버가 위치 정보를 한 번 더 지우고, 사진은 받은 견적서 점검 도구만 읽어요.
// - 아래 시트(폰) · 가운데 창(웹)은 components/ui/Sheet 그대로예요.
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Check } from "@/components/ui/Check";
import { Sheet } from "@/components/ui/Sheet";
import { uploadQuotePhoto } from "@/lib/api/assistant";
import { canUpload, dragBox, fitSize, toImage, type Box, type Pt } from "@/lib/assistant/mask";
import { errorText } from "@/lib/backend/client";
import s from "./PhotoMask.module.css";

export type Attached = { id: string; url: string };

const OPEN_FAIL = "사진을 열 수 없어요. 다른 사진을 골라 주세요.";
const MASK = "#000"; // 가린 칸은 그림 픽셀이라 늘 검정이에요(화면 색 토큰과 상관없음)
const DRAFT = "rgba(0, 0, 0, 0.55)";

async function openImage(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch { /* 아래 <img>로 다시 열어요 */ }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function PhotoMask({ file, onDone, onClose }: {
  /** 고른 사진(없으면 닫힘) */
  file: File | null;
  /** 올린 가린 그림의 파일 id와 미리 보기 주소(object URL, 쓰고 나면 부르는 쪽이 놓아요) */
  onDone: (p: Attached) => void;
  onClose: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const pic = useRef<ImageBitmap | HTMLImageElement | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [drag, setDrag] = useState<{ a: Pt; b: Pt } | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!file) return;
    let live = true;
    setBoxes([]);
    setDrag(null);
    setOk(false);
    setErr(null);
    setSize(null);
    openImage(file)
      .then((img) => {
        if (!live) return;
        pic.current = img;
        setSize(fitSize(img.width, img.height));
      })
      .catch(() => { if (live) setErr(OPEN_FAIL); });
    return () => {
      live = false;
      const img = pic.current;
      if (img && "close" in img) img.close();
      pic.current = null;
    };
  }, [file]);

  // 사진 + 가린 상자 + 끄는 중인 상자(옅게)를 다시 그려요
  useEffect(() => {
    const c = canvas.current;
    const img = pic.current;
    if (!c || !img || !size) return;
    if (c.width !== size.w) c.width = size.w;
    if (c.height !== size.h) c.height = size.h;
    const g = c.getContext("2d");
    if (!g) return;
    g.drawImage(img, 0, 0, size.w, size.h);
    g.fillStyle = MASK;
    for (const b of boxes) g.fillRect(b.x, b.y, b.w, b.h);
    const d = drag ? dragBox(drag.a, drag.b, size.w, size.h) : null;
    if (d) {
      g.fillStyle = DRAFT;
      g.fillRect(d.x, d.y, d.w, d.h);
    }
  }, [size, boxes, drag]);

  const at = (e: React.PointerEvent<HTMLCanvasElement>): Pt => {
    const c = e.currentTarget;
    return toImage(e.clientX, e.clientY, c.getBoundingClientRect(), c.width, c.height);
  };

  async function upload() {
    const c = canvas.current;
    if (!c || !canUpload(ok, !!size, busy)) return;
    setBusy(true);
    setErr(null);
    setDrag(null);
    try {
      const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.9));
      if (!blob) throw new Error("toBlob");
      const got = await uploadQuotePhoto(blob);
      onDone({ id: got.id, url: URL.createObjectURL(blob) });
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={!!file}
      onClose={onClose}
      title="개인정보 가리기"
      dismissible={!busy}
      hideClose
      actions={
        <div className={s.btns}>
          <Button variant="secondary" size="lg" onClick={onClose} disabled={busy}>취소</Button>
          <Button size="lg" onClick={() => { void upload(); }} disabled={!canUpload(ok, !!size, busy)} busy={busy}>{busy ? "올리는 중" : "올리기"}</Button>
        </div>
      }
    >
      <p className={s.hint}>이름 · 주소 · 전화번호 위를 끌어서 가려 주세요.</p>
      <div className={s.stage}>
        {size ? (
          <canvas
            ref={canvas}
            className={s.canvas}
            role="img"
            aria-label={`받은 견적서 사진, ${boxes.length}곳 가림`}
            onPointerDown={(e) => {
              if (busy || e.button > 0) return;
              e.currentTarget.setPointerCapture(e.pointerId);
              const p = at(e);
              setDrag({ a: p, b: p });
            }}
            onPointerMove={(e) => { if (drag) setDrag({ a: drag.a, b: at(e) }); }}
            onPointerUp={(e) => {
              if (!drag || !size) return;
              const b = dragBox(drag.a, at(e), size.w, size.h);
              setDrag(null);
              if (b) setBoxes((x) => [...x, b]);
            }}
            onPointerCancel={() => setDrag(null)}
          />
        ) : (
          <p className={s.wait}>{err ? null : "사진을 여는 중이에요"}</p>
        )}
      </div>
      <div className={s.tools}>
        <span className={s.count}>{boxes.length ? `${boxes.length}곳 가렸어요` : "아직 가린 곳이 없어요"}</span>
        <Button variant="text" gray onClick={() => setBoxes((x) => x.slice(0, -1))} disabled={!boxes.length || busy}>되돌리기</Button>
      </div>
      <Check label="개인정보를 가렸어요" checked={ok} onChange={setOk} disabled={!size || busy} />
      {err ? <p className={s.err} role="alert">{err}</p> : null}
    </Sheet>
  );
}

"use client";
// 시공 사례 묶음(C11 · D07): 사진 칸(B4 PhotoGrid, 묶음이 좁으면 3장 · 넓으면 4장) + '크게 보기'(C47, B4 Lightbox).
// 크게 보기는 주소에 ?photo=n을 얕게 붙여요(history.pushState, routes.md 1장): 뒤로 가기로 닫히고, 주소로 바로 열 수도 있어요.
// 기록 칸은 여기서 한 번만 넣으니 Lightbox는 pushHistory={false}, 넘길 때는 onIndex로 주소의 n만 바꿔요(기록을 더 쌓지 않아요).
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Lightbox, type LightboxPhoto } from "@/components/ui/Lightbox";
import { PhotoGrid } from "@/components/ui/PhotoGrid";
import s from "./vendors3.module.css";

export type CasePhoto = LightboxPhoto & { label: string };

const PARAM = "photo";

/** 지금 주소에 ?photo=n(1부터)을 붙이거나 빼요 */
function urlWith(i: number | null): URL {
  const u = new URL(window.location.href);
  if (i === null) u.searchParams.delete(PARAM);
  else u.searchParams.set(PARAM, String(i + 1));
  return u;
}

/** ?photo=n과 크게 보기 여닫기를 맞춰요 */
function usePhotoParam(count: number) {
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => {
    const sync = () => {
      const n = Number(new URLSearchParams(window.location.search).get(PARAM));
      setAt(Number.isInteger(n) && n >= 1 && n <= count ? n - 1 : null);
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [count]);
  const open = useCallback((i: number) => {
    history.pushState({ ...history.state, mjPhoto: true }, "", urlWith(i));
    setAt(i);
  }, []);
  const close = useCallback(() => {
    if (history.state?.mjPhoto) { history.back(); return; } // popstate → sync가 닫아요
    history.replaceState(history.state, "", urlWith(null));
    setAt(null);
  }, []);
  /** 넘길 때 주소의 n만 바꿔요(여는 사진 start는 그대로 둬요) */
  const mark = useCallback((i: number) => { history.replaceState(history.state, "", urlWith(i)); }, []);
  return { at, open, close, mark };
}

export function CasesBlock({ id, photos }: { id: string; photos: CasePhoto[] }) {
  const v = usePhotoParam(photos.length);
  return (
    <section id={id} className={`${s.group} ${s.spot} ${s.cases}`} aria-labelledby={`${id}-t`}>
      <div className={s.gh}>
        <h2 id={`${id}-t`}>시공 사례 <span className="mj-num">{photos.length}</span></h2>
        <Button variant="text" onClick={() => v.open(0)} aria-haspopup="dialog">크게 보기</Button>
      </div>
      <PhotoGrid
        label="시공 사례 사진"
        className={s.caseGrid}
        photos={photos.slice(0, 4).map((p) => ({ key: p.key, src: p.src, alt: p.alt, label: p.label }))}
        onOpen={v.open}
      />
      <Lightbox open={v.at !== null} start={v.at ?? 0} onClose={v.close} label="시공 사례" photos={photos} pushHistory={false} onIndex={v.mark} />
    </section>
  );
}

"use client";
// 사진 넣는 칸. 끌어다 놓거나, 칸을 눌러 파일을 고른다(진짜 파일 입력을 칸 안에 둬서 키보드로도 연다).
// 넣은 사진은 넣은 차례대로 작은 그림으로 보이고, 누르면 아래에 크게 보인다. 오른쪽 위 ×로 뺀다.
import { useEffect, useRef, useState } from "react";
import { eulReul } from "@/lib/format";

export type Photo = { id: string; name: string; url: string; type: string; file: File };

let seq = 0;
export function toPhotos(files: File[]): Photo[] {
  return files.map((f) => ({ id: `p${++seq}`, name: f.name, url: URL.createObjectURL(f), type: f.type, file: f }));
}

export function PhotoDrop({ id, label, photos, onAdd, onRemove, max = 10, accept = "image/*", maxMB, hint }: {
  id: string; label: string; photos: Photo[]; onAdd: (files: File[]) => void; onRemove: (photoId: string) => void; max?: number; accept?: string; maxMB?: number; hint: string;
}) {
  const [over, setOver] = useState(false);
  const [cur, setCur] = useState(0);
  const [msg, setMsg] = useState(""); // 넣었어요 · 뺐어요: 화면 읽기에만 알린다
  const [warn, setWarn] = useState(""); // 못 넣은 파일이 있을 때만 화면에 보인다
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const refocus = useRef<number | null>(null);
  const room = max - photos.length;
  const one = max === 1;
  const okType = (f: File) => accept.split(",").some((a) => (a.endsWith("/*") ? f.type.startsWith(a.slice(0, -1)) : f.type === a.trim()));

  useEffect(() => { if (cur > photos.length - 1) setCur(Math.max(0, photos.length - 1)); }, [photos.length, cur]);
  // 뺀 뒤에는 같은 자리의 다음 사진 ×로, 남은 사진이 없으면 사진 넣는 칸으로 초점을 옮긴다.
  useEffect(() => {
    if (refocus.current == null) return;
    const xs = list.current?.querySelectorAll<HTMLButtonElement>(".mj-thumb-x");
    const target = xs?.[Math.min(refocus.current, xs.length - 1)];
    (target ?? input.current)?.focus();
    refocus.current = null;
  }, [photos.length]);

  function remove(i: number) {
    const p = photos[i];
    refocus.current = i;
    onRemove(p.id);
    setMsg(`${i + 1}번째를 뺐어요.`);
    setWarn("");
  }

  function take(list: FileList | null) {
    const all = Array.from(list ?? []);
    const typed = all.filter(okType);
    const good = maxMB ? typed.filter((f) => f.size <= maxMB * 1024 * 1024) : typed;
    const fit = one ? good.slice(0, 1) : good.slice(0, Math.max(0, room));
    if (fit.length) { onAdd(fit); setCur(one ? 0 : photos.length); }
    if (!all.length) return;
    const done = !fit.length ? "" : one ? `${eulReul(label)} 넣었어요.` : `${fit.length}장을 넣었어요.`;
    const notType = all.length - typed.length;
    const tooBig = typed.length - good.length;
    const notRoom = good.length - fit.length;
    const why = [
      notType ? `넣을 수 없는 형식 ${notType}개는 뺐어요.` : "",
      tooBig ? `${maxMB}MB가 넘는 파일 ${tooBig}개는 뺐어요.` : "",
      !one && notRoom ? `${max}장까지 넣을 수 있어요.` : "",
    ].filter(Boolean).join(" ");
    setMsg([done, why].filter(Boolean).join(" "));
    setWarn(why);
  }

  const shown = photos[cur];
  return (
    <div className="mj-photo">
      <label
        className={`mj-drop${over ? " is-over" : ""}`}
        htmlFor={id}
        onDragEnter={(e) => { e.preventDefault(); setOver(true); }}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false); }}
        onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files); }}
      >
        <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="10" r="1.6" /><path d="M21 16l-5-5-8 8" /></svg>
        <span className="mj-drop-t">{label}</span>
        <span className="mj-small">여기로 끌어다 놓거나 눌러서 고르세요 · {hint}</span>
        <input ref={input} id={id} type="file" accept={accept} multiple={!one} className="mj-sr" onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
      </label>
      <p className="mj-sr" aria-live="polite">{msg}</p>
      {warn ? <p className="mj-small" style={{ color: "var(--warn)" }}>{warn}</p> : null}

      {photos.length > 0 && (
        <>
          <ol ref={list} className="mj-thumbs" aria-label={`${label} 목록`}>
            {photos.map((p, i) => (
              <li key={p.id} className="mj-thumb-li">
                <button type="button" className="mj-thumb" aria-pressed={i === cur} onClick={() => setCur(i)} aria-label={`${i + 1}번째 크게 보기 · ${p.name}`}>
                  {p.type.startsWith("image/") ? <img src={p.url} alt="" /> : <span className="mj-thumb-file">PDF</span>}
                  <span className="mj-thumb-n mj-num" aria-hidden="true">{i + 1}</span>
                </button>
                <button type="button" className="mj-thumb-x" onClick={() => remove(i)} aria-label={`${i + 1}번째 빼기 · ${p.name}`}>
                  <span aria-hidden="true"><svg width="12" height="12" viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /></svg></span>
                </button>
              </li>
            ))}
          </ol>
          {shown && (
            <figure className="mj-viewer">
              {shown.type.startsWith("image/") ? <img src={shown.url} alt={`${label} ${cur + 1}번째: ${shown.name}`} /> : <div className="mj-viewer-file">{shown.name}</div>}
            </figure>
          )}
        </>
      )}
    </div>
  );
}

"use client";
// 사진: 고른 사진 종류(S.imgMode) → 다른 종류 → 색 견본 순서로 보인다 (v10 pickSrc · photo · paintPhoto).
// 사진이 깨지면 그 종류를 지우고 다음 종류로 넘어간다.
import { useState, type ReactNode } from "react";
import type { Material } from "./data";
import { asset, S, store, touch, useV2 } from "./store";

export type Srcs = { ai?: string | null; mfg?: string | null; free?: string | null; color?: string | null };

export function pickSrc(srcs: Srcs, mode: string, broken: Set<string>) {
  const order = [mode, ...["ai", "mfg", "free"].filter((m) => m !== mode)] as ("ai" | "mfg" | "free")[];
  for (const m of order) {
    const src = srcs[m];
    if (src && !broken.has(m)) return { m, src };
  }
  return null;
}

export function Photo({ srcs, alt, cls = "", children }: { srcs: Srcs; alt: string; cls?: string; children?: ReactNode }) {
  const st = useV2();
  const [broken, setBroken] = useState<Set<string>>(() => new Set());
  const got = pickSrc(srcs, st.imgMode, broken);
  return (
    <figure className={`ph ${cls}`.trim()} data-ph="1">
      {got ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={got.src}
          src={asset(got.src) ?? undefined}
          alt={alt}
          loading="lazy"
          decoding="async"
          onError={() => setBroken((b) => new Set(b).add(got.m))}
        />
      ) : (
        <div className="swatch-fill" style={{ background: srcs.color || "var(--surface-2)" }} role="img" aria-label={alt} />
      )}
      {children}
    </figure>
  );
}

export const matSrcs = (m: Material): Srcs => ({ ai: m.img_ai || null, mfg: m.img_mfg || null, free: m.img_free || null, color: m.color });

/** 사진 종류 바꾸기 (머리의 '무료 사진 · 제조사 · AI') */
export function setImgMode(m: "free" | "mfg" | "ai") {
  S.imgMode = m;
  store.set("mj-imgmode", m);
  touch();
}

/** 가구 없는 '시공 직후' 사진 보기 (v10 emptyView) */
export const view = { empty: false };
export function EmptyToggle() {
  useV2();
  return (
    <div className="seg" role="group" aria-label="사진 보기">
      {([[false, "가구 있음"], [true, "시공 직후"]] as const).map(([v, l]) => (
        <button
          key={l}
          type="button"
          aria-pressed={view.empty === v}
          onClick={() => {
            view.empty = v;
            store.set("mj-empty", v ? "1" : "0");
            touch();
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

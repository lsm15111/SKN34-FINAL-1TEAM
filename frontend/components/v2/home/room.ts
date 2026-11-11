// 사진이 없는 느낌의 방 그림 (v10 roomDraw · RR · standIn · roomSvg · lookCredit7).
// 거실 · 방은 빈 방 실사 사진에 느낌 색(바닥 · 벽 · 나무)을 입히고, 욕실 · 주방 · 현관은 같은 공간의 비슷한 사진을 빌린다.
// 사진을 칠할 준비가 되기 전에는 SVG 그림(roomDraw)을 쓰고, 준비되면 touch()로 다시 그린다.
import { LOOKS, type Look, mixHex, rgbOf } from "../looks";
import { touch } from "../store";

type Tone = Look["tone"];
type LookLike = { tone?: Tone; space?: string; style?: string; img?: string | null };

export function roomDraw(lk: LookLike) {
  const t = lk.tone || {}, sp = lk.space;
  const bath = sp === "bath", kit = sp === "kitchen";
  const wall = bath ? t.tile || "#E4E5E2" : t.wall || "#F2EFEA", wood = t.wood || "#D8C7AE", tile = t.tile || "#E4E5E2";
  const flC = bath ? mixHex(t.tile || "#E4E5E2", "#5a5a5a", 0.18) : t.floor || "#CDB592";
  /* 한 점 원근: 앞면 480×320, 뒷벽은 0.6배(96~384 × 60~252), 소실점 (240,150) */
  const Sc = (u: number) => 1 - 0.4 * u;
  type Pt = [number, number];
  const fp = (l: number, u: number): Pt => {
    const s = Sc(u);
    return [240 + (l * 2 - 1) * 240 * s, 150 + 170 * s];
  };
  const cp = (l: number, u: number): Pt => {
    const s = Sc(u);
    return [240 + (l * 2 - 1) * 240 * s, 150 - 150 * s];
  };
  const rp = (u: number, hh: number): Pt => {
    const s = Sc(u), yf = 150 + 170 * s, yc = 150 - 150 * s;
    return [240 + 240 * s, yf + (yc - yf) * hh];
  };
  const lp = (u: number, hh: number): Pt => {
    const p = rp(u, hh);
    return [480 - p[0], p[1]];
  };
  const P = (pts: Pt[]) => pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const L = (a: Pt, b: Pt, st: string) => `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" ${st}/>`;
  const ceil = mixHex(t.wall || "#F2EFEA", "#ffffff", 0.55);
  let g = "";
  /* 바닥 */
  g += `<g clip-path="url(#cf)"><rect x="0" y="252" width="480" height="68" fill="${flC}"/>`;
  if (bath) {
    for (let i = -6; i <= 6; i++) g += L([240 + i * 60, 320], [240 + i * 36, 252], 'stroke="#fff" stroke-opacity=".22" stroke-width=".8"');
    for (let k = 1; k < 5; k++) {
      const y = fp(0, k / 5)[1];
      g += L([0, y], [480, y], 'stroke="#fff" stroke-opacity=".22" stroke-width=".8"');
    }
  } else {
    g += `<rect x="0" y="252" width="480" height="68" filter="url(#wg)"/>`;
    for (let i = -14; i <= 14; i++) g += L([240 + i * 30, 320], [240 + i * 18, 252], 'stroke="#000" stroke-opacity=".13" stroke-width=".8"');
    for (let k = 0; k < 7; k++) {
      const y = fp(0, (k + 0.5) / 7)[1], s = (y - 150) / 170;
      for (let i = -14; i < 14; i++) if ((((i * 5 + k * 3) % 4) + 4) % 4 === 0) g += L([240 + i * 30 * s, y], [240 + (i + 1) * 30 * s, y], 'stroke="#000" stroke-opacity=".12" stroke-width=".8"');
    }
  }
  g += `<rect x="0" y="252" width="480" height="68" fill="url(#gf)"/>`;
  /* 창에서 바닥으로 떨어지는 빛 */
  g += `<polygon points="${P([fp(0.97, 0.22), fp(0.97, 0.7), fp(0.52, 0.62), fp(0.52, 0.14)])}" fill="#fff" opacity="${bath ? 0.12 : 0.26}" filter="url(#bl)"/></g>`;
  /* 천장 · 옆벽 · 뒷벽 */
  g += `<polygon points="0,0 480,0 384,60 96,60" fill="${ceil}"/><polygon points="0,0 480,0 384,60 96,60" fill="url(#gc)"/>`;
  g += `<polygon points="0,0 96,60 96,252 0,320" fill="${wall}"/><polygon points="0,0 96,60 96,252 0,320" fill="url(#gl)"/>`;
  g += `<polygon points="480,0 384,60 384,252 480,320" fill="${wall}"/><polygon points="480,0 384,60 384,252 480,320" fill="url(#gr)"/>`;
  g += `<rect x="96" y="60" width="288" height="192" fill="${wall}"/>`;
  if (bath) {
    const st = 'stroke="#000" stroke-opacity=".09" stroke-width=".8"';
    for (let x = 96 + 48; x < 384; x += 48) g += L([x, 60], [x, 252], st);
    for (let y = 252 - 48; y > 60; y -= 48) g += L([96, y], [384, y], st);
    for (let k = 1; k < 4; k++) {
      const hh = k / 4;
      g += L(lp(0, hh), lp(1, hh), st) + L(rp(0, hh), rp(1, hh), st);
    }
    for (let k = 1; k < 4; k++) {
      const u = k / 4;
      g += L(lp(u, 0), lp(u, 1), st) + L(rp(u, 0), rp(u, 1), st);
    }
  }
  if (kit) {
    const doors = (y0: number, y1: number, c: string) => {
      let s = `<rect x="96" y="${y0}" width="288" height="${y1 - y0}" fill="${c}"/><rect x="96" y="${y0}" width="288" height="${y1 - y0}" fill="url(#gv)"/>`;
      for (let x = 96 + 48; x < 384; x += 48) s += L([x, y0], [x, y1], 'stroke="#000" stroke-opacity=".16" stroke-width=".9"');
      return s;
    };
    g += `<rect x="96" y="118" width="288" height="60" fill="${tile}"/>`;
    for (let y = 118 + 12; y < 178; y += 12) g += L([96, y], [384, y], 'stroke="#000" stroke-opacity=".08" stroke-width=".7"');
    for (let r = 0; r < 5; r++) for (let x = 96 + (r % 2 ? 12 : 24); x < 384; x += 24) g += L([x, 118 + r * 12], [x, 130 + r * 12], 'stroke="#000" stroke-opacity=".08" stroke-width=".7"');
    g += doors(64, 116, wood) + `<rect x="96" y="116" width="288" height="5" fill="#000" opacity=".1"/>`;
    g += doors(184, 246, wood) + `<rect x="94" y="177" width="292" height="7" fill="${mixHex(tile, "#ffffff", 0.45)}"/><rect x="94" y="183" width="292" height="2" fill="#000" opacity=".12"/><rect x="96" y="246" width="288" height="6" fill="#000" opacity=".22"/>`;
  }
  g += `<rect x="96" y="60" width="288" height="192" fill="url(#gb)"/><rect x="96" y="60" width="288" height="192" fill="url(#ga)"/>`;
  /* 걸레받이 · 모서리 그림자 */
  if (!bath) {
    const bb = mixHex(wood, "#ffffff", 0.15);
    g += `<rect x="96" y="246" width="288" height="6" fill="${bb}"/><polygon points="${P([[0, 320], [96, 252], [96, 246.6], [0, 311]])}" fill="${mixHex(bb, "#000000", 0.12)}"/><polygon points="${P([[480, 320], [384, 252], [384, 246.6], [480, 311]])}" fill="${mixHex(bb, "#000000", 0.05)}"/>`;
  }
  g += L([96, 60], [96, 252], 'stroke="#000" stroke-opacity=".08" stroke-width="1.5"') + L([384, 60], [384, 252], 'stroke="#000" stroke-opacity=".05" stroke-width="1.5"') + L([96, 60], [384, 60], 'stroke="#000" stroke-opacity=".06" stroke-width="1.2"');
  /* 오른쪽 벽 창 */
  if (!bath) {
    const fr = [rp(0.22, 0.2), rp(0.7, 0.2), rp(0.7, 0.86), rp(0.22, 0.86)], gl = [rp(0.25, 0.24), rp(0.67, 0.24), rp(0.67, 0.82), rp(0.25, 0.82)];
    g += `<polygon points="${P(fr)}" fill="#fbfbfa"/><polygon points="${P(gl)}" fill="url(#gw)"/>` + L(rp(0.46, 0.24), rp(0.46, 0.82), 'stroke="#fbfbfa" stroke-width="3"');
    g += `<polygon points="${P([rp(0.2, 0.2), rp(0.72, 0.2), rp(0.72, 0.19), rp(0.2, 0.19)])}" fill="#000" opacity=".08"/>`;
  }
  /* 뒷벽 문 (욕실 · 주방은 빼요) */
  if (!bath && !kit) {
    g += `<rect x="126" y="97" width="73" height="155" fill="${mixHex(wood, "#000000", 0.14)}"/><rect x="130" y="101" width="65" height="151" fill="${wood}"/><rect x="130" y="101" width="65" height="151" fill="url(#gd)"/>`;
    g += `<rect x="184" y="176" width="8" height="3" rx="1.5" fill="#2e2e2e" opacity=".7"/><rect x="130" y="248" width="65" height="4" fill="#000" opacity=".12"/>`;
  }
  /* 천장 매입등 */
  for (const l of [0.36, 0.64]) {
    const c = cp(l, 0.45), s = Sc(0.45);
    g += `<ellipse cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" rx="${(9 * s).toFixed(1)}" ry="${(2.4 * s).toFixed(1)}" fill="#fff"/><ellipse cx="${c[0].toFixed(1)}" cy="${(c[1] + 1).toFixed(1)}" rx="${(22 * s).toFixed(1)}" ry="${(9 * s).toFixed(1)}" fill="url(#gg)"/>`;
  }
  const defs =
    `<defs><clipPath id="cf"><polygon points="0,320 96,252 384,252 480,320"/></clipPath>` +
    `<filter id="wg" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.2 0.012" numOctaves="3" seed="4"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.3 0 0 0 -0.08"/></filter>` +
    `<filter id="gn" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.09 0 0 0 0"/></filter>` +
    `<filter id="bl" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="7"/></filter>` +
    `<linearGradient id="gf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".1"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".16"/></linearGradient>` +
    `<linearGradient id="gc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".1"/><stop offset="1" stop-color="#000" stop-opacity=".02"/></linearGradient>` +
    `<linearGradient id="gl" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".16"/><stop offset="1" stop-color="#000" stop-opacity=".05"/></linearGradient>` +
    `<linearGradient id="gr" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".12"/><stop offset="1" stop-color="#000" stop-opacity=".07"/></linearGradient>` +
    `<radialGradient id="gb" cx=".82" cy=".42" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".32"/><stop offset=".6" stop-color="#fff" stop-opacity=".05"/><stop offset="1" stop-color="#000" stop-opacity=".05"/></radialGradient>` +
    `<linearGradient id="ga" x1="0" y1="0" x2="0" y2="1"><stop offset=".82" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".12"/></linearGradient>` +
    `<linearGradient id="gv" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".14"/><stop offset="1" stop-color="#000" stop-opacity=".1"/></linearGradient>` +
    `<linearGradient id="gd" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset="1" stop-color="#000" stop-opacity=".12"/></linearGradient>` +
    `<linearGradient id="gw" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset=".55" stop-color="#eef3f6"/><stop offset="1" stop-color="#d9e4ea"/></linearGradient>` +
    `<radialGradient id="gg"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>` +
    `<radialGradient id="gvn" cx=".5" cy=".5" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".16"/></radialGradient></defs>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 320">${defs}${g}<rect width="480" height="320" filter="url(#gn)"/><rect width="480" height="320" fill="url(#gvn)"/></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

/* 빈 방 실사 사진(Unsplash nQlVMCHPysY, 원본 1920×1280)의 바닥 · 벽 · 천장 · 걸레받이 · 문에 느낌 색을 입힌다.
   사진의 밝기 · 결 · 그림자는 그대로 두고 색만 바꾼다(영역 평균 밝기 = 고른 색) */
type RRBase = { W: number; H: number; base: ImageData; reg: Uint8Array; up: Uint8Array; lum: Float32Array; mean: number[]; canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D };
const RR = { src: "/v2/img/free/style-modern-white-empty-hd.jpg", cache: {} as Record<string, string>, base: null as RRBase | null, ready: null as Promise<boolean> | null };
const segY = (pts: number[][], x: number) => {
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    if (x <= x1) return y0 + (y1 - y0) * ((x - x0) / (x1 - x0 || 1));
  }
  return pts[pts.length - 1][1];
};

/* 경계: 천장 · 창은 좌표로, 바닥 윗선 · 걸레받이 윗선은 사진의 세로줄마다 찾아요(나무색이 시작되는 곳 · 밝기가 바뀌는 곳).
   좌표는 720 폭 기준이고 사진 크기에 맞춰 늘려요 */
async function rrPrepare(): Promise<boolean> {
  const im = new Image();
  im.src = RR.src;
  await im.decode();
  const W = Math.min(1440, im.naturalWidth), H = Math.round((W * im.naturalHeight) / im.naturalWidth), sc = W / 720, n = W * H; /* 계산은 1440 폭까지만 */
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const x = c.getContext("2d", { willReadFrequently: true });
  if (!x) return false;
  x.drawImage(im, 0, 0, W, H);
  const base = x.getImageData(0, 0, W, H), d = base.data;
  const P = (pts: number[][]) => pts.map(([a, b]) => [a * sc, b * sc]);
  const FLOOR = P([[0, 376], [189, 297], [472, 296], [496, 309], [546, 309], [720, 391]]);
  const CEIL = P([[0, 48], [189, 143], [190, 143], [498, 143], [499, 103], [546, 103], [720, 0]]);
  const WX0 = 299 * sc, WX1 = 409 * sc, WY0 = 147 * sc, WY1 = 293 * sc;
  const lum = new Float32Array(n);
  for (let k = 0; k < n; k++) lum[k] = d[k * 4] * 0.3 + d[k * 4 + 1] * 0.59 + d[k * 4 + 2] * 0.11;
  const sat = (px: number, py: number) => {
    const i = (py * W + px) * 4, mx = Math.max(d[i], d[i + 1], d[i + 2]), mn = Math.min(d[i], d[i + 1], d[i + 2]);
    return mx ? (mx - mn) / mx : 0;
  };
  const med = (a: Int32Array, r: number) =>
    Int32Array.from(a, (_, i) => {
      const w = Array.from(a.slice(Math.max(0, i - r), i + r + 1)).sort((p, q) => p - q);
      return w[w.length >> 1];
    });
  let fy = new Int32Array(W), bt = new Int32Array(W);
  for (let px = 0; px < W; px++) {
    const g = Math.round(segY(FLOOR, px));
    let f = g;
    for (let py = Math.round(g - 14 * sc); py <= g + 10 * sc && py + 2 < H; py++)
      if (sat(px, py) > 0.07 && sat(px, py + 1) > 0.07 && sat(px, py + 2) > 0.07) {
        f = py;
        break;
      }
    fy[px] = f;
  }
  fy = med(fy, Math.round(3 * sc));
  for (let px = 0; px < W; px++) {
    const f = fy[px], st = Math.round(2 * sc);
    let best = f - Math.round(6 * sc), bd = 0;
    for (let py = f - Math.round(3 * sc); py > f - 22 * sc && py - st >= 0; py--) {
      const dd = Math.abs(lum[py * W + px] - lum[(py - st) * W + px]);
      if (dd > bd) {
        bd = dd;
        best = py - Math.round(st / 2);
      }
    }
    bt[px] = Math.max(f - Math.round(16 * sc), Math.min(f - Math.round(3 * sc), best));
  }
  bt = med(bt, Math.round(6 * sc));
  /* 벽 면마다 곧은 선으로 맞춰요(튀는 점은 빼고 다시 맞춤). 경계: 왼쪽 벽 · 뒷벽 · 기둥 옆 · 기둥 앞 · 오른쪽 벽 */
  const SEGS = [[0, 189], [189, 472], [472, 496], [496, 546], [546, 720]].map(([a, b]) => [Math.round(a * sc), Math.min(W - 1, Math.round(b * sc))]);
  const fit = (arr: Int32Array, a: number, b: number, skip: (px: number) => boolean) => {
    let pts: number[][] = [];
    for (let px = a; px <= b; px++) if (!skip(px)) pts.push([px, arr[px]]);
    if (pts.length < 4) return;
    for (let round = 0; round < 3; round++) {
      const m = pts.length, sx = pts.reduce((t, q) => t + q[0], 0), sy = pts.reduce((t, q) => t + q[1], 0), sxx = pts.reduce((t, q) => t + q[0] * q[0], 0), sxy = pts.reduce((t, q) => t + q[0] * q[1], 0);
      const k1 = (m * sxy - sx * sy) / (m * sxx - sx * sx || 1), k0 = (sy - k1 * sx) / m;
      if (round === 2) {
        for (let px = a; px <= b; px++) arr[px] = Math.round(k0 + k1 * px);
        return;
      }
      const keep = pts.filter(([px, py]) => Math.abs(py - (k0 + k1 * px)) <= 2 * sc);
      if (keep.length >= 4) pts = keep;
    }
  };
  const winX = (px: number) => px > WX0 - 2 && px < WX1 + 2;
  for (const [a, b] of SEGS) {
    fit(fy, a, b, winX);
    fit(bt, a, b, winX);
  }
  for (let px = 0; px < W; px++) bt[px] = Math.max(fy[px] - Math.round(16 * sc), Math.min(fy[px] - Math.round(3 * sc), bt[px]));
  const reg = new Uint8Array(n), up = new Uint8Array(n), sum = [0, 0, 0, 0, 0], cnt = [0, 0, 0, 0, 0];
  for (let py = 0; py < H; py++)
    for (let px = 0; px < W; px++) {
      const k = py * W + px;
      let r = 0; /* 0 벽 · 1 바닥 · 2 천장 · 3 그대로(창) · 4 걸레받이 */
      if (px >= WX0 && px <= WX1 && py >= WY0 && py <= WY1) r = 3;
      else if (py >= fy[px]) r = 1;
      else if (py >= bt[px] && !(px > WX0 - 1 && px < WX1 + 1)) r = 4;
      else if (py < segY(CEIL, px)) r = 2;
      reg[k] = r;
      sum[r] += lum[k];
      cnt[r]++;
      if (py > 0 && reg[k - W] !== r) up[k] = reg[k - W] + 1; /* 경계 한 줄은 위아래 색을 섞어요 */
    }
  RR.base = { W, H, base, reg, up, lum, mean: sum.map((v, r) => v / (cnt[r] || 1)), canvas: c, ctx: x };
  return true;
}
/** 빈 방 사진 칠할 준비 (한 번만). 준비되면 화면을 다시 그린다 */
export function rrReady() {
  if (!RR.ready) {
    RR.ready = typeof window === "undefined" ? Promise.resolve(false) : rrPrepare().catch(() => false);
    RR.ready.then((ok) => {
      if (ok) touch();
    });
  }
  return RR.ready;
}
export const rrOn = () => !!RR.base;
export function rrPaint(tone: Tone) {
  const B = RR.base;
  if (!B) return null;
  const key = [tone.floor, tone.wall, tone.wood].join("|");
  if (RR.cache[key]) return RR.cache[key];
  const wall = tone.wall || "#F2EFEA";
  const cols = [rgbOf(wall), rgbOf(tone.floor || "#CDB592"), rgbOf(mixHex(wall, "#ffffff", 0.75)), null, rgbOf(tone.wood || "#D8C7AE")];
  const out = B.ctx.createImageData(B.W, B.H), o = out.data, d = B.base.data, tmp = [0, 0, 0], tmp2 = [0, 0, 0];
  const col = (k: number, r: number, t: number[]) => {
    const c = cols[r], i = k * 4;
    if (!c) {
      t[0] = d[i];
      t[1] = d[i + 1];
      t[2] = d[i + 2];
      return;
    }
    const f = B.lum[k] / B.mean[r];
    for (let j = 0; j < 3; j++) t[j] = f <= 1 ? c[j] * f : c[j] + (255 - c[j]) * Math.min(1, (f - 1) * 1.6);
  };
  for (let k = 0, n = B.W * B.H; k < n; k++) {
    const i = k * 4;
    col(k, B.reg[k], tmp);
    if (B.up[k]) {
      col(k, B.up[k] - 1, tmp2);
      for (let j = 0; j < 3; j++) tmp[j] = (tmp[j] + tmp2[j]) / 2;
    }
    o[i] = tmp[0];
    o[i + 1] = tmp[1];
    o[i + 2] = tmp[2];
    o[i + 3] = 255;
  }
  B.ctx.putImageData(out, 0, 0);
  return (RR.cache[key] = B.canvas.toDataURL("image/jpeg", 0.9));
}

/* 사진 없는 느낌: 거실 · 방은 빈 방 사진에 색을 입히고, 욕실 · 주방 · 현관은 같은 공간의 비슷한 사진을 보여 준다 */
const RR_STANDIN: Record<string, 1> = { bath: 1, kitchen: 1, entry: 1, dress: 1 };
function standIn(lk: LookLike) {
  const all = Object.entries(LOOKS).flatMap(([sid, ls]) => ls.map((l) => ({ ...l, style: sid })));
  return all.find((l) => l.img && l.space === lk.space && l.style === lk.style) || all.find((l) => l.img && l.space === lk.space) || null;
}
/** 느낌 사진 자리 그림 (data URI 또는 빌린 사진 경로). flow.ts lookSrcs가 부른다 */
export function roomSvg(lk: LookLike): string {
  if (lk.space && RR_STANDIN[lk.space]) {
    const s = standIn(lk);
    if (s?.img) return s.img;
  }
  const painted = rrPaint(lk.tone || {});
  if (painted) return painted;
  rrReady();
  return roomDraw(lk);
}
export function lookCredit(lk: LookLike) {
  if (lk.space && RR_STANDIN[lk.space]) {
    const s = standIn(lk);
    if (s) return `비슷한 공간 사진이에요(사진 ${s.credit || "Unsplash"} · Unsplash). 색은 위 견본을 봐 주세요.`;
  }
  return "빈 방 사진(Unsplash)에 이 느낌의 바닥 · 벽 · 문 색을 입혔어요";
}

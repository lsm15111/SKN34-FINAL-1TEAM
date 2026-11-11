"use client";
// 견적서에 나오는 말, 사진으로 보기 (v10 v8 PG_PHOTOS · PARTS8 · partsGuide).
// 단어나 사진 속 그 부분에 마우스를 올리면(폰은 누르면) 그 부분만 밝게 남기고 짧은 설명을 보인다.
// v10 최종 첫 화면에서는 숨겨져 있다(11-11 덧씌움). 다시 넣을 때 Home에 <PartsGuide />만 더하면 된다.
import { useEffect, useState } from "react";
import { asset } from "../store";

const PG_PHOTOS: Record<string, { src: string; w: number; h: number; credit: string; alt: string }> = {
  room: { src: "img/guide/room.jpg", w: 1600, h: 1064, credit: "Josh Lemmon · Unsplash", alt: "가구 없는 회색 벽 방. 흰 창과 흰 문, 걸레받이, 회색 마루가 보여요" },
  mold: { src: "img/guide/molding.jpg", w: 1600, h: 1067, credit: "Yves Cedric Schulze · Unsplash", alt: "흰 천장과 짙은 벽 사이에 흰 몰딩이 둘러진 방 모서리" },
};
/* 걸레받이 윗선 · 아랫선(사진 밝기로 잰 곧은 선): 왼쪽 벽 x 0~838, 오른쪽 벽 838~1187, 문 오른쪽 1490~1600 */
const PG_WIN = "M253 222L718 260L728 622L712 668L258 713L243 680Z";
const PG_DOOR = "M1187 288L1490 230L1490 769.5L1187 717.5Z";
type Part = { id: string; photo: string; ko: string; trade: string; desc: string; d: string; mark: [number, number] };
const PARTS8: Part[] = [
  { id: "wall", photo: "room", ko: "도배", trade: "도배", desc: "벽에 벽지를 바르는 일이에요. 얇은 종이 벽지(합지)와 비닐을 입혀 닦기 쉬운 벽지(실크)가 있어요.",
    d: `M0 75L835 322L1600 100V787L1490 769.5L1187 717.5L838 651L0 808.8Z ${PG_WIN} ${PG_DOOR}`, mark: [1010, 470] },
  { id: "ceil", photo: "room", ko: "천장", trade: "도배", desc: "천장도 보통 벽지로 마감해요. 벽과 같은 날 함께 도배해요.",
    d: "M0 0H1600V100L835 322L0 75Z", mark: [560, 150] },
  { id: "mold", photo: "mold", ko: "몰딩", trade: "목공", desc: "벽과 천장이 만나는 곳을 덮는 띠예요. 사진처럼 굵은 것도, 얇고 단순한 것도 있어요. 요즘은 몰딩 없이 마감하기도 해요(무몰딩).",
    d: "M0 0H45L545 582L1600 331V495L515 727L0 251Z", mark: [330, 444] },
  { id: "base", photo: "room", ko: "걸레받이", trade: "목공", desc: "벽 아래와 바닥이 만나는 곳에 대는 띠예요. 청소할 때 벽 아랫부분이 상하지 않게 막아 줘요.",
    d: "M0 808.8L838 651L1187 717.5V760.5L838 682.5L0 877.7Z M1490 769.5L1600 787V849.5L1490 824.5Z", mark: [250, 800] },
  { id: "door", photo: "room", ko: "문 · 문틀", trade: "목공", desc: "문짝과 그 둘레를 감싸는 틀이에요. 바꾸지 않고 필름을 붙여 색만 바꾸기도 해요.",
    d: "M1187 288L1490 230L1490 820L1187 765Z", mark: [1338, 520] },
  { id: "floor", photo: "room", ko: "바닥재", trade: "바닥", desc: "바닥에 까는 마감재예요. 마루 · 장판 · 타일 등이 있어요.",
    d: "M0 877.7L838 682.5L1187 760.5V765L1490 820V824.5L1600 849.5V1064H0Z", mark: [820, 930] },
  { id: "sash", photo: "room", ko: "샷시", trade: "창호", desc: "창틀과 유리를 함께 이르는 말이에요. 창호라고도 해요. 단열 · 소음에 영향을 줘요.",
    d: "M325 300L645 340L645 620L325 640Z", mark: [485, 470] },
];
/* 사진의 부위만 마우스로 고를 수 있게 영역을 깐다(큰 영역 먼저, 작은 영역 위에) */
const ORDER = ["ceil", "wall", "floor", "mold", "sash", "door", "base"];

export function PartsGuide() {
  const [cur, setCur] = useState("room");
  const [pinned, setPinned] = useState<string | null>(null);
  const [shown, setShown] = useState<string | null>(null);
  const show = (id: string | null) => {
    const x = PARTS8.find((p) => p.id === id);
    if (x && x.photo !== cur) setCur(x.photo);
    setShown(x ? x.id : null);
  };
  const pin = (id: string) => {
    const n = pinned === id ? null : id;
    setPinned(n);
    show(n);
  };
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && pinned) {
        setPinned(null);
        setShown(null);
      }
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [pinned]);
  const x = PARTS8.find((p) => p.id === shown) || null;
  const p = PG_PHOTOS[cur];
  return (
    <section className="home-sec pg">
      <div className="sec-t">
        <h2>견적서에 나오는 말, 사진으로 보기</h2>
        <p className="muted">도배 · 몰딩 · 걸레받이 · 샷시가 집의 어디인지 보여 드려요.</p>
      </div>
      <div className="pg-box">
        <div className={"pg-pic" + (x ? " on" : "")}>
          {Object.entries(PG_PHOTOS).map(([k, ph]) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={k} className={"pg-img" + (k === cur ? " on" : "")} src={asset(ph.src) ?? undefined} alt={k === cur ? ph.alt : ""} loading="lazy" decoding="async" />
          ))}
          <svg className="pg-svg" viewBox={`0 0 ${p.w} ${p.h}`} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
            <path className="pg-dim" fillRule="evenodd" d={x ? `M0 0H${p.w}V${p.h}H0Z ${x.d}` : ""} />
            <path className={"pg-edge" + (x?.id === "base" ? " thin" : "")} fillRule="evenodd" d={x ? x.d : ""} />
            <g>
              {ORDER.map((id) => PARTS8.find((q) => q.id === id))
                .filter((q): q is Part => !!q && q.photo === cur)
                .map((q) => (
                  <path key={q.id} className="pg-hit" fillRule="evenodd" d={q.d} onPointerEnter={() => show(q.id)} onPointerLeave={() => show(pinned)} onClick={() => pin(q.id)} />
                ))}
            </g>
          </svg>
          <span
            className="pg-label"
            aria-hidden="true"
            hidden={!x}
            style={x ? { left: `${((x.mark[0] / p.w) * 100).toFixed(2)}%`, top: `${((x.mark[1] / p.h) * 100).toFixed(2)}%` } : undefined}
          >
            {x?.ko}
          </span>
          <small className="pg-credit">{`사진 ${p.credit}`}</small>
        </div>
        <div className="pg-side">
          <div className="pg-chips" role="group" aria-label="부위 이름">
            {PARTS8.map((q) => (
              <button
                key={q.id}
                type="button"
                className={"pg-chip" + (shown === q.id ? " hot" : "")}
                data-id={q.id}
                aria-pressed={pinned === q.id}
                aria-describedby="pg-tip"
                onPointerEnter={(e) => {
                  if (e.pointerType === "mouse") show(q.id);
                }}
                onPointerLeave={(e) => {
                  if (e.pointerType === "mouse") show(pinned);
                }}
                onFocus={() => show(q.id)}
                onBlur={() => show(pinned)}
                onClick={() => pin(q.id)}
              >
                {q.ko}
              </button>
            ))}
          </div>
          <div className="pg-tip" id="pg-tip" aria-live="polite">
            {x ? (
              <>
                <div className="pg-tip-h">
                  <b>{x.ko}</b>
                  <span className="pg-trade">{`${x.trade} 공정`}</span>
                </div>
                <p>{x.desc}</p>
              </>
            ) : (
              <p className="muted">단어에 마우스를 올리거나 눌러 보세요. 사진 속 그 부분을 짚어도 돼요.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

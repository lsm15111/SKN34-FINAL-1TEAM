// 예상 범위 카드 (믿집 계산). 끝값 · 가운데 · '알려 주시면' 금액은 모두 API 값을 그대로 보이고 새로 계산하지 않는다.
// 막대 위 표시 위치(%)만 화면에서 정한다. 표준견적서 금액(point)이 범위 밖이면 막대 끝에 붙이고 글로 알린다.
import Link from "next/link";
import { won } from "@/lib/format";
import { partName, precisionText, rangeHints, shareText, spanText, type ApiRange } from "@/lib/range";
import s from "./RangeCard.module.css";

type Props = {
  id: string;
  r: ApiRange;
  title: string;
  /** 막대 위에 같이 보일 금액 (표준견적서 · 가견적) */
  point?: { label: string; amount: number };
  /** '알려 주시면' 안내에서 갈 곳 */
  areaHref?: string;
  vendorsHref?: string;
  /** 범위 · 막대만 (폭의 이유 · 안내 없이) */
  compact?: boolean;
};

function at(x: number, r: ApiRange): number {
  if (r.high <= r.low) return 50;
  return Math.min(100, Math.max(0, ((x - r.low) / (r.high - r.low)) * 100));
}

export function RangeCard({ id, r, title, point, areaHref, vendorsHref, compact = false }: Props) {
  const parts = compact ? [] : r.parts.filter((p) => Number(p.share) >= 0.05).slice(0, 3);
  const hints = compact ? [] : rangeHints(r, { areaHref, vendorsHref });
  const outside = point ? (point.amount < r.low ? "below" : point.amount > r.high ? "above" : null) : null;

  return (
    <section className={`${s.card}${compact ? ` ${s.compact}` : ""}`} aria-labelledby={`${id}-t`}>
      <div className={s.head}>
        <h3 id={`${id}-t`} className={s.title}>{title}</h3>
        <p className={s.tag}>믿집 계산 · 업체 견적 아님</p>
      </div>
      <p className={`mj-num ${s.span}`}>
        {spanText(r.low, r.high)}
        <span className="mj-small"> 부가세 포함</span>
      </p>
      <div className={s.bar} aria-hidden="true">
        <span className={s.fill} />
        <span className={s.mid} style={{ left: `${at(r.mid, r)}%` }} />
        {point ? <span className={s.pt} style={{ left: `${at(point.amount, r)}%` }} /> : null}
      </div>
      <p className={`mj-small mj-num ${s.legend}`}>
        <span className={s.item}><span className={s.keyMid} aria-hidden="true" />가운데 {won(r.mid)}</span>
        {point ? <span className={s.item}><span className={s.keyPt} aria-hidden="true" />{point.label} {won(point.amount)}</span> : null}
      </p>
      {outside ? (
        <p className="mj-small">{point?.label} 금액이 범위 {outside === "below" ? "아래" : "위"}에 있어요. 공공 단가와 시장 단가가 달라서 그래요.</p>
      ) : null}

      {parts.length ? (
        <div className={s.block}>
          <h4 className={s.sub}>폭이 생긴 이유</h4>
          <ul className={s.parts}>
            {parts.map((p) => (
              <li key={p.driver}>
                <span>{partName(p.driver)}</span>
                <span className={`mj-num ${s.share}`}>{shareText(p.share)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {hints.length ? (
        <div className={s.block}>
          <h4 className={s.sub}>이걸 알면 범위가 좁아져요</h4>
          <ul className={s.hints}>
            {hints.map((h) => (
              <li key={h.key}>
                <span className="mj-num">{h.text}</span>
                {h.href && h.cta ? <Link className="mj-lnk" href={h.href}>{h.cta}</Link> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!compact ? (
        <div className={s.foot}>
          <p className="mj-small">{precisionText(r)}</p>
          {r.fixed_add > 0 ? (
            <p className="mj-small mj-num">작은 공사라 출장 · 최소 인건비 같은 고정비 약 {won(r.fixed_add)}을 더해 잡았어요. 방 1칸은 집 전체보다 ㎡당 1.5배 안팎이 보통이에요.</p>
          ) : null}
          {r.extra_max > 0 ? (
            <p className="mj-small mj-num">철거 · 폐기물 같은 &lsquo;실측 후&rsquo; 줄은 할 가능성만큼 범위에 넣었어요. 모두 하게 되면 그 줄만 최대 {won(r.extra_max)}이에요.</p>
          ) : null}
          <p className="mj-small">비슷한 집이면 업체 10곳 중 8곳쯤이 이 안에 들도록 잡은 범위예요. 실제 견적이 쌓이면 계속 맞춰요.</p>
        </div>
      ) : null}
    </section>
  );
}

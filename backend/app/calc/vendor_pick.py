"""업체 추천 점수(코드, LLM 아님): 조건에 맞는 업체 중 3곳을 고르는 계산 엔진 순수 함수.

- 거르기: 가견적이 있는 업체만(단가를 업체가 확인했다는 뜻). 이 구 업체를 먼저 보고, 모자라면 가까운 구.
- 점수(0~1) = 별점 0.45 + 믿집 공사 수 0.20 + 가견적 0.35 (+ 이 구 0.05). 광고 · 돈으로 순서를 바꾸지 않는다.
  - 별점: 리뷰 수로 당긴 평균((평균 × 리뷰 + 4.0 × 5) ÷ (리뷰 + 5))을 3.5점 0 ~ 5.0점 1 눈금으로. 리뷰가 적으면
    4.0 쪽으로 당겨져요. 별점은 대부분 4~5점이라 ÷ 5로 재면 차이가 거의 안 보였어요(2026.11b).
  - 공사 수: 끝낸 공사를 로그 눈금으로(100건이면 만점). 20건 만점일 때는 오래 한 업체가 모두 같은 값이었어요.
  - 가견적: 표준견적서 대비 −40% 이하 만점, +40% 이상 0, 사이는 직선.
- 같은 점수는 가견적 낮은 순 → 이름 순. 사유는 화면 틀이 점수에 쓴 값을 그대로 옮긴다.
판(version)을 올리면 가중치를 바꿀 수 있어요. 고르는 건 고객이고, 화면에는 고른 기준을 같이 적어요.
2026.11b(리드 11-24, 목업 업체 48곳에서 비싸도 평이 좋은 업체가 3곳에 거의 못 들고 싼 업체가 1위를 독차지): 별점 눈금 ·
공사 수 로그 눈금 · 가격 폭 ±40%로 바꿨어요.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

VERSION = "vendor-pick-2026.11b"
W_RATING, W_DONE, W_PRICE, W_LOCAL = 0.45, 0.20, 0.35, 0.05
PRIOR, PRIOR_N = 4.0, 5
RATING_FLOOR, RATING_TOP = 3.5, 5.0
DONE_FULL = 100
PRICE_SPAN = 40  # %


@dataclass(frozen=True)
class Candidate:
    vendor_id: str
    name: str
    local: bool
    estimate_total: int | None
    vs_standard_pct: int | None
    rating: float | None
    review_count: int
    done_count: int
    instant: bool = False


@dataclass(frozen=True)
class Pick:
    c: Candidate
    score: float
    rating_shrunk: float | None
    value: bool = False  # 고를 거리로 넣은 '가견적이 낮은 곳'(pick 참고)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def score(c: Candidate) -> tuple[float, float | None]:
    """(점수, 리뷰 수로 당긴 별점). 가견적이 없으면 고르지 않으므로 부르는 쪽이 거른다."""
    shrunk = None
    if c.rating is not None and c.review_count > 0:
        r = float(c.rating)  # Decimal이 와도 같은 계산(Decimal + float은 오류)
        shrunk = (r * c.review_count + PRIOR * PRIOR_N) / (c.review_count + PRIOR_N)
    s_rating = _clamp(
        ((shrunk if shrunk is not None else PRIOR) - RATING_FLOOR) / (RATING_TOP - RATING_FLOOR)
    )
    s_done = _clamp(math.log1p(max(c.done_count, 0)) / math.log1p(DONE_FULL))
    pct = c.vs_standard_pct if c.vs_standard_pct is not None else 0
    s_price = _clamp((PRICE_SPAN - pct) / (2 * PRICE_SPAN))
    total = W_RATING * s_rating + W_DONE * s_done + W_PRICE * s_price + (W_LOCAL if c.local else 0)
    return round(total, 4), (round(shrunk, 2) if shrunk is not None else None)


VALUE_RATING = 4.0  # 가견적이 낮은 곳으로 넣을 때 당긴 별점 아래 끝


def pick(cands: Sequence[Candidate], n: int = 3) -> list[Pick]:
    """가견적이 있는 업체 중 점수 높은 n곳. 이 구 업체가 n곳 이상이면 이 구에서만 고른다.
    고를 거리(2026.11b): 3곳 넘게 있는데 고른 n곳 중 가견적이 가장 낮은 두 곳이 하나도 없으면, 마지막 자리를
    당긴 별점 4.0 이상 중 가견적이 가장 낮은 곳으로 바꾼다(점수만으로는 비싼 곳만 모일 수 있어요)."""
    ok = [c for c in cands if c.estimate_total is not None]
    local = [c for c in ok if c.local]
    pool = local if len(local) >= n else ok
    ranked = []
    for c in pool:
        s, shrunk = score(c)
        ranked.append(Pick(c, s, shrunk))
    ranked.sort(key=lambda p: (-p.score, p.c.estimate_total or 0, p.c.name))
    top = ranked[:n]
    if n < 2 or len(ranked) <= n:
        return top
    cheap = sorted(ranked, key=lambda p: (p.c.estimate_total or 0, -p.score, p.c.name))
    if any(p in top for p in cheap[:2]):
        return top
    alt = next(
        (p for p in cheap if p not in top and (p.rating_shrunk or PRIOR) >= VALUE_RATING), None
    )
    if alt is None:
        return top
    return [*top[: n - 1], Pick(alt.c, alt.score, alt.rating_shrunk, value=True)]


def reasons(p: Pick) -> list[str]:
    """화면 사유(틀). 숫자는 업체 자료 · 계산 엔진 값 그대로.
    표준견적서와 견준 %는 사유에 넣지 않는다(사용자 결정 2026-11-21, 점수에만 쓴다)."""
    c = p.c
    out: list[str] = []
    if p.value:
        out.append("가견적이 낮은 편이에요")
    if c.rating is not None and c.review_count > 0:
        out.append(f"별점 {c.rating:.1f} · 리뷰 {c.review_count}개")
    if c.done_count > 0:
        out.append(f"믿집 공사 {c.done_count}건")
    if c.instant:
        out.append("바로 확정할 수 있어요")
    if not c.local:
        out.append("가까운 구 업체예요")
    return out[:3]

"""업체 추천 점수 2026.11b(리드 11-24): 별점 눈금 · 공사 수 로그 눈금 · 가격 폭 ±40% · 고를 거리(가견적 낮은 곳). DB 없음."""

from app.calc import vendor_pick as vp


def cand(
    i: str, pct: int, rating: float | None, reviews: int, done: int, local: bool = True
) -> vp.Candidate:
    return vp.Candidate(i, f"업체{i}", local, 3_000_000 + pct * 30_000, pct, rating, reviews, done)


def test_version_bumped():
    assert vp.VERSION == "vendor-pick-2026.11b"


def test_rating_scale_separates_good_from_ok():
    """별점 4.3과 4.8(리뷰 많음) 차이가 점수에 보여요(÷5 눈금에서는 0.04 남짓이었어요)."""
    ok, good = cand("a", 0, 4.3, 60, 60), cand("b", 0, 4.8, 60, 60)
    assert vp.score(good)[0] - vp.score(ok)[0] > 0.1


def test_done_count_keeps_growing_after_twenty():
    """끝낸 공사 20건과 200건이 같은 값이 아니에요."""
    assert vp.score(cand("a", 0, 4.5, 30, 200))[0] > vp.score(cand("b", 0, 4.5, 30, 20))[0]


def test_value_pick_when_top_three_are_all_pricey():
    """점수 3곳이 모두 비싸면 셋째 자리를 평이 괜찮은 가장 싼 곳으로 바꾸고 사유에 적어요."""
    cs = [
        cand("p1", 18, 4.8, 86, 120),
        cand("p2", 11, 4.6, 131, 180),
        cand("p3", 27, 4.8, 48, 64),
        cand("cheap", 6, 4.5, 27, 35),
        cand("bad", -20, 3.6, 40, 10),  # 가장 싸지만 당긴 별점 4.0 아래 → 넣지 않음
    ]
    picks = vp.pick(cs)
    assert [p.c.vendor_id for p in picks][:2] == ["p1", "p2"]
    last = picks[-1]
    assert last.c.vendor_id == "cheap" and last.value
    assert vp.reasons(last)[0] == "가견적이 낮은 편이에요"
    assert not any(p.value for p in picks[:2])


def test_no_value_swap_when_a_cheap_one_is_already_in():
    cs = [
        cand("a", -10, 4.6, 80, 90),
        cand("b", 15, 4.8, 90, 120),
        cand("c", 20, 4.7, 70, 100),
        cand("d", 25, 4.4, 20, 30),
    ]
    picks = vp.pick(cs)
    assert not any(p.value for p in picks)
    assert "a" in [p.c.vendor_id for p in picks]


def test_no_value_swap_with_three_or_fewer():
    cs = [cand("a", 20, 4.8, 80, 90), cand("b", 25, 4.8, 90, 120), cand("c", -15, 4.5, 30, 40)]
    assert not any(p.value for p in vp.pick(cs))

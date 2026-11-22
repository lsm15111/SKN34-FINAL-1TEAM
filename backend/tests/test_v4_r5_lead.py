"""고침 5차 리드: 빈 집이면 사는 집 준비 줄(가구 · 짐 · 액자 · 선반)을 뺀다(QA r5 c1). DB 없음."""

from app.agent.v3.trades import BY_CODE
from app.assistant.tools import aftercare, cards

HANGINGS = "벽에 건 액자 · 선반 떼기"


def labels(card) -> list[str]:
    return [x["label"] for x in card.data["checklist"]]


def test_empty_home_drops_wall_hangings_and_shelves_from_prep():
    prep = list(BY_CODE["dobae"].prep)
    assert HANGINGS in prep  # 공정 설정 줄이 있어야 이 시험이 뜻이 있어요
    empty = cards.fit_items(prep, cards.HomeCtx(occupied=False))
    assert not [x for x in empty if any(w in x for w in ("액자", "선반", "가구"))]
    assert cards.fit_items(prep, cards.HomeCtx(occupied=True)) == prep
    assert cards.fit_items(prep, None) == prep


def test_before_card_of_an_empty_home_has_no_hangings_but_after_checks_keep_shelves():
    empty = cards.HomeCtx(occupied=False)
    before = labels(aftercare.check_card("b", "before", ["dobae"], [], home=empty))
    assert before and HANGINGS not in before
    lived = labels(aftercare.check_card("b", "before", ["dobae"], [], home=cards.HomeCtx()))
    assert HANGINGS in lived
    # 공사 끝 점검표(목공 '선반 · 수납장 고정')는 빈 집이어도 그대로예요(거름은 공사 전 할 일에만)
    after = labels(aftercare.check_card("a", "after", ["mokgong"], [], home=empty))
    assert any("선반" in x for x in after)


def test_a_shown_choice_chip_card_counts_as_something_to_press():
    from app.assistant import policy

    chips = policy.buttons_of("options", {})
    claim = policy.card_claim("아래 칩에서 [둘 다 취소]를 눌러 주세요.")
    assert chips and claim is not None and claim[0] == "press"
    assert policy.claim_ok(claim, made=(), opened=(), buttons=chips)
    # 칩도 카드도 없으면 그대로 바꿔요
    assert not policy.claim_ok(claim, made=(), opened=(), buttons=())

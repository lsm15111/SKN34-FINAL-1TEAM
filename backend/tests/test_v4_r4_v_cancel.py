"""고침 4차 V(QA r4 s1 C1 · s6 N-1): 보낸 실측 요청이 둘일 때 이름표 없이 부른 취소 도구를 이번 고객 말로 풀기.
업체 이름 하나 → 그 요청 카드 · '둘 다 · 모두' → 요청마다 카드 · 같은 턴 두 번째 고르기는 오류(6번 되풀이 막기) ·
고르기 칩에 '둘 다 취소'. 유료 호출 0회(Claude 대본)."""

from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import propose
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_new_tools import call, cards_of, results, two_requests


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


NO_REF = ("propose_visit_cancel", {"code": "other"})  # 엄격 도구에서 visit_ref를 비운 부름


def cancel_cards(ev) -> dict[str, dict]:
    """이 턴에 열린 취소 승인 카드(요청 id → 카드)."""
    return {
        x["target_id"]: x
        for x in acts(ev)
        if x["kind"] == "visit_cancel" and x["status"] == "proposed"
    }


# ---- 고객 말로 대상 풀기(순수 함수) ----

TWO = [NS(vendor_name="결도배"), NS(vendor_name="마루와벽")]


def names(rows: list, text: str) -> list[str]:
    return [v.vendor_name for v in propose.cancel_targets(rows, text)]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("마루와벽에 보낸 실측 요청 취소해 줘", ["마루와벽"]),  # 고르기 칩이 보내는 말
        ("결도배 요청만 취소해 줘", ["결도배"]),
        ("둘 다 취소해 주세요.", ["결도배", "마루와벽"]),
        ("실측 요청 두 곳 다 취소할래요", ["결도배", "마루와벽"]),
        ("보낸 실측 요청 둘 다 취소해 줘", ["결도배", "마루와벽"]),  # '둘 다 취소' 칩
        ("요청 모두 취소해 줘", ["결도배", "마루와벽"]),
        ("그냥 다 취소해", ["결도배", "마루와벽"]),
        ("결도배랑 마루와벽 취소해 줘", ["결도배", "마루와벽"]),
        ("결도배는 남기고 나머지 취소해 줘", ["마루와벽"]),
        ("결도배 빼고 다 취소", ["마루와벽"]),
        ("결도배는 두고 마루와벽 취소해 줘", ["마루와벽"]),
        ("결도배 요청은 그대로 두고 나머지 취소해 줘", ["마루와벽"]),
        ("결도배에 보낸 요청은 남겨 주세요. 다른 건 취소", ["마루와벽"]),
        ("취소해 줘", []),
        # '다음' · '다시'는 '다'가 아니에요
        ("취소하고 살면서 공사로 바꾼 다음에 다시 요청하면 돼요?", []),
        ("다른 업체로 할래요. 취소해 주세요", []),
    ],
)
def test_cancel_targets_read_the_customer_words(text, want):
    assert names(TWO, text) == want


def test_a_name_inside_another_name_is_not_a_second_target():
    rows = [NS(vendor_name="한결"), NS(vendor_name="한결도배")]
    assert names(rows, "한결도배 취소해 줘") == ["한결도배"]
    three = [*TWO, NS(vendor_name="한결")]
    assert names(three, "결도배는 남기고 취소해 줘") == []  # 남은 둘 중 모름
    assert names(three, "결도배는 남기고 나머지 취소") == ["마루와벽", "한결"]


# ---- 실제 턴 ----


def test_chip_words_with_one_vendor_make_that_card(api, script):
    """s6 12 · 13턴 · s1 8턴: 고르기 칩 글을 보내도 고르기 칩만 6번(도구 상한), 카드 0."""
    w = two_requests(api)
    ev, log = call(script, api, w["pid"], "마루와벽에 보낸 실측 요청 취소해 줘", NO_REF)
    (got,) = results(log)
    assert got["state"] == "new" and got["kind"] == "visit_cancel"
    assert set(cancel_cards(ev)) == {w["visits"]["마루와벽"]}
    assert not cards_of(ev, "options")


def test_both_makes_a_card_for_each_request(api, script):
    """s1 7턴: '둘 다 취소해 주세요.'에 고르기 칩만."""
    w = two_requests(api)
    ev, log = call(script, api, w["pid"], "둘 다 취소해 주세요.", NO_REF)
    (got,) = results(log)
    assert (got["state"], got["count"]) == ("new", 2) and got["note"] == propose.CANCEL_MANY_NOTE
    assert {x["vendor_name"] for x in got["items"]} == {"결도배", "마루와벽"}
    assert all(x["state"] == "new" and x["summary"]["title"] for x in got["items"])
    assert set(cancel_cards(ev)) == set(w["visits"].values())
    # 같은 말을 또 하면 카드를 새로 만들지 않아요(열린 카드 그대로)
    ev, log = call(script, api, w["pid"], "둘 다 취소해 주세요.", NO_REF)
    (got,) = results(log)
    assert {x["state"] for x in got["items"]} == {"same"}


def test_second_choose_in_one_turn_is_an_error_and_the_chip_offers_both(api, script):
    """s1 6 · 7 · 8턴: 같은 고르기 결과를 한 턴에 6번(도구 상한까지)."""
    w = two_requests(api)
    ev, log = call(script, api, w["pid"], "취소해 줘", NO_REF, NO_REF)
    first, second = results(log, 1)[0], results(log, 2)[0]
    assert first["state"] == "choose" and first["note"] == propose.CANCEL_CHOOSE_NOTE
    assert (second["error"], second["message"]) == ("choose_shown", propose.CANCEL_AGAIN)
    refs = {x["vendor_name"]: x["ref"] for x in first["requests"]}
    assert all(f"{r} {n}" in second["hint"] for n, r in refs.items())  # 고객이 말한 업체 이름표로
    assert not cancel_cards(ev)
    (pick,) = cards_of(ev, "options")  # 칩 카드는 한 번만
    options = {o["label"]: o for o in pick["data"]["options"]}
    assert set(options) == {"결도배에 보낸 실측 요청", "마루와벽에 보낸 실측 요청", "둘 다 취소"}
    both = options["둘 다 취소"]["say"]
    assert both == "보낸 실측 요청 둘 다 취소해 줘"
    # '둘 다 취소' 칩을 누르면(그 글이 와요) 요청마다 카드
    ev, _log = call(script, api, w["pid"], both, NO_REF)
    assert set(cancel_cards(ev)) == set(w["visits"].values())
    # 다음 턴엔 다시 물을 수 있어요(표시는 턴마다 새로)
    _ev, log = call(script, api, w["pid"], "음 취소할래요", NO_REF)
    assert results(log)[0]["state"] == "choose"


def test_three_requests_offer_all_instead_of_both():
    rows = [
        NS(vendor_name="결도배", status="requested"),
        NS(vendor_name="마루와벽", status="offered"),
        NS(vendor_name="한결", status="booked"),
    ]
    card = propose.cancel_options(rows)
    labels = [o["label"] for o in card.data["options"]]
    assert labels[-1] == "모두 취소" and len(labels) == 4
    assert card.data["options"][-1]["say"] == "보낸 실측 요청 모두 취소해 줘"
    assert names(rows, "보낸 실측 요청 모두 취소해 줘") == ["결도배", "마루와벽", "한결"]

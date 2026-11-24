"""v4 비서 말과 행동 맞추기: 모델 글이 승인 카드를 만들었다 · 눌러 달라고 하면 이 턴에 제안 도구가 카드를 만들었거나
그 카드가 열려 있을 때만 보낸다(아니면 정직한 한 줄) · 앞으로 하겠다는 말('만들어 드릴게요') · 조건 · 물음이 붙은 제안은
그대로(고침 3차 A2) · 평형('34평')과 면적 기준(계약서 · 타입의 ㎡는 전용)으로 집 정보 승인 카드를 만든다(기준 없는 ㎡는
도구 오류). 유료 호출 0회(Claude 대본)."""

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from tests.conftest import query
from tests.test_v4_assistant_actions import approve
from tests.test_v4_assistant_offers import proposed, tokens, with_delay
from tests.test_v4_assistant_turns import ask, home, ok


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


def test_home_info_takes_pyeong_and_needs_a_basis_for_square_meters(api, script):
    _, pid = home(api)  # 공급 69.4㎡
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_home_info", "input": {"fields": {"area_m2": 84}}}
                ]
            },
            {
                "tool_calls": [
                    {"id": "b", "name": "propose_home_info", "input": {"fields": {"pyeong": 34}}}
                ]
            },
            {"text": "34평으로 바꾸는 카드를 만들었어요. 카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "34평이고 84 타입이라고 들었어요"))
    first = log[1]["messages"][-1]["content"][0]
    assert first["is_error"] and "need_basis" in first["content"]  # ㎡만으로는 기준을 모른다
    (a,) = proposed(ev)
    rows = {r["label"]: r["value"] for r in a["summary"]["rows"]}
    assert rows["면적(㎡)"].startswith("112.4")  # 34평 × 3.3058(계산 엔진)
    assert "카드를 만들었어요" in tokens(ev)
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    p = api.get(f"/projects/{pid}").json()
    assert (p["home"]["area_m2"], p["home"]["area_basis"]) == ("112.4", "supply")


def test_square_meters_with_exclusive_basis_makes_a_card(api, script):
    _, pid = home(api)
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "a",
                        "name": "propose_home_info",
                        "input": {"fields": {"area_m2": 84, "area_basis": "exclusive"}},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "계약서에는 84㎡라고 적혀 있어요"))
    (a,) = proposed(ev)
    rows = {r["label"]: r["value"] for r in a["summary"]["rows"]}
    assert rows["면적(㎡)"].startswith("84") and rows["면적 기준"] == "전용"


def test_card_words_without_a_card_are_made_honest(api, script):
    _, pid = home(api)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_home", "input": {}}]},
            {
                "text": "그 값으로 면적을 고치는 승인 카드를 만들어 드릴게요. "
                "카드를 확인하고 눌러 주세요. 표준견적서도 같이 바뀌어요."
            },
        ]
    )
    ev = ok(ask(api, pid, "면적 다시 봐 주세요"))
    text = tokens(ev)
    # 앞으로 하겠다는 말은 그대로 두고(고침 3차 A2), 누를 것이 없는데 눌러 달라는 말만 정직한 한 줄로
    assert "만들어 드릴게요" in text and "눌러 주세요" not in text
    assert policy.NO_CARD in text and "표준견적서도 같이 바뀌어요" in text
    (saved,) = query("select text from chat_messages where role = 'assistant'")
    assert "눌러 주세요" not in saved["text"]
    # 이 턴에 만들었다는 말(지난 일)은 그대로 정직한 한 줄로 바꾼다
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_home", "input": {}}]},
            {"text": "면적을 고치는 승인 카드를 만들었어요. 표준견적서도 같이 바뀌어요."},
        ]
    )
    text = tokens(ok(ask(api, pid, "면적 고쳐 주세요")))
    assert "만들었어요" not in text and policy.CARD_NOT_MADE in text


def test_card_words_with_a_card_or_an_offer_stay(api, script):
    _, pid = home(api)
    script(
        [
            {
                "text": "방 개수를 고치는 카드를 만들어 드릴게요.",
                "tool_calls": [
                    {"id": "p", "name": "propose_home_info", "input": {"fields": {"rooms": 3}}}
                ],
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "방은 세 개예요"))
    text = tokens(ev)
    assert text.index("카드를 만들어 드릴게요") < text.index("눌러 주세요")  # 순서 그대로
    # 조건이 붙은 제안과 열린 카드를 누르라는 말은 그대로(열린 카드 단추가 하나면 그 이름을 넣어요, QA r9)
    script([{"text": "면적 기준을 알려 주시면 카드를 만들어 드릴게요. 위 카드를 눌러 주세요."}])
    ev = ok(ask(api, pid, "면적은 잘 모르겠어요"))
    text = tokens(ev)
    assert "알려 주시면 카드를 만들어 드릴게요" in text
    assert "위 카드의 [맞아요, 저장]을 눌러 주세요" in text


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("승인 카드를 만들었어요.", "made"),
        ("면적을 고치는 승인 카드를 만들어 뒀어요.", "made"),
        ("면적을 고치는 승인 카드를 만들어 드릴게요.", None),  # 앞으로 하겠다는 말(고침 3차 A2)
        ("날짜가 정해지면 카드로 준비해 둘게요.", None),
        ("카드를 확인하고 눌러 주세요.", "press"),
        ("[맞아요, 저장]을 눌러 주세요.", "press"),
        ("요청 카드는 아까 눌러 주셨어요.", None),  # 지난 일
        ("결과 카드의 링크를 눌러 보세요.", None),  # 승인 카드가 아닌 것
        ("카드의 [채팅 열기]를 눌러 물어보세요.", None),
        ("카드에서 수락을 눌러 주세요.", "press"),
        ("버튼을 누르기 전에는 보내지지 않아요.", None),  # 설명은 눌러 달라는 말이 아니다
        ("기준을 알려 주시면 카드를 만들어 드릴게요.", None),
        ("수락 카드를 만들어 드릴까요?", None),
        ("승인 카드는 아직 만들지 않았어요.", None),
        ("업체가 견적서를 새로 만들었어요.", None),
    ],
)
def test_card_claim_words(text, kind):
    got = policy.card_claim(text)
    assert (got[0] if got else None) == kind


def test_press_words_with_a_shown_button(api, script):
    """이 턴에 보인 공사 날짜 카드에 수락 단추가 있으면 눌러 달라는 말은 그대로 둔다(단추 이름이 없어도: 누를 것이
    있으니 확실히 틀린 말이 아니다, 08-rules)."""
    _, pid, _did = with_delay(api)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {"text": "바뀐 날짜가 괜찮으면 카드에서 수락을 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "업체가 날짜를 바꿨대요"))
    assert proposed(ev) == [] and "카드에서 수락을 눌러 주세요" in tokens(ev)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {"text": "승인 카드를 확인하고 눌러 주세요."},
        ]
    )
    text = tokens(ok(ask(api, pid, "어떻게 하면 돼요?")))
    assert "확인하고 눌러 주세요" in text and policy.NO_CARD not in text


def test_press_and_made_words_change_only_when_surely_wrong():
    named = policy.card_claim("카드에서 수락을 눌러 주세요.")
    assert policy.claim_ok(
        named, set(), set(), policy.buttons_of("schedule", {"proposal_ref": "p1"})
    )
    assert not policy.claim_ok(
        named, set(), set(), policy.buttons_of("schedule", {})
    )  # 누를 것 없음
    plain = policy.card_claim("카드를 확인하고 눌러 주세요.")
    assert policy.claim_ok(plain, set(), set(), {"dates_accept"})  # 보인 화면 카드 단추도 누를 것
    assert policy.claim_ok(plain, set(), {"home_info"})  # 열린 승인 카드
    assert not policy.claim_ok(plain, set(), set(), set())
    made = policy.card_claim("수락 카드를 만들었어요.")
    assert not policy.claim_ok(
        made, set(), {"dates_accept"}, {"dates_accept"}
    )  # 만들었다는 말은 이 턴에 만든 카드가 있어야
    assert policy.claim_ok(
        made, {"visit_slot"}, set()
    )  # 이 턴에 만든 카드가 있으면 종류 낱말은 따지지 않는다


def test_card_claim_names_the_kind():
    assert policy.card_claim("실측 요청 카드를 만들었어요.")[1] == {"visit_request"}
    assert policy.card_claim("면적을 고치는 카드를 만들어 뒀어요.")[1] == {"home_info"}
    assert "date_change" in policy.card_claim("날짜 바꾸기 요청 카드를 만들었어요.")[1]
    assert policy.card_claim("카드를 만들었어요.")[1] == set()

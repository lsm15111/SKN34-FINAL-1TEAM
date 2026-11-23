"""v4 요청 점검(asks.py): 고객 말에서 부탁(수 · 값 · 보일 카드)을 코드가 뽑아 턴 사실에 한 줄로 주고, 턴 끝에 보여 달라 ·
바꾸겠다고 한 카드가 없으면 한 번만 더 기회를 준다. 조사 목표에 빠진 찾을 수 · 판매가를 붙이고, 덜 찾았으면 끝 줄에서
정직하게 말한다. 유료 호출 0회(Claude 대본)."""

import json

import pytest

from app.agent import llm
from app.assistant import asks, research
from app.assistant.models import AssistantResearch
from tests.test_v4_assistant_turns import ask, home, ok, turn_row


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


# ---- 부탁 뽑기 ----


@pytest.mark.parametrize(
    ("text", "count", "unit"),
    [
        ("강남구 도배 업체 5곳 찾아줘", 5, "곳"),
        ("믿집 밖 업체 다섯 군데만 알아봐 줘", 5, "군데"),
        ("유행하는 벽지 세 가지 골라 줘", 3, "가지"),
        ("실크벽지 3개 정도 비교해줘", 3, "개"),
        ("방 3개인데 업체 4곳 추천해줘", 4, "곳"),
        ("2~3곳 추천해 줘", 3, "곳"),
        ("업체도 조사해줘봐 5개까지", 5, "개"),
        ("도배 추천해줘. 방 3개야", None, ""),
        ("방 3개인데 도배 얼마예요?", None, ""),
        ("공사는 3개월 뒤에 해요. 찾아볼게요", None, ""),
        ("한 곳만 알려줘", None, ""),
        ("방 2개 도배만 할래요", None, ""),
    ],
)
def test_count_needs_an_asking_word_after_it(text, count, unit):
    got = asks.extract(text)
    assert (got.count, got.unit) == (count, unit)


@pytest.mark.parametrize(
    ("text", "price"),
    [
        ("첫번째꺼로 하면 얼마정도나올거같아? 가격도 조사해봐", True),
        ("벽지값 알려줘", True),
        ("이 제품 판매가 찾아줘", True),
        ("가격 말고 디자인만 알려줘", False),
        ("가격은 됐고 색만 봐 줘", False),
        ("공사 얼마나 걸려요?", False),
        ("값싼 벽지 말고 튼튼한 거", False),
        ("업체 견적이랑 많이 차이나?", True),
        ("그럼 표준견적서에 벽지 값이 들어가 있어요?", False),
    ],
)
def test_price_ask_and_negation(text, price):
    assert asks.extract(text).price is price


@pytest.mark.parametrize(
    ("text", "show"),
    [
        ("우리 집 정보 변경할게", ("home_info",)),
        ("평수가 틀렸어 고쳐줘", ("home_info",)),
        ("집 정보 보여줘", ("home_info",)),
        ("표준견적서 다시 보여줘", ("standard_quote",)),
        ("공정표 보여줘", ("schedule",)),
        ("견적서 비교해줘", ("quote_compare",)),
        ("받은 견적 보여줘", ("quote_compare",)),
        ("면적은 어떻게 계산해요?", ()),
        ("면적 계산 방법 보여줘", ()),
        ("평형별로 얼마인지 보여줘", ()),
        ("방수 공사 보여줘", ()),
        ("표준견적서 말고 업체 견적서 보여줘", ()),
        ("공사 일정 바꿀래", ()),
        ("표준견적서는 왜 비싸?", ()),
        ("견적서 보여줘", ()),  # 표준인지 업체 것인지 모르면 잡지 않는다
        ("16평으로 바꿔줘", ("home_info",)),
        ("벽지를 합지로 바꿀래요", ("home_info",)),
        ("30평으로 하면 얼마야?", ()),
        ("업체 추천해 주세요", ("vendor_picks",)),
        ("업체 추천은 어떻게 해요?", ()),
        ("오늘 할 일 다시 보기", ("today",)),
        ("평일은 안 돼요. 주말 시간으로만 보여 주세요", ()),  # 실측 시간 카드는 show_card 밖
    ],
)
def test_show_asks_are_narrow(text, show):
    assert asks.extract(text).show == show


def test_line_keys_missing_and_tried():
    a = asks.extract("업체 5곳 가격이랑 찾아주고 집 정보도 보여줘")
    assert a.keys() == ["count", "price", "show:home_info"]
    assert asks.line(a).startswith(
        "이번 부탁(고객 말에서 코드가 뽑음): 5곳 · 값(가격) · 집 정보 카드."
    )
    assert asks.line(asks.NONE) == "" and not asks.extract("도배 순서 알려줘")
    assert asks.missing(a, {"vendor_picks"}) == ["home_info"]
    assert asks.missing(a, asks.tried("get_home", {})) == []
    assert asks.tried("show_card", {"kind": "schedule"}) == {"schedule"}
    assert asks.tried("propose_home_info", {"fields": {}}) == {"home_info"}
    assert asks.tried("answer_question", {}) == set()
    assert asks.tried("recommend_vendors", {}) == {"vendor_picks"}


# ---- 조사 목표 · 끝 줄 ----


def test_research_goal_gets_the_count_and_price_the_model_left_out():
    g = asks.research_goal
    assert (
        g("강남구 아파트 도배 업체", "업체 5곳 찾아줘", "outside_vendors", 200)
        == "강남구 아파트 도배 업체 · 5곳"
    )
    assert (
        g("강남구 아파트 도배 업체 5곳", "업체 5곳 찾아줘", "outside_vendors", 200)
        == "강남구 아파트 도배 업체 5곳"
    )
    assert (
        g("LX 디아망 회벽", "그거 가격도 조사해봐", "materials", 200) == "LX 디아망 회벽 · 판매가"
    )
    assert (
        g("유행 실크 벽지", "벽지 세 가지 가격이랑 찾아줘", "materials", 200)
        == "유행 실크 벽지 · 3가지 · 판매가"
    )
    assert (
        g("도배 업체", "업체 가격 알려줘", "outside_vendors", 200) == "도배 업체"
    )  # 업체 값은 조사하지 않는다
    long = g("가" * 199, "5곳 찾아줘", "outside_vendors", 200)
    assert len(long) <= 200 and long.endswith(" · 5곳")


def test_title_drops_the_added_tail_and_count_reads_gaji():
    assert research.title_of("강남구 아파트 도배 업체 · 5곳") == "강남구 아파트 도배 업체"
    assert research.title_of("LX 디아망 회벽 · 3가지 · 판매가") == "LX 디아망 회벽"
    assert research.want_count("유행 실크 벽지 · 3가지") == 3
    assert research.want_count("공사 3개월 뒤") is None


def row(kind: str, goal: str, result: dict, status: str = "done") -> AssistantResearch:
    return AssistantResearch(
        kind=kind, title=research.title_of(goal), goal=goal, status=status, result=result, notes=[]
    )


def item(name: str, price: dict | None = None) -> dict:
    return {"name": name, "href": f"https://example.kr/{name}", "price": price}


def test_ended_line_says_what_was_short():
    three = [item("가"), item("나"), item("다")]
    r = row(
        "outside_vendors", "강남구 도배 업체 · 5곳", {"items": three, "links": [], "partial": True}
    )
    assert (
        research.ended_line(r)
        == "강남구 도배 업체 조사를 마쳤어요. 부탁하신 5곳 중 3곳을 찾았어요."
    )
    r = row("materials", "유행 실크 벽지 · 3가지 · 판매가", {"items": three[:2], "links": []})
    assert research.ended_line(r) == (
        "유행 실크 벽지 조사를 마쳤어요. 부탁하신 3가지 중 2가지를 찾았어요."
        " 판매가는 판매처 페이지에서 확인하지 못했어요."
    )
    priced = [item("가", {"text": "1롤 32,000원", "won": 32000, "per_roll": True})]
    r = row("materials", "LX 디아망 회벽 · 판매가", {"items": priced, "links": []})
    assert research.ended_line(r) == "LX 디아망 회벽 조사를 마쳤어요."
    # 부탁한 수를 채웠고 덜 찾고 마쳤으면 예전처럼 '찾은 만큼'
    r = row(
        "outside_vendors", "강남구 도배 업체 · 3곳", {"items": three, "links": [], "partial": True}
    )
    assert research.ended_line(r) == "강남구 도배 업체 조사를 마쳤어요. 찾은 만큼 정리했어요."


def test_first_message_says_gaji_and_price_for_materials():
    msg = research._first_message(
        "materials", "유행 실크 벽지 · 3가지 · 판매가", "강남구", [], research.date(2026, 11, 23)
    )
    assert "찾을 수: 3가지(서로 다른 가지로," in msg and "판매가: 고객이 값을 물었어요." in msg
    msg = research._first_message(
        "outside_vendors", "강남구 도배 업체", "강남구", [], research.date(2026, 11, 23)
    )
    assert "찾을 수: 5곳(서로 다른 곳으로," in msg and "판매가:" not in msg


def test_start_research_adds_the_count_from_the_customer_words(api, script):
    _, pid = home(api)
    log = script(
        [
            {"tool_calls": [{"id": "t1", "name": "start_research",
                             "input": {"kind": "outside_vendors", "goal": "노원구 아파트 도배 업체"}}]},
            {"text": "잠깐(1분 안팎) 걸려요."},
        ]
    )  # fmt: skip
    ok(ask(api, pid, "믿집 밖 도배 업체 다섯 군데 찾아줘"))
    got = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    assert got["state"] == "started"
    from tests.conftest import query

    (r,) = query("select goal, title from assistant_research")
    assert r["goal"].endswith(" · 5곳") and "5곳" not in r["title"]


# ---- 턴 끝 점검 ----


def cards(ev) -> list[str]:
    return [d["kind"] for e, d, _ in ev if e == "card"]


def said(ev) -> str:
    return "".join(d.get("text", "") for e, d, _ in ev if e == "token")


def test_missing_card_gets_one_more_try(api, script):
    _, pid = home(api)
    log = script(
        [
            {"text": "어떤 정보를 바꾸고 싶으세요?"},
            {"tool_calls": [{"id": "s1", "name": "show_card", "input": {"kind": "home_info"}}]},
            {"text": "바꿀 칸과 값을 말씀해 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "우리 집 정보 변경할게"))
    assert cards(ev) == ["home_info"]
    assert "요청 점검" not in said(ev) and "바꿀 칸과 값을 말씀해 주세요." in said(ev)
    nudge = log[1]["messages"][-1]["content"][-1]["text"]
    assert nudge.startswith("(요청 점검: 고객이 집 정보 카드를") and "show_card(home_info)" in nudge
    assert "이번 부탁(고객 말에서 코드가 뽑음): 집 정보 카드." in json.dumps(
        log[0], ensure_ascii=False
    )
    trace = turn_row(ev[0][1]["turn_id"])["trace"]
    trace = json.loads(trace) if isinstance(trace, str) else trace
    assert trace["asks"] == {"want": ["show:home_info"], "unmet": [], "retry": True}


def test_card_shown_first_needs_no_more_try(api, script):
    _, pid = home(api)
    log = script(
        [
            {"tool_calls": [{"id": "g1", "name": "get_home", "input": {}}]},
            {"text": "카드에서 바꿀 칸을 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "우리 집 정보 변경할게"))
    assert cards(ev) == ["home_info"] and len(log) == 2
    trace = turn_row(ev[0][1]["turn_id"])["trace"]
    trace = json.loads(trace) if isinstance(trace, str) else trace
    assert trace["asks"] == {"want": ["show:home_info"], "unmet": [], "retry": False}


def test_only_one_more_try_and_unmet_is_recorded(api, script):
    _, pid = home(api)
    log = script([{"text": "공정표는 아직 없어요."}, {"text": "업체를 정하면 공정표가 생겨요."}])
    ev = ok(ask(api, pid, "공정표 보여줘"))
    assert len(log) == 2 and cards(ev) == []
    trace = turn_row(ev[0][1]["turn_id"])["trace"]
    trace = json.loads(trace) if isinstance(trace, str) else trace
    assert trace["asks"] == {"want": ["show:schedule"], "unmet": ["show:schedule"], "retry": True}


def test_turn_without_asks_is_unchanged(api, script):
    _, pid = home(api)
    log = script([{"text": "철거 → 목공 → 도배 순서예요."}])
    ev = ok(ask(api, pid, "도배 순서 알려줘"))
    assert len(log) == 1
    trace = turn_row(ev[0][1]["turn_id"])["trace"]
    trace = json.loads(trace) if isinstance(trace, str) else trace
    assert "asks" not in trace
    assert "이번 부탁" not in json.dumps(log[0], ensure_ascii=False)

"""v4 비서 글 점검(docs/v4/06-answer-audit.md 5절) 카드 갈래 몫: 턴 사실 '최근 처리한 카드'(#2) · 기간을 답한 뒤
못 받아요 카드 없음 · 업체 '수락 안 했는데'(#3) · 도구 오류 글에 이름표 · 도구 이름 없음 + 모델 힌트 · 실측 시간 도구는
이름표가 꼭(#4) · 무료 모드 오분류(#5 · #7) · 카드 위 한 줄 되풀이 · 인사 턴 도구 막기(#8) · 조사 '로/으로'(#9) ·
먼저 말 걸기 · 새 소식 끝말(#10) · 도구 값 빈칸(#11) · 지식 발췌 · 출처(#14) · 카드만 턴 기록 글(#15).
유료 호출 0회(무료 모드 또는 Claude 대본)."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions, free, policy, proactive
from app.assistant.tools import REGISTRY
from app.assistant.tools.cards import excerpt, knowledge_card, news_line
from app.shared.korean import euro
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose
from tests.test_dates import ready as dates_ready
from tests.test_deal import confirm
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import customer, offered, requested, vendor
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_free import cards_of, said, vendor_turn
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login


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


def result_of(log: list[dict], step: int) -> dict:
    """대본 step번째 요청에 실린 마지막 도구 결과(JSON)."""
    block = log[step]["messages"][-1]["content"][0]
    return {"is_error": block.get("is_error", False), **json.loads(block["content"])}


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


# ---- #5 · #7 · #8 무료 모드 ----


def test_free_mode_answers_what_was_asked(api):
    llm.clear_stubs()
    vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = customer(api)

    def turn(text: str) -> tuple[str, list[str]]:
        ev = ok(ask(api, pid, text))
        assert ev[-1][1]["mode"] == "free"
        return said(ev), [d["kind"] for e, d, _ in ev if e == "card" and d["kind"] != "answer"]

    text, _ = turn("도배 공사 며칠 걸려요?")
    assert "예상" in text and "부가세" not in text  # 금액이 아니라 예상 일수(계산 엔진 값)
    text, kinds = turn("살면서 도배할 수 있어요?")
    assert text != free.HOME and "home_info" not in kinds  # 되는지 묻는 말은 지식 답
    text, _ = turn("도배 견적이 적정한지 어떻게 알 수 있어요?")
    assert text != free.NO_QUOTES
    assert turn("공사 날짜를 미뤄야 하면 어떻게 해요?")[0] == free.CHANGE_HOW_EARLY
    text, kinds = turn("오늘 점심 뭐 먹지?")
    assert text != free.TODAY  # '오늘'만으로 오늘 할 일을 띄우지 않는다
    assert turn("내용증명에는 무엇을 적어야 효과가 있어요?")[0] == free.LEGAL
    text, kinds = turn("기억해: 내 예산은 3,000만 원이야.")
    assert text == free.MEMORY_SAY and "standard_quote" not in kinds
    text, kinds = turn("저는 주말에만 시간이 되고, 강아지가 있어요.")
    assert text == free.PREFS and kinds == ["today"]
    assert turn("안녕하세요") == (free.SMALL_TALK_HI, [])
    assert turn("고마워요") == (free.SMALL_TALK, [])
    assert turn("오늘 뭐 하면 돼요?")[0] in (free.TODAY, free.TODAY_NONE)  # 할 일 묻는 말은 그대로


def test_free_vendor_brief_and_customer_accept_words(api):
    llm.clear_stubs()
    f = requested(api)
    login(api, f["email"])
    ev = ok(vendor_turn(api, f["visit"], "새 요청 브리핑해 줘"))
    assert said(ev) == free.BRIEF and cards_of(ev, "vendor_brief")
    ev = ok(vendor_turn(api, f["visit"], "고객이 아직 수락 안 했는데 공사 날짜 확정으로 바꿔 줘."))
    assert said(ev) == free.ACCEPT_RULE  # 기간 답하기 카드를 만들지 않는다(RT36)
    assert [a for a in acts(ev) if a["status"] == "proposed"] == []


def test_free_schedule_and_plan_do_not_repeat_the_card_line(api):
    llm.clear_stubs()
    customer_token, pid, did, _ = dates_ready(api)
    assert propose(api, did, *days(10)).status_code == 200
    use(api, customer_token)
    ev = ok(ask(api, pid, "공사 날짜 보여 줘"))
    (card,) = cards_of(ev, "schedule")
    assert said(ev) == free.DATES and not said(ev).startswith(card["say"])


# ---- #3 못 받아요는 기간을 답하기 전만 ----


def test_decline_card_only_before_the_window_is_answered(api):
    llm.clear_stubs()
    f = offered(api)  # 업체가 기간을 답함(offered)
    login(api, f["email"])
    ev = ok(vendor_turn(api, f["visit"], "이번 건은 바빠서 못 받아요"))
    assert [a for a in acts(ev) if a["status"] == "proposed"] == []
    assert said(ev).startswith("기간을 답한 뒤에는 못 받아요를 보낼 수 없어요")


# ---- #4 도구 오류 글 · 힌트 · 실측 시간 도구 입력 ----


def test_tool_errors_keep_refs_and_tool_names_in_the_hint(api, script):
    _, pid = home(api)
    assert "ref" in REGISTRY["vendor_free_slots"].schema["required"]  # 이름표 없이 부를 수 없다
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_visit_slot", "input": {"slot_ref": "s9"}}
                ]
            },
            {
                "tool_calls": [
                    {
                        "id": "b",
                        "name": "vendor_free_slots",
                        "input": {"prefer": "am", "days": "any"},
                    }
                ]
            },
            {"text": "실측 시간을 다시 찾아볼게요."},
        ]
    )
    ok(ask(api, pid, "실측 시간 골라 줘"))
    ref = result_of(log, 1)
    assert ref["is_error"] and ref["error"] == "unknown_ref"
    assert "s9" not in ref["message"] and "s9" in ref["hint"]  # 사람에게 보일 글에는 이름표가 없다
    bad = result_of(log, 2)
    assert bad["error"] == "bad_input" and "ref" in bad["hint"]  # 빠진 칸을 모델에 알린다


# ---- #2 턴 사실: 최근 처리한 카드 ----


def test_turn_facts_list_recently_processed_cards(api, script):
    _, pid = home(api)
    script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_home_info", "input": {"fields": {"rooms": 3}}}
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    (a,) = [x for x in acts(ok(ask(api, pid, "방은 세 개예요"))) if x["status"] == "proposed"]
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    log = script([{"text": "방 개수를 고쳤어요."}])
    ok(ask(api, pid, "방 개수 바뀌었어요?"))
    assert "최근 처리한 카드: 집 정보 저장(승인해 실행됨)" in facts_of(log[0])


# ---- #8 인사 턴은 도구를 부르지 못한다 ----


def test_greeting_turn_sends_tool_choice_none(api, script):
    _, pid = home(api)
    log = script([{"text": "네, 궁금한 게 있으면 물어봐 주세요."}])
    ok(ask(api, pid, "고마워요"))
    assert log[0]["tool_choice"] == {"type": "none"} and log[0]["tools"]  # 도구 정의는 그대로(캐시)
    log = script([{"text": "집 정보예요."}])
    ok(ask(api, pid, "네"))  # 앞 물음에 답하는 말은 막지 않는다
    assert log[0]["tool_choice"] == {"type": "auto"}
    assert policy.small_talk("알겠어요, 감사합니다!") and not policy.small_talk(
        "고마워요. 실측은 언제예요?"
    )


# ---- #9 조사 · #10 끝말 ----


def test_particles_and_line_endings():
    assert [euro(x) for x in ("마루와벽", "결도배", "11.24(화) 오전", "11.30(일)", "ABC")] == [
        "마루와벽으로",
        "결도배로",
        "11.24(화) 오전으로",
        "11.30(일)로",
        "ABC(으)로",
    ]
    s = actions.confirm_summary("마루와벽", 2, 3_388_000, 3, date(2026, 12, 5))
    assert (s.title, s.approve_label) == ("마루와벽으로 확정", "마루와벽으로 확정")
    assert news_line("결도배가 실측 견적서를 보냈어요 · 도배") == (
        "결도배가 실측 견적서를 보냈어요",
        "도배",
    )
    assert news_line("새 소식") == ("새 소식", None)
    # 먼저 말 걸기 틀(이 갈래가 고친 줄. 자동화 갈래가 더한 글은 빼요)은 '· 지역.'이 아니라 '요'로 끝난다
    mine = [
        (x, c)
        for x in ("visit_offered", "quote_sent", "dates_proposed")
        for c in ("feed", "notify")
    ]
    mine += [("work_eve", "notify"), ("no_pick", "notify"), ("visit_requested", "feed")]
    mine += [("visit_picked", "feed"), ("deal_confirmed", "feed")]
    for name, channel in mine:
        t = proactive.TRIGGERS[name]
        f = proactive.Facts(
            trigger=t.name,
            channel=channel,
            surface=t.surface,
            names={"vendor": "마루와벽", "trade": "도배", "area": "노원구 상계동 도배"},
        )
        assert proactive.template(f).endswith(("요.", "요?")), (name, channel)


# ---- #11 도구 값 ----


def test_tool_values_name_what_is_missing_or_chosen(api, script):
    _token, pid, va, _vb, _ = deal_setup(api)
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "s", "name": "get_standard_quote", "input": {"trade": "mokgong"}}
                ]
            },
            {"tool_calls": [{"id": "c", "name": "compare_quotes", "input": {"trade": "dobae"}}]},
            {"text": "견적서를 견줘 봤어요."},
        ]
    )
    ok(ask(api, pid, "목공 표준견적서랑 견적서 보여 줘"))
    std = result_of(log, 1)
    assert "목공" in std["missing"] and std["trades"] == ["도배"]  # 도배 값을 목공 값으로 읽지 않게
    cols = result_of(log, 2)["cols"]
    quoted = [c for c in cols if c.get("version")]  # 빈 값은 모델 값에서 빠진다(기다림 업체)
    assert quoted and all(c.get("vat_way") for c in quoted)  # 부가세 방식(화면 말)
    assert confirm(api, pid, va).status_code == 200
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "compare_quotes", "input": {"trade": "dobae"}}]},
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_vendor_confirm", "input": {"visit_ref": "m1"}}
                ]
            },
            {"text": "이미 확정했어요."},
        ]
    )
    ok(ask(api, pid, "마루와벽으로 확정해 줘"))
    err = result_of(log, 2)
    assert err["error"] == "already_chosen" and err["message"].startswith(
        "이미 마루와벽으로 확정했어요"
    )


def test_vendor_picks_value_has_the_basis(api, script):
    vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = customer(api)
    log = script(
        [
            {"tool_calls": [{"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}]},
            {"text": "이 집 조건에 맞는 업체예요."},
        ]
    )
    ok(ask(api, pid, "업체 추천해 줘"))
    assert result_of(log, 1)["basis"]  # 고른 기준(비면 '추천 이유가 없어요'라고 말했다)


# ---- #14 지식 발췌 · 출처 ----


def test_knowledge_card_cuts_at_sentences_and_shows_public_names():
    long = "도배 전에는 벽의 먼지를 닦아요. " + "가" * 200 + "."
    assert excerpt(long) == "도배 전에는 벽의 먼지를 닦아요."
    assert excerpt("가나다 " * 60).endswith("…") and len(excerpt("가나다 " * 60)) <= 160
    book = SimpleNamespace(
        text="1) 현장준비 물품\n① 안전용구",
        official=False,
        source_type="시공 안내서",
        publisher="시공 안내서(책, 팀 내부 참고)",
        title="인테리어 시공 안내서 · 공사 전 준비",
    )
    kcs = SimpleNamespace(
        text="초배지는 겹쳐 붙여요.",
        official=True,
        source_type="표준시방서",
        publisher="국토교통부",
        title="KCS",
    )
    card = knowledge_card("k", "도배 준비", [book, kcs])
    assert card.data["source"] == "시공 안내서 · 국토교통부" and "내부" not in card.data["source"]
    assert card.data["lines"][0] == "1) 현장준비 물품 ① 안전용구"


# ---- #15 카드만 보낸 턴의 기록 글 ----


def test_cards_only_turn_saves_screen_names(api, script):
    _, pid = home(api)
    script([{"tool_calls": [{"id": "h", "name": "get_home", "input": {}}]}, {"text": ""}])
    ok(ask(api, pid, "집 정보 보여 줘"))
    (row,) = query("select text from chat_messages where role = 'assistant'")
    assert row["text"] == "(카드를 보여 줬어요: 집 정보)"

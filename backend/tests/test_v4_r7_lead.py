"""QA r7 리드 고침: 실측 요청 칸(공정마다 3곳)이 다 차면 추천 카드를 보내지 않고, 모자라면 요청 승인 카드를
만들지 않아요(c1 높음: 다 찬 뒤 추천 카드 → 요청 카드 승인이 409 slots_full). 유료 호출 0회(Claude 대본)."""

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import customer as customer_tools
from app.assistant.tools import propose
from tests.test_v3_visit_kit import add, customer, quiet, vendor
from tests.test_v3_visit_kit import ask as send_visits
from tests.test_v4_assistant_cards import proposed
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_r6_a1_cards import RECOMMEND, SHOW_PICKS, cards, tool_result


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


NAMES = ("결도배", "마루와벽", "한결도배", "솜씨도배", "바른도배")


def test_slots_bound_request_cards_and_picks(api, script, monkeypatch):
    quiet(monkeypatch)
    vids = [vendor(api, f"r7v{i}@mitjip.test", n) for i, n in enumerate(NAMES)]
    _, pid = customer(api)
    for v in vids[:2]:
        assert add(api, pid, v).status_code == 201
    r = send_visits(api, pid, vids[:2])
    assert r.status_code == 201, r.text  # 2곳 진행 중 → 빈 칸 하나

    # 빈 칸이 하나인데 두 곳 요청 카드는 만들지 않아요(만들면 승인 때 409 slots_full)
    req = {
        "id": "p",
        "name": "propose_visit_request",
        "input": {"trade": "dobae", "vendor_refs": ["v1", "v2"]},
    }
    log = script(
        [
            {"tool_calls": [RECOMMEND]},
            {"tool_calls": [req]},
            {"text": "한 곳만 더 요청할 수 있어요."},
        ]
    )
    ev = ok(ask(api, pid, "추천한 두 곳에도 실측 요청해 줘"))
    assert cards(ev, "vendor_picks")  # 빈 칸이 있으면 추천 카드는 보여요
    assert tool_result(log, 1)["count"] == 3
    err = tool_result(log, 2)
    assert err["error"] == "slots_full" and err["message"] == propose.slots_full_said(2, 1)
    assert "1곳만 더 요청할 수 있어요" in err["message"]
    assert proposed(ev) == []

    # 3곳째가 차면 추천 · 카드 다시 보이기 모두 카드 없이 까닭 · 다음 할 일
    assert add(api, pid, vids[2]).status_code == 201
    r = send_visits(api, pid, [vids[2]])
    assert r.status_code == 201, r.text
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "요청 3곳이 다 찼어요."}])
    ev = ok(ask(api, pid, "업체 추천해 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got["count"] == 0 and got["picks"] == []
    assert customer_tools.FULL_NOTE in got["note"] and got["next"].startswith("진행 중인")
    assert any(e == "status" and d.get("task") for e, d, _ in ev)  # 진행 중인 요청 작업 카드

    log = script([{"tool_calls": [SHOW_PICKS]}, {"text": "요청 3곳이 다 찼어요."}])
    ev = ok(ask(api, pid, "추천 카드 다시 보여 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got.get("shown") is None and customer_tools.FULL_NOTE in got["note"]


def test_slots_full_said_reads_both_ways():
    assert propose.slots_full_said(3, 0) == (
        "실측 요청은 공정마다 3곳까지예요. 지금 3곳이 진행 중이라 새 업체에 요청할 수 없어요. "
        "진행 중인 요청 한 곳을 취소하면 다른 업체에 요청할 수 있어요."
    )
    assert "2곳만 더 요청할 수 있어요" in propose.slots_full_said(1, 2)


# ---- 앞 턴 카드를 두고 한 '만들었어요'를 반대 말로 바꾸지 않기(QA r7 c1 9턴) ----


def test_made_words_about_an_earlier_card_are_dropped_not_reversed(api, script):
    from app.assistant import policy
    from tests.test_v4_assistant_actions import approve
    from tests.test_v4_assistant_offers import proposed as offered
    from tests.test_v4_assistant_offers import tokens
    from tests.test_v4_assistant_turns import home

    _, pid = home(api)
    script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_home_info", "input": {"fields": {"rooms": 3}}}
                ]
            },
            {"text": "방 개수를 고치는 카드를 확인해 주세요."},
        ]
    )
    (a,) = offered(ok(ask(api, pid, "방은 세 개예요")))
    assert approve(api, a["action_id"], seen=a["target_ver"]).status_code == 200
    # 다음 턴 '?': 방금 승인한 카드를 두고 '만들었어요'라고 해도 '아직 만들지 않았어요'로 뒤집지 않아요
    script([{"text": "방금 방 개수를 고치는 승인 카드를 만들었어요. 저장도 끝났어요."}])
    text = tokens(ok(ask(api, pid, "?")))
    assert policy.CARD_NOT_MADE not in text and "만들었어요" not in text
    assert "저장도 끝났어요" in text


# ---- 날짜 바꾸기 이유의 연락처는 고객에게 가림(QA r7 화면 N1) ----


def test_change_reason_hides_contacts_from_the_customer(api):
    from tests.helpers import use
    from tests.test_final_plan import DOB, after, both_accepted, propose

    customer_token, pid, _dm, dd = both_accepted(api)
    said = "급하면 010-1234-5678로 전화 주세요."
    r = propose(api, "maru@mitjip.test", dd, after(DOB[1]), kind="change", reason=said)
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["reason"] == said  # 업체 본인 화면은 쓴 그대로
    use(api, customer_token)
    got = api.get(f"/projects/{pid}/schedule").json()
    (x,) = [t["proposal"] for t in got["trades"] if t["proposal"] and t["proposal"]["reason"]]
    assert "010-1234-5678" not in x["reason"] and "전화 주세요" in x["reason"]


# ---- 날짜 바꾸기 후보는 지금 시작일에 가까운 바란 날부터(QA r7 c4: '하루만 당겨'가 닷새 당김) ----


def test_change_candidates_start_with_the_wish_closest_to_the_current_start():
    import uuid
    from datetime import date, timedelta
    from types import SimpleNamespace

    from app.assistant.tools import aftercare as aftercare_tools
    from tests.test_v4_assistant_qa_r1 import TODAY, FakeJob, _clear_monday

    mon = _clear_monday()
    wishes = [
        mon - timedelta(days=n) for n in (3, 4, 5)
    ]  # 앞 주 금 · 목 · 수(가까운 순, 요청 카드 순서)
    req = SimpleNamespace(id=uuid.uuid4(), wish_dates=sorted(wishes))  # 서버는 날짜순으로 저장해요
    job = FakeJob(plan_start=mon, start_date=mon, request=req)
    got = aftercare_tools.request_candidates(job, uuid.uuid4(), TODAY)
    starts = [date.fromisoformat(c["start"]) for c in got]
    assert starts and starts == sorted(starts, key=lambda d: abs((d - mon).days))
    assert starts[0] == max(starts)  # 당기기: 가장 늦은(가까운) 날이 첫 후보
    # 아직 수락 전(다른 날짜 요청)은 날짜순 그대로
    first = FakeJob(status="confirmed", plan_start=mon, request=req)
    got = aftercare_tools.request_candidates(first, uuid.uuid4(), TODAY)
    starts = [date.fromisoformat(c["start"]) for c in got]
    assert starts == sorted(starts)


# ---- 화면 단추 길 안내는 승인 카드 말이 아니에요(QA r7 c4 T20 · V22) ----


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("공사 한 건 화면의 [공사 끝 알리기]를 눌러 주세요.", None),
        ("[리뷰 쓰기]를 눌러 주세요.", None),
        ("공사 화면에서 [날짜 바꾸기] 버튼을 눌러 주세요.", None),
        ("카드에서 [리뷰 쓰기]를 눌러 주세요.", "press"),  # 카드를 가리키면 카드 말
        ("카드를 확인하고 눌러 주세요.", "press"),
        ("[맞아요, 저장]을 눌러 주세요.", "press"),
    ],
)
def test_screen_button_guidance_is_not_a_card_claim(text, kind):
    from app.assistant import policy

    got = policy.card_claim(text)
    assert (got[0] if got else None) == kind


def test_due_note_shows_midnight_as_the_day_before_24():
    """QA r8 u1: 비서 '기다리는 중' 카드 기한이 '11.27 00:00까지'였어요(화면은 '11.26(목) 24:00까지')."""
    from datetime import datetime

    from app.assistant.tools import cards
    from app.shared.clock import SEOUL

    assert cards.due_note(datetime(2026, 11, 27, 0, 0, tzinfo=SEOUL)) == "11.26 24:00까지"
    assert cards.due_note(datetime(2026, 11, 26, 18, 30, tzinfo=SEOUL)) == "11.26 18:30까지"


# ---- 날짜 바꾸기 카드에 지금 날짜와 바꾸자는 말(QA r8 u1 U3) ----


def test_delay_schedule_card_shows_the_current_dates(api, script):
    from tests.test_v4_assistant_offers import with_delay

    _, pid, _did = with_delay(api)
    script(
        [
            {"tool_calls": [{"id": "s", "name": "show_card", "input": {"kind": "schedule"}}]},
            {"text": "바꾸자는 날짜를 카드에서 확인해 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "공사 날짜 보여 줘"))
    (card,) = [d for e, d, _ in ev if e == "card" and d["kind"] == "schedule"]
    data = card["data"]
    assert data["phase"] == "dates" and data["now_start"] and data["now_end"]
    assert data["now_start"] != data["start"]  # 지금 날짜와 바꾸자는 날이 따로
    assert card["say"].endswith("공사 날짜를 바꾸자고 했어요.")


def test_offer_result_gives_the_card_note_to_the_model(api, script, monkeypatch):
    """판정 에이전트 r8 S15: 카드 아래 안내(누르면 · 수락 전 무엇이 되는지)가 모델 값에 없어 다음 걸음에 못 썼어요."""
    quiet(monkeypatch)
    vendor(api, "r7note@mitjip.test", "결도배")
    _, pid = customer(api)
    req = {
        "id": "p",
        "name": "propose_visit_request",
        "input": {"trade": "dobae", "vendor_refs": ["v1"]},
    }
    log = script(
        [{"tool_calls": [RECOMMEND]}, {"tool_calls": [req]}, {"text": "카드를 만들었어요."}]
    )
    ev = ok(ask(api, pid, "결도배에 실측 요청해 줘"))
    (a,) = proposed(ev)
    got = tool_result(log, 2)
    assert got["state"] == "new" and got["summary"]["note"] == a["summary"]["note"]
    assert "48시간" in got["summary"]["note"]


# ---- 필요 · 원인 · 하자 증상 물음은 금액 · 기간 낱말이 있어도 공정 전문가로(QA r8 d1) ----


@pytest.mark.parametrize(
    ("kind", "question", "want"),
    [
        ("price", "초배 꼭 해야 해요? 빼면 얼마예요?", "general"),
        ("period", "이음매가 몇 달 뒤에 벌어지면 어떻게 해요?", "general"),
        ("period", "겨울에 보일러 켜 둬야 해요?", "general"),
        ("price", "곰팡이 생긴 벽은 비용이 더 드나요?", "general"),
        ("price", "왜 이렇게 비싸요?", "price"),  # 이 공사 금액 물음은 v3 그대로
        ("price", "표준견적서 초배 줄은 얼마예요?", "price"),
        ("period", "공사 얼마나 기다려야 해요?", "period"),
    ],
)
def test_need_and_symptom_questions_go_to_the_trade_experts(kind, question, want):
    from app.assistant.tools import answer

    assert answer.kind_of(kind, question) == want
    if want == "general":
        assert not answer.money_first(question)

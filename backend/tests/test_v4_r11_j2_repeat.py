"""QA 11차 뒤 J2: 칩 · 다음에 물을 말 되풀이(r11 c1 T2 · c2 T4 · T19, r10 c1 T13~T15). 유료 호출 0회(Claude 대본).

- (가) 고객이 방금 보낸 말과 같은(띄움 · 문장부호만 다른) 칩은 빼요: 카드 칩(턴 끝 · 대화 기록) · 고르기 칩(offer_choices)
  · 다음에 물을 말.
- (나) 바로 앞 턴에 보인 다음에 물을 말은 단계 · 상태(제안 글)가 그대로면 다시 내지 않아요(단계 제안 · 먼저 말 건 줄 제안
  · 업체 오늘 할 일). 단계가 바뀌면 다시 나와요. 모델이 낸 고르기 칩은 (가)만 걸어요.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from tests.conftest import query
from tests.test_v3_visit_kit import add, customer, requested, vendor
from tests.test_v4_assistant_free import cards_of, vendor_turn
from tests.test_v4_assistant_nudges import add_nudge
from tests.test_v4_assistant_turns import ask, ok
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


def done_of(ev) -> dict:
    assert ev[-1][0] == "done", ev[-1]
    return ev[-1][1]


def ideas(api, script, pid: str, text: str) -> list[str]:
    """글만 답하는 턴 하나 → 다음에 물을 말 id."""
    script([{"text": "벽지는 바탕이 중요해요."}])
    return [x["id"] for x in done_of(ok(ask(api, pid, text)))["suggest"]]


def nowon(api) -> tuple[str, str]:
    """노원구 업체 2곳 + 고객 공사(고객으로 로그인한 채). (공사 id, 첫 업체 id)"""
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    return pid, a


# ---- (나) 다음에 물을 말 ----


def test_step_idea_is_not_repeated_while_the_stage_stays(api, script):
    pid, _ = nowon(api)
    got = [ideas(api, script, pid, f"실크벽지 관리는 어떻게 해요 {i}") for i in range(3)]
    # r11 c1 T1 · T2, c2 T3 · T4: 같은 단계 두 턴 연속 '업체 n곳을 골라 둘까요?'
    assert [("step-standard" in x) for x in got] == [True, False, False]


def test_step_idea_comes_back_when_the_stage_changes(api, script):
    pid, a = nowon(api)
    assert "step-standard" in ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 1")
    assert "step-standard" not in ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 2")
    # 업체를 담으면 단계가 바뀌어요(업체 고르기 → 실측 일정): 그 단계 제안이 나와요
    assert add(api, pid, a).status_code == 201
    got = ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 3")
    assert "step-pick" in got and "step-standard" not in got
    # 다시 빼면 업체 고르기 단계로 돌아와 같은 제안이 다시 나와요
    r = api.delete(f"/projects/{pid}/shortlist/{a}", params={"trade": "dobae"})
    assert r.status_code == 204, r.text
    assert "step-standard" in ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 4")


def test_nudge_idea_is_not_repeated_on_the_next_turn(api, script):
    pid, _ = nowon(api)
    uid = query("select id from users where email = 'home@mitjip.test'")[0]["id"]

    def nudge() -> uuid.UUID:
        return add_nudge(
            uid,
            trigger="no_pick",
            channel="feed",
            status="sent",
            project_id=uuid.UUID(pid),
            sent_at=datetime.now(UTC) - timedelta(minutes=1),
            body="표준견적서를 본 뒤 업체를 아직 담지 않았어요.",
            src="guide",
        )

    first = nudge()
    assert f"n-{first}" in ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 1")
    # 다음 턴에는 같은 줄도, 같은 말의 새 줄도(r10 c1 T13~T15 '받은 견적서를 견줘 볼까요?' 세 턴) 다시 내지 않아요.
    # 같은 말(업체 추천해 줘)의 단계 제안도 마찬가지예요
    second = nudge()
    got = ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 2")
    assert not {f"n-{first}", f"n-{second}", "step-standard"} & set(got)
    assert not {f"n-{first}", f"n-{second}"} & set(
        ideas(api, script, pid, "실크벽지 관리는 어떻게 해요 3")
    )


def vendor_ideas(api, script, text: str) -> list[str]:
    script([{"text": "새 요청이 있어요."}])
    return [x["id"] for x in done_of(ok(vendor_turn(api, None, text)))["suggest"]]


def test_vendor_today_idea_is_not_repeated(api, script):
    f = requested(api)
    login(api, f["email"])
    assert "today-new" in vendor_ideas(api, script, "오늘 뭐 해요?")
    assert "today-new" not in vendor_ideas(api, script, "다른 건요?")


# ---- (가) 방금 보낸 말과 같은 칩 ----


def test_chip_same_as_what_was_just_said_is_dropped(api, script):
    _, pid = customer(api)
    show = {"tool_calls": [{"id": "s", "name": "show_card", "input": {"kind": "standard_quote"}}]}
    script([show, {"text": "가견적은 업체가 확인한 단가로 계산해요."}])
    # r11 c2 T19: 칩 '가견적은 어떻게 계산해요?'가 방금 물은 말과 같았어요(띄움 · 문장부호만 달라도 같은 말)
    ev = ok(ask(api, pid, "가견적은  어떻게 계산해요"))
    assert cards_of(ev, "standard_quote")
    chips = done_of(ev)["chips"]
    assert chips == ["업체 추천해 줘"]
    # 다시 열 때(대화 기록)의 칩도 같아요
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    assert feed["chips"] == chips


def test_idea_same_as_what_was_just_said_is_dropped(api, script):
    # 다음에 물을 말 '새 요청을 정리해 볼까요?'(보내는 말 '새 요청 브리핑해 줘')를 문장부호만 다르게 말한 첫 턴
    f = requested(api)
    login(api, f["email"])
    assert "today-new" not in vendor_ideas(api, script, "새 요청 브리핑해 줘!")


def test_offer_choices_drops_only_the_option_just_said(api, script):
    _, pid = customer(api)
    args = {
        "title": "무엇부터 볼까요?",
        "options": [
            {"label": "견적 금액부터", "say": "견적 금액부터 볼래요"},
            {"label": "벽지부터", "say": "벽지부터 볼래요"},
        ],
    }
    call = {"tool_calls": [{"id": "c", "name": "offer_choices", "input": args}]}

    def options(text: str) -> list[str]:
        script([call, {"text": "견적 금액부터 볼까요, 벽지부터 볼까요?"}])
        (card,) = cards_of(ok(ask(api, pid, text)), "options")
        return [o["say"] for o in card["data"]["options"]]

    assert options("기다리는 동안 뭐 할 수 있어요?") == ["견적 금액부터 볼래요", "벽지부터 볼래요"]
    assert options("견적 금액부터 볼래요.") == ["벽지부터 볼래요"]
    # 모델이 낸 고르기 칩은 바로 앞 턴과 같아도 그대로 보여요((나)는 걸지 않아요)
    assert options("음 잘 모르겠어요") == ["견적 금액부터 볼래요", "벽지부터 볼래요"]

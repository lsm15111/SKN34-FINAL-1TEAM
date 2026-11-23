"""v4 고침 갈래 FA1(QA r6 c3 H1): 추천할 업체가 0곳이면 빈 카드 대신 까닭 · 다음 할 일, show_card는 보인 카드의
핵심 값을 모델에 돌려주고, 한 턴에 같은 카드를 두 번 보내지 않아요. 유료 호출 0회(Claude 대본)."""

import json

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import runtime
from app.assistant.tools import customer
from tests.helpers import use
from tests.test_v3_visit_kit import add, quiet, requested, vendor
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


def tool_result(log, call: int, block: int = 0) -> dict:
    """대본 log의 call번째 LLM 호출이 받은 마지막 도구 결과(모델에 간 값)."""
    return json.loads(log[call]["messages"][-1]["content"][block]["content"])


def cards(ev, kind: str | None = None) -> list[dict]:
    return [d for e, d, _ in ev if e == "card" and (kind is None or d["kind"] == kind)]


RECOMMEND = {"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}
SHOW_PICKS = {"id": "s", "name": "show_card", "input": {"kind": "vendor_picks"}}


def test_zero_picks_send_no_card_and_tell_why_and_next(api, script, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)  # 노원구 업체 하나(마루와벽)에 이미 실측 요청
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "더 추천할 업체는 없어요."}])
    ev = ok(ask(api, f["pid"], "업체 추천해 줘"))
    assert not cards(ev, "vendor_picks")  # 빈 카드를 보내지 않아요
    got = tool_result(log, 1)
    assert got["count"] == 0 and got["picks"] == []
    assert any("마루와벽" in w and "진행 중" in w for w in got["why"])
    assert got["next"] == customer.NEXT_LIVE.format(steps="마루와벽 답 기다림")
    assert customer.NONE_NOTE in got["note"]
    # 진행 중인 요청은 작업 카드로 보여요(누를 곳)
    assert any(e == "status" and d.get("task") for e, d, _ in ev)


def test_zero_picks_in_an_empty_area_point_outside_once(api, script):
    _, pid = home(api)  # 업체가 하나도 없는 지역
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "아직 업체가 없어요."}])
    ev = ok(ask(api, pid, "업체 추천해 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got["count"] == 0 and "단가를 확인한 도배 업체가 아직 없어요" in got["why"][0]
    assert got["next"] == customer.NEXT_OUTSIDE


def test_show_card_gives_the_shown_values_and_no_empty_picks(api, script, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    log = script([{"tool_calls": [SHOW_PICKS]}, {"text": "업체는 다 요청했어요."}])
    ev = ok(ask(api, f["pid"], "추천 카드 다시 보여 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got.get("shown") is None and got["count"] == 0 and got["next"]
    # 고를 수 있는 업체가 생기면 카드와 함께 몇 곳 · 어느 업체인지 모델에 가요
    login_vendor = vendor(api, "gyeol@mitjip.test", "결도배")
    use(api, f["token"])
    assert add(api, f["pid"], login_vendor).status_code == 201
    log = script([{"tool_calls": [SHOW_PICKS]}, {"text": "결도배예요."}])
    ev = ok(ask(api, f["pid"], "추천 카드 다시 보여 줘"))
    (card,) = cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got["shown"] == "vendor_picks" and got["count"] == 1
    assert [p["name"] for p in got["picks"]] == ["결도배"]
    assert got["picks"][0]["ref"] == card["data"]["picks"][0]["ref"]


def test_same_card_is_sent_once_per_turn(api, script, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    other = vendor(api, "gyeol@mitjip.test", "결도배")
    use(api, f["token"])
    assert add(api, f["pid"], other).status_code == 201
    log = script([{"tool_calls": [RECOMMEND, SHOW_PICKS]}, {"text": "결도배를 골라 왔어요."}])
    ev = ok(ask(api, f["pid"], "업체 추천해 줘"))
    assert len(cards(ev, "vendor_picks")) == 1  # 같은 카드는 한 번만
    second = tool_result(log, 1, block=1)  # show_card 결과
    assert runtime.SAME_CARD in second["note"] and second["count"] == 1
    done = next(d for e, d, _ in ev if e == "done")
    assert done["cards"] == ["picks-dobae"]


def test_shown_of_keeps_names_and_counts_only():
    model = {
        "area": "노원구",
        "count": 2,
        "picks": [
            {"ref": "v1", "name": "결도배", "estimate_won": 3_000_000, "reasons": ["별점"]},
            {"ref": "v2", "name": "마루와벽", "estimate_won": 3_200_000, "proposed": True},
        ],
        "basis": ["긴 기준 글"],
    }
    got = customer.shown_of("vendor_picks", model)
    assert got == {
        "shown": "vendor_picks",
        "area": "노원구",
        "count": 2,
        "picks": [
            {"ref": "v1", "name": "결도배", "estimate_won": 3_000_000},
            {"ref": "v2", "name": "마루와벽", "estimate_won": 3_200_000, "proposed": True},
        ],
    }
    assert customer.shown_of("home_info", {"facts": ["서울 노원구"], "locked": False}) == {
        "shown": "home_info",
        "facts": ["서울 노원구"],
        "locked": False,
    }

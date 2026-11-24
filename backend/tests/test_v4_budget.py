"""희망 예산(갈래 P3, 사용자 결정 11-24 '공사 조건 칸으로'). 기억은 금액을 그대로 막고(고정 선 7), 고객이 말한 예산은
비서 승인 카드(propose_budget)를 눌러야 집 정보 '예산' 칸(projects.budget_won)에 저장돼요(고정 선 1). 화면 길은 집 정보
고치기(PATCH)예요. 저장된 값은 턴 사실 · 보드에 그대로 가고(고정 선 2), 값 꼴은 DB CHECK(0024: 10만 원 ~ 100억 원 · 만 원
단위)가 지켜요. 유료 호출 0회(Claude 대본)."""

import uuid

import asyncpg
import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import memory
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v3_project_home import HOME, create
from tests.test_v4_assistant_actions import action_row, acts, approve, code
from tests.test_v4_assistant_handled import handled, sweep
from tests.test_v4_assistant_memory import remember_job
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_vendor_profile import approved_vendor
from tests.test_visit_inbox import login

SAID = "예산은 250만 원 안쪽이면 좋겠어요"


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


def offer(api, script, pid: str, won: int = 2_500_000, said: str = SAID):
    """대본 턴: 비서가 propose_budget을 불러요. (이벤트, LLM 요청 기록)"""
    log = script(
        [
            {"tool_calls": [{"id": "b", "name": "propose_budget", "input": {"max_won": won}}]},
            {"text": "희망 예산 카드를 만들었어요."},
        ]
    )
    return ok(ask(api, pid, said)), log


def opened(ev) -> dict:
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    return a


def tool_result(log) -> dict:
    return log[1]["messages"][-1]["content"][0]


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def said(ev) -> str:
    return "".join(d["text"] for e, d, _ in ev if e == "token")


def budget(api, pid: str) -> int | None:
    return api.get(f"/projects/{pid}").json()["budget_won"]


def no_budget_home(api, email: str = "nob@mitjip.test") -> str:
    signup(api, email)
    r = create(api, {**HOME, "budget_won": None})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- 저장은 승인 카드로만 ----


def test_budget_card_saves_only_when_pressed(api, script):
    _, pid = home(api)  # 집 정보 예산 300만 원(HOME)
    ev, log = offer(api, script, pid)
    a = opened(ev)
    assert a["kind"] == "budget" and a["target_ver"] == "3000000"
    sm = a["summary"]
    assert (sm["title"], sm["approve_label"]) == ("희망 예산 저장", "맞아요, 저장")
    assert sm["rows"] == [{"label": "희망 예산", "value": "250만 원", "sub": "지금 300만 원"}]
    assert "업체 요청서에도 보여요" in sm["note"]
    res = tool_result(log)
    assert not res.get("is_error") and "250만 원" in res["content"]
    assert budget(api, pid) == 3_000_000  # 누르기 전에는 그대로
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "executed"
    assert done["result"]["text"] == "희망 예산을 250만 원으로 저장했어요"
    p = api.get(f"/projects/{pid}").json()
    # 표준견적서 계산에 들지 않아 집 정보 rev는 그대로예요(열린 집 정보 · 실측 요청 카드가 낡지 않게)
    assert (p["budget_won"], p["home"]["budget_won"], p["rev"]) == (2_500_000, 2_500_000, 1)
    assert approve(api, a["action_id"]).json() == done  # 두 번 눌러도 같은 결과
    board = api.get("/assistant/board", params={"project_id": pid}).json()
    assert board["budget_won"] == 2_500_000


def test_budget_card_from_no_budget_and_reject_keeps_nothing(api, script):
    pid = no_budget_home(api)
    ev, _ = offer(api, script, pid)
    a = opened(ev)
    assert a["target_ver"] == "-" and a["summary"]["rows"][0]["sub"] == "지금 아직 몰라요"
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"
    assert budget(api, pid) is None
    assert api.get("/assistant/board", params={"project_id": pid}).json()["budget_won"] is None


def test_budget_card_refuses_bad_or_same_values(api, script):
    _, pid = home(api)  # 300만 원
    for won, why in ((50_000, "bad_input"), (2_505_000, "bad_input"), (3_000_000, "no_change")):
        ev, log = offer(api, script, pid, won=won, said="예산은 300만 원이에요")
        res = tool_result(log)
        assert res["is_error"] and why in res["content"], (won, res)
        assert not acts(ev)
    assert query("select id from assistant_actions") == []


def test_budget_value_is_checked_by_db(api):
    _, pid = home(api)
    pid_ = uuid.UUID(pid)
    for bad in (
        50_000,
        2_505_000,
        20_000_000_000,
    ):  # 10만 원 아래 · 만 원 단위 아님 · 100억 원 넘음
        with pytest.raises(asyncpg.CheckViolationError):
            query("update projects set budget_won = $2 where id = $1", pid_, bad)
    query("update projects set budget_won = $2 where id = $1", pid_, 2_500_000)
    assert budget(api, pid) == 2_500_000


def test_budget_card_and_screen_are_for_the_owner_only(api, script):
    _, pid = home(api)
    a = opened(offer(api, script, pid)[0])
    body = {**HOME, "budget_won": 2_000_000}
    home(api, "other@mitjip.test")
    assert approve(api, a["action_id"]).status_code == 404  # 남의 카드
    assert api.patch(f"/projects/{pid}", json=body).status_code == 404  # 남의 공사(화면 길)
    assert ask(api, pid, SAID).status_code == 404  # 남의 공사 대화
    use(api, approved_vendor(api))
    assert approve(api, a["action_id"]).status_code == 403  # 업체
    assert api.patch(f"/projects/{pid}", json=body).status_code == 403
    login(api, "home@mitjip.test")
    assert budget(api, pid) == 3_000_000 and action_row(a["action_id"])["status"] == "proposed"


def test_budget_card_goes_stale_when_the_screen_changes_it(api, script):
    _, pid = home(api)
    a = opened(offer(api, script, pid)[0])
    # 화면(집 정보 고치기)에서 예산을 바꿨어요: 옛 카드는 옛 값으로 덮지 않아요
    assert api.patch(f"/projects/{pid}", json={**HOME, "budget_won": 2_000_000}).status_code == 200
    assert code(approve(api, a["action_id"])) == (409, "stale")
    assert budget(api, pid) == 2_000_000
    # 정리(sweep): 열린 카드의 대상 값이 비서 밖에서 바뀌면 처리된 것으로 닫아요
    b = opened(offer(api, script, pid, won=2_200_000)[0])
    assert b["target_ver"] == "2000000"
    query("update projects set budget_won = 2400000 where id = $1", uuid.UUID(pid))
    sweep(api)
    assert handled(b["action_id"])


def test_budget_follows_the_home_lock(api, script):
    _, pid = home(api)
    a = opened(offer(api, script, pid)[0])
    query("update projects set locked_at = now() where id = $1", uuid.UUID(pid))
    sweep(api)  # 잠긴 공사의 열린 카드는 닫혀요(업체 요청서에 간 값)
    assert handled(a["action_id"])
    ev, log = offer(api, script, pid, won=2_200_000)
    res = tool_result(log)
    assert res["is_error"] and "locked" in res["content"] and not acts(ev)
    assert api.patch(f"/projects/{pid}", json={**HOME, "budget_won": 2_200_000}).status_code == 409
    assert budget(api, pid) == 3_000_000


def test_budget_card_fails_if_locked_before_press(api, script):
    _, pid = home(api)
    a = opened(offer(api, script, pid)[0])
    query("update projects set locked_at = now() where id = $1", uuid.UUID(pid))
    assert code(approve(api, a["action_id"])) == (409, "locked")
    assert budget(api, pid) == 3_000_000


# ---- 턴 사실 · 숫자 검사(고정 선 2) ----


def test_saved_budget_is_a_turn_fact_for_the_number_check(api, script):
    pid = no_budget_home(api)
    line = "희망 예산 270만 원 안에서 볼게요."
    log = script([{"text": f"{line} 표준견적서부터 볼까요?"}])
    ev = ok(ask(api, pid, "견적 볼 때 뭐부터 봐요?"))
    assert "희망 예산" not in facts_of(log[0])
    assert line not in said(ev)  # 근거 없는 금액은 빠져요
    # 화면에서 넣기(집 정보 고치기): 다음 턴 사실에 저장 값 그대로
    assert api.patch(f"/projects/{pid}", json={**HOME, "budget_won": 2_700_000}).status_code == 200
    log = script([{"text": line}])
    ev = ok(ask(api, pid, "견적 볼 때 뭐부터 봐요?"))
    assert "\n희망 예산: 270만 원" in facts_of(log[0])
    assert line in said(ev)


def test_approved_budget_shows_in_the_next_turn_facts(api, script):
    _, pid = home(api)
    a = opened(offer(api, script, pid)[0])
    log = script([{"text": "알겠어요."}])
    ok(ask(api, pid, "오늘 뭐 하면 돼요?"))
    facts = facts_of(log[0])
    assert "\n희망 예산: 300만 원" in facts and "희망 예산 저장" in facts  # 승인 기다리는 카드
    assert approve(api, a["action_id"]).status_code == 200
    log = script([{"text": "알겠어요."}])
    ok(ask(api, pid, "오늘 뭐 하면 돼요?"))
    facts = facts_of(log[0])
    assert "\n희망 예산: 250만 원" in facts and "300만 원" not in facts


# ---- 기억에는 금액이 남지 않아요(고정 선 7) ----


def test_budget_talk_never_lands_in_memory(api, script):
    _, pid = home(api)
    ok(ask(api, pid, "예산 250만 원 이하예요"))  # 금액만: 기억 뽑기 일을 만들지 않아요
    assert query("select id from jobs where kind = 'assistant_memory'") == []
    text = "예산은 250만 원 안쪽이고 실크가 좋아요"
    items = [
        {
            "key": "priority",
            "value": "예산 250만 원 안쪽",
            "evidence_quote": "예산은 250만 원 안쪽이고",
        },
        {"key": "material", "value": "실크", "evidence_quote": text},
    ]
    remember_job(api, script, pid, text, items)
    rows = query("select key, value, evidence_quote from assistant_memory")
    assert [(r["key"], r["value"], r["evidence_quote"]) for r in rows] == [
        ("material", "실크", "실크")
    ]  # 금액 줄은 버리고, 금액이 든 인용은 값으로 줄여요
    a = opened(offer(api, script, pid)[0])
    assert approve(api, a["action_id"]).status_code == 200  # 예산은 공사 칸에만
    shown = api.get("/assistant/memory").json()
    board = api.get("/assistant/board", params={"project_id": pid}).json()
    texts = [m["value"] for m in shown] + [m.get("evidence_quote") or "" for m in shown]
    texts += [m["value"] for m in board["memory"]]
    assert texts and not [t for t in texts if memory.MONEY.search(t)], texts
    assert board["budget_won"] == 2_500_000

"""v4 비서 승인 카드: 같은 사람 · 같은 대상 · 같은 종류는 열린 카드 하나(대화 · 먼저 말 걸기가 같은 행을 씀) ·
고객이 거절한 제안은 새 사실(판 · 금액 · 날짜) 없이 다시 만들지 않음(도구는 오류 대신 모델 값, 사람이 카드 단추를 누르면
만듦) · 동시에 같은 제안 두 번은 행 하나 · 같은 행동 승인 두 번은 실행 한 번 · 업체 두 곳이면 반나절 카드도 요청마다 하나 ·
공사 날짜 수락 단추는 하나 · 같은 오류 두 번이면 멈춤. 유료 호출 0회(Claude 대본)."""

import asyncio
import json
import uuid

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions, proactive
from app.assistant.schemas import ActionSummary
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import now_utc
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose
from tests.test_dates import ready as dates_ready
from tests.test_v3_visit_kit import add, answer, customer, offered, quiet, vendor, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import action_row, acts, approve, propose_home
from tests.test_v4_assistant_nudges import at, nudges, run
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


def proposed(ev) -> list[dict]:
    return [x for x in acts(ev) if x["status"] == "proposed"]


def tokens(ev) -> str:
    return "".join(d["text"] for e, d, _ in ev if e == "token")


def cards_of(ev, kind: str) -> list[dict]:
    return [d for e, d, _ in ev if e == "card" and d["kind"] == kind]


def scheduled(api) -> tuple[str, str, str]:
    """도배를 마루와벽으로 확정하고 처음 날짜를 수락한 집(scheduled). (고객 토큰, 공사 id, 확정 id). 고객으로 로그인."""
    token, pid, did, _ = dates_ready(api)
    start, end = days(10)
    x = propose(api, did, start, end).json()["proposal"]["id"]
    use(api, token)
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json={"seen_version": 0})
    assert r.status_code == 200, r.text
    return token, pid, did


def with_delay(api) -> tuple[str, str, str]:
    """수락한 뒤 업체가 날짜를 바꾸자고 한 집(바뀐 날짜 수락 기다림)."""
    token, pid, did = scheduled(api)
    login(api, "maru@mitjip.test")
    r = propose(api, did, *days(24), kind="change", reason="자재가 늦게 와요.")
    assert r.status_code == 200, r.text
    use(api, token)
    return token, pid, did


DELAY_TURN = [
    {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
    {"tool_calls": [{"id": "d", "name": "propose_delay_accept", "input": {"proposal_ref": "p1"}}]},
    {"text": "바뀐 날짜를 카드에서 확인해 주세요."},
]


# ---- 거절한 제안은 다시 만들지 않는다(S13) ----


def test_rejected_card_is_not_made_again_without_new_facts(api, script):
    _, pid, _did = with_delay(api)
    script(DELAY_TURN)
    ev = ok(ask(api, pid, "업체가 날짜를 미루자는데 어떻게 돼요?"))
    (a,) = proposed(ev)
    assert a["kind"] == "delay_accept"
    r = api.post(f"/assistant/actions/{a['action_id']}/reject")
    assert r.json()["status"] == "rejected"
    # 같은 날짜 · 같은 공정표 판으로 다시 만들려 하면 도구는 오류 대신 '거절한 제안' 값을 돌려준다
    log = script(DELAY_TURN)
    ev = ok(ask(api, pid, "입주가 그 뒤라서 괜찮을까요?"))
    assert proposed(ev) == []
    res = log[2]["messages"][-1]["content"][0]
    assert not res.get("is_error") and "고객이 거절한 제안이에요" in res["content"]
    rows = query("select status from assistant_actions where kind = 'delay_accept'")
    assert [x["status"] for x in rows] == ["rejected"]
    # 사람이 카드 단추를 직접 누르면 다시 만든다(사람이 새로 정함)
    (sched,) = cards_of(ev, "schedule")
    assert sched["data"]["proposal_ref"] == "p1"  # 열린 승인 카드가 없으니 카드 단추가 있다
    script([{"text": "카드를 확인해 주세요."}])
    press = {"card_id": sched["card_id"], "choice": "delay_accept:p1"}
    ev = ok(ask(api, pid, "이 날짜로 수락할래요", context=press))
    (again,) = proposed(ev)
    assert again["kind"] == "delay_accept" and again["action_id"] != a["action_id"]


def test_nudge_does_not_remake_a_rejected_card(api, script, monkeypatch):
    """먼저 말 걸기(바뀐 날짜)가 만든 승인 카드를 거절한 뒤 대화가 같은 카드를 다시 만들지 않는다(S13)."""
    quiet(monkeypatch)
    _, pid, _did = with_delay(api)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    (n,) = [x for x in nudges(trigger="dates_proposed") if x["status"] == "sent"]
    assert n["action_id"] is not None
    assert api.post(f"/assistant/actions/{n['action_id']}/reject").json()["status"] == "rejected"
    log = script(DELAY_TURN)
    ev = ok(ask(api, pid, "도배 업체가 날짜를 미루자는데 어떻게 돼요?"))
    assert proposed(ev) == []
    assert "고객이 거절한 제안이에요" in log[2]["messages"][-1]["content"][0]["content"]
    assert query("select count(*) n from assistant_actions")[0]["n"] == 1


# ---- 대화 · 먼저 말 걸기가 같은 행을 쓴다 ----


def test_nudge_keeps_the_open_card_the_chat_made(api, script, monkeypatch):
    quiet(monkeypatch)
    f = offered(api)
    script(
        [
            {"tool_calls": [{"id": "t", "name": "today_tasks", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "s",
                        "name": "vendor_free_slots",
                        "input": {"ref": "m1", "prefer": "any", "days": "any"},
                    }
                ]
            },
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_visit_slot", "input": {"slot_ref": "s2"}}
                ]
            },
            {"text": "고른 시간으로 카드를 만들었어요."},
        ]
    )
    ev = ok(ask(api, f["pid"], "실측 날짜 골라 줘"))
    (mine,) = proposed(ev)
    llm.clear_stubs()
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    (n,) = nudges(trigger="visit_offered")
    assert str(n["action_id"]) == mine["action_id"]  # 대화에서 고른 카드를 덮지 않는다
    rows = query("select id, status from assistant_actions where kind = 'visit_slot'")
    assert [(str(x["id"]), x["status"]) for x in rows] == [(mine["action_id"], "proposed")]
    card = json.loads(n["card"])["data"]
    picked = json.loads(action_row(mine["action_id"])["payload"])
    (chosen,) = [c for c in card["candidates"] if c["ref"] == card["chosen"]]
    assert (chosen["day"], chosen["half"]) == (picked["day"], picked["half"])


def test_chat_reuses_the_nudge_card_for_the_same_slot(api, script, monkeypatch):
    quiet(monkeypatch)
    f = offered(api)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    (n,) = nudges(trigger="visit_offered")
    first = json.loads(n["card"])["data"]["candidates"][0]["ref"]
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_visit_slot", "input": {"slot_ref": first}}
                ]
            },
            {"text": "위 카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, f["pid"], "첫 번째 시간으로 할게요"))
    (same,) = proposed(ev)
    assert same["action_id"] == str(n["action_id"])
    body = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    assert body["state"] == "same" and "이미 열려" in body["note"]
    assert query("select count(*) n from assistant_actions")[0]["n"] == 1


def test_same_offer_twice_at_once_makes_one_row(api, monkeypatch):
    from app.assistant import repository as repo

    _, pid = home(api)
    uid = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    real = repo.replace_open

    async def go():
        gate = asyncio.Barrier(2)

        async def both_here(*a, **k):  # 두 제안이 열린 카드를 본 뒤 같이 넣게 한다(넣기 경쟁)
            try:
                await asyncio.wait_for(gate.wait(), 1.0)
            except TimeoutError:
                pass
            return await real(*a, **k)

        monkeypatch.setattr(repo, "replace_open", both_here)
        async with SessionLocal() as s:
            user = await s.get(User, uid)

        async def one():
            async with SessionLocal() as s:
                row, _ = await actions.propose(
                    s,
                    user,
                    surface="customer",
                    kind="home_info",
                    target_kind="project",
                    target_id=uuid.UUID(pid),
                    target_ver="1",
                    payload={"fields": {"rooms": 3}},
                    summary=ActionSummary(title="집 정보 저장", approve_label="맞아요, 저장"),
                    now=now_utc(),
                    project_id=uuid.UUID(pid),
                    turn_id=uuid.uuid4(),
                )
                await s.commit()
                return row.id

        return await asyncio.gather(one(), one(), return_exceptions=True)

    got = asyncio.run(go())
    assert not [x for x in got if isinstance(x, BaseException)], got
    assert got[0] == got[1]
    rows = query("select status from assistant_actions")
    assert [x["status"] for x in rows] == ["proposed"]


def test_two_approvals_at_once_run_once_and_the_other_is_409(api, script, monkeypatch):
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 2})
    uid = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    real = actions.EXECUTORS["home_info"]

    async def slow(*args):
        await asyncio.sleep(0.3)  # 첫 승인이 처리 중일 때 둘째가 온다
        return await real(*args)

    monkeypatch.setitem(actions.EXECUTORS, "home_info", slow)

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
        aid = uuid.UUID(a["action_id"])
        return await asyncio.gather(
            actions.execute(user, aid, "customer", None, now_utc()),
            actions.execute(user, aid, "customer", None, now_utc()),
            return_exceptions=True,
        )

    got = asyncio.run(go())
    oks = [x for x in got if not isinstance(x, BaseException)]
    errs = [x for x in got if isinstance(x, BaseException)]
    assert len(oks) == 1 and oks[0].status == "executed"
    assert len(errs) == 1 and isinstance(errs[0], AppError)
    assert (errs[0].status, errs[0].code) == (409, "in_progress")
    assert query("select rev from projects")[0]["rev"] == 2  # 한 번만 실행
    again = approve(api, a["action_id"])
    assert again.status_code == 200 and again.json()["status"] == "executed"
    assert query("select rev from projects")[0]["rev"] == 2


def test_two_vendors_get_one_slot_card_each_and_each_runs_once(api, monkeypatch):
    """F1 '반나절 실행 2건': 업체 두 곳에 실측을 요청하면 먼저 말 걸기가 요청마다 반나절 카드를 하나씩 만든다(대상이
    다름). 두 카드를 승인하면 요청마다 한 번씩 실행되고, 같은 카드를 다시 눌러도 다시 실행되지 않는다."""
    quiet(monkeypatch)
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = customer(api)
    for v in (a, b):
        assert add(api, pid, v).status_code == 201
    assert ask_visits(api, pid, [a, b]).status_code == 201
    for email, v in (("maru@mitjip.test", a), ("gyeol@mitjip.test", b)):
        login(api, email)
        assert answer(api, visit_of(pid, v)).status_code == 200
    use(api, token)
    llm.clear_stubs()
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    lines = nudges(trigger="visit_offered")
    assert len(lines) == 2 and all(x["action_id"] for x in lines)
    rows = query("select id, target_id from assistant_actions where kind = 'visit_slot'")
    assert len({x["target_id"] for x in rows}) == 2  # 요청마다 하나
    for x in rows:
        assert approve(api, str(x["id"])).json()["status"] == "executed"
        assert approve(api, str(x["id"])).json()["status"] == "executed"  # 다시 눌러도 같음
    booked = query("select status from visits where project_id = $1", uuid.UUID(pid))
    assert sorted(x["status"] for x in booked) == ["booked", "booked"]
    done = query("select count(*) n from assistant_actions where status = 'executed'")
    assert done[0]["n"] == 2


# ---- 공사 날짜 수락 단추는 하나(F1 18) ----


def test_dates_nudge_card_leaves_the_accept_button_to_the_approval_card(api, monkeypatch):
    quiet(monkeypatch)
    token, _pid, did, _ = dates_ready(api)
    assert propose(api, did, *days(10)).status_code == 200
    use(api, token)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    (n,) = nudges(trigger="dates_proposed")
    card = json.loads(n["card"])
    assert card["kind"] == "schedule" and n["action_id"] is not None
    assert card["data"]["proposal_ref"] is None and card["data"]["proposal_kind"] is None
    assert card["data"]["action_id"] == str(n["action_id"])


def test_chat_dates_card_is_swapped_after_the_approval_card(api, script):
    token, pid, did, _ = dates_ready(api)
    assert propose(api, did, *days(10)).status_code == 200
    use(api, token)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_dates_accept", "input": {"proposal_ref": "p1"}}
                ]
            },
            {"text": "수락 카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "공사 날짜 어때요?"))
    (a,) = proposed(ev)
    first, last = cards_of(ev, "schedule")
    assert first["card_id"] == last["card_id"]  # 같은 카드를 바꿔 끼운다
    assert first["data"]["proposal_ref"] == "p1"
    assert last["data"]["proposal_ref"] is None and last["data"]["action_id"] == a["action_id"]
    # 다음 턴에 공사 날짜를 다시 보여도 승인 카드가 열려 있으면 카드 단추는 없다
    script([{"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]}, {"text": "네."}])
    ev = ok(ask(api, pid, "공사 날짜 다시 보여 줘"))
    (again,) = cards_of(ev, "schedule")
    assert again["data"]["proposal_ref"] is None and again["data"]["action_id"] == a["action_id"]


# ---- 같은 오류 두 번이면 멈춘다 ----


def test_same_error_twice_in_one_reply_stops(api, script):
    _, pid = home(api)
    bad = {"name": "propose_visit_slot", "input": {"slot_ref": "s9"}}
    log = script(
        [{"tool_calls": [{"id": "a", **bad}, {"id": "b", **bad}]}, {"text": "다시 해 볼게요."}]
    )
    ev = ok(ask(api, pid))
    assert len(log) == 1  # 같은 답 안의 두 번째 같은 오류 뒤 더 부르지 않는다
    (fail,) = [d for e, d, _ in ev if e == "card" and d["card_id"].startswith("fail-")]
    assert fail["data"]["text"].startswith("같은 문제가 두 번 나서 멈췄어요")
    assert ev[-1][1]["stopped"] is True


def test_same_code_from_different_tools_keeps_going(api, script):
    _, pid = home(api)
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_visit_slot", "input": {"slot_ref": "s9"}}
                ]
            },
            {
                "tool_calls": [
                    {"id": "b", "name": "propose_vendor_confirm", "input": {"visit_ref": "m9"}}
                ]
            },
            {"text": "고를 수 있는 것이 없어요."},
        ]
    )
    ev = ok(ask(api, pid))
    assert len(log) == 3 and ev[-1][1]["stopped"] is False  # 도구가 다르면 멈추지 않는다

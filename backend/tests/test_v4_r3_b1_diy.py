"""QA 3차 고침 B1(직접 할 일): 리드 결정 11-22.

- s6 B1: 직접 할 일의 원본은 저장된 칩뿐이에요. 기억은 카드 · 실측 요청 '업체에 알릴 것' · 업체 브리핑에 넣지 않아요.
  직접 할 일 카드를 거두거나 거절하면 저장되지 않은 일, 칩을 줄이거나 '없어요'로 저장하면 빠진 일을 말하는 기억
  조각도 지워요. 칩이 바뀌면 열린 실측 요청 카드는 새 판(같은 업체 · 같은 조건 + 새 직접 할 일)으로 바뀌고, 화면에서
  칩을 바꾼 뒤 옛 카드를 누르면 보내지 않고 새 판을 만들어요(409 diy_changed). 한 번 더 요청도 지금 칩을 써요.
- c2 21턴 · c3 12 · 16 · 19 · 21 · 24번 · c6: 확정한 업체도 공사가 시작되기 전까지는 사본을 고치고 알려요. '따로
  알리세요'는 공사가 시작돼 사본을 고칠 수 없고 사본에 지금 직접 할 일이 빠졌을 때만이에요.
- r2 c6: 업체 종 알림 '오후를 골랐어요'(받침 따라 을 · 를).
유료 호출 0회(무료 모드 · Claude 대본)."""

import json
import uuid
from datetime import timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions
from app.assistant.tools import diy as diy_tools
from app.visit import flow
from app.visit.flow import DIY_DEALT_NOTE
from tests import test_v3_visit_kit as kit
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import TODAY, notes
from tests.test_deal import confirm, setup
from tests.test_v4_assistant_actions import action_row, approve, code, propose_home
from tests.test_v4_assistant_card_state import picks_request
from tests.test_v4_assistant_diy import chips
from tests.test_v4_assistant_free import said
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login

TOLD = diy_tools.TOLD_LABEL


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


def payload(aid: str) -> dict:
    p = action_row(aid)["payload"]
    return json.loads(p) if isinstance(p, str) else p


def summary(aid: str) -> dict:
    s = action_row(aid)["summary"]
    return json.loads(s) if isinstance(s, str) else s


def result(aid: str) -> dict:
    r = action_row(aid)["result"]
    return (json.loads(r) if isinstance(r, str) else r) or {}


def told_rows(rows: list[dict]) -> list[str]:
    return [r["value"] for r in rows if r["label"] == TOLD]


def memory_row(api, pid: str, key: str, value: str, quote: str) -> None:
    """기억 한 줄(기억 뽑기 결과와 같은 꼴). 근거는 이 공사 대화의 고객 메시지(무료 턴)예요."""
    llm.clear_stubs()
    ok(ask(api, pid, "안녕하세요"))
    (msg,) = query(
        "select id from chat_messages where role = 'user' order by created_at desc limit 1"
    )
    uid = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    query(
        "insert into assistant_memory (id, user_id, key, value, evidence_message_id, evidence_quote)"
        " values ($1, $2, $3, $4, $5, $6)",
        uuid.uuid4(),
        uid,
        key,
        value,
        msg["id"],
        quote,
    )


def memory(key: str = "diy") -> dict | None:
    rows = query("select value, evidence_quote from assistant_memory where key = $1", key)
    return dict(rows[0]) if rows else None


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


def diy_plan(api, script, pid: str) -> dict:
    """직접 할 일 도구(diy_plan all)가 모델에 준 값."""
    log = script(
        [
            {"tool_calls": [{"id": "d", "name": "diy_plan", "input": {"item": "all"}}]},
            {"text": "직접 할 일을 정리했어요."},
        ]
    )
    ok(ask(api, pid, "직접 할 일 정리해 줘"))
    return tool_result(log, 1)


# ---- 1. 거둔 직접 할 일이 다음 실측 요청에 다시 들어감(s6 B1) ----


def test_withdrawn_diy_card_drops_memory_and_next_request_has_no_paint_qa_r3_s6(api, script):
    kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    memory_row(api, pid, "diy", "문틀 페인트 직접", "문틀 페인트는 제가 직접 칠할게요")
    a = propose_home(api, script, pid, {"diy": ["paint"]})
    script(
        [
            {
                "tool_calls": [
                    {"id": "w", "name": "withdraw_proposal", "input": {"kind": "home_info"}}
                ]
            },
            {"text": "문틀 페인트 카드를 거뒀어요. 저장된 건 없어요."},
        ]
    )
    ok(ask(api, pid, "음 아니다, 그 카드 취소해 줘"))
    assert (action_row(a["action_id"])["status"], result(a["action_id"])["reason"]) == (
        "rejected",
        actions.WITHDRAWN,
    )
    assert memory() is None  # 거둔 일은 기억에서도 빠져요
    assert api.get("/assistant/memory").json() == []  # 기억 화면에서도
    req = picks_request(api, pid)
    assert told_rows(req["summary"]["rows"]) == []  # 다음 실측 요청 카드에 페인트가 없어요
    assert "diy" not in payload(req["action_id"])
    r = approve(api, req["action_id"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (v,) = query("select id, diy from visits")
    assert v["diy"] == []
    login(api, "maru@mitjip.test")
    assert api.get(f"/vendor/assistant/briefs/{v['id']}").json()["diy"] == []  # 업체 브리핑에도


def test_memory_alone_is_not_the_source_for_cards_or_requests(api):
    kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    memory_row(api, pid, "diy", "페인트 직접 · 콘센트 커버", "페인트랑 콘센트 커버는 제가 할게요")
    req = picks_request(api, pid)
    assert told_rows(req["summary"]["rows"]) == [] and "diy" not in payload(req["action_id"])
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    # 칩을 안 골랐으면 고른 일이 없어요(기억으로 안 채워요)
    assert said(ev) == diy_tools.FREE_NOT_ASKED
    assert memory()["value"] == "페인트 직접 · 콘센트 커버"  # 기억은 그대로(지울 까닭이 없어요)
    # 칩을 저장하면 그 칩이 카드에 들어가요
    chips(api, pid, ["outlet"])
    req2 = picks_request(api, pid)
    assert told_rows(req2["summary"]["rows"]) == ["고객이 직접 해요 — 콘센트 · 스위치 커버"]


def test_diy_plan_tool_without_chips_says_memory_is_not_saved(api, script):
    _, pid = home(api)
    memory_row(api, pid, "diy", "문틀 페인트 직접", "문틀 페인트는 제가 직접 칠할게요")
    got = diy_plan(api, script, pid)
    assert (got["state"], got["items"]) == ("not_asked", [])
    assert got["note"] == diy_tools.SRC_NOTE["not_asked"] and "저장 전" in got["note"]


def test_saving_fewer_or_no_chips_drops_those_memory_parts(api, script):
    _, pid = home(api)
    memory_row(
        api,
        pid,
        "diy",
        "문틀 페인트 직접 · 욕실 실리콘 · 장판 직접",
        "문틀 페인트랑 욕실 실리콘은 제가 할게요 / 장판은 제가 직접 깔려고요",
    )
    a = propose_home(api, script, pid, {"diy": ["silicone"]})
    assert approve(api, a["action_id"], seen=a["target_ver"]).json()["status"] == "executed"
    got = memory()
    assert got["value"] == "욕실 실리콘 · 장판 직접"  # 저장 목록에 없는 페인트만 빠져요
    assert got["evidence_quote"] == (
        "문틀 페인트랑 욕실 실리콘은 제가 할게요 / 장판은 제가 직접 깔려고요"
    )  # 남는 일(실리콘)의 근거라 인용은 그대로
    b = propose_home(api, script, pid, {"diy": []})
    assert approve(api, b["action_id"], seen=b["target_ver"]).json()["status"] == "executed"
    got = memory()  # '없어요': 칩 일은 모두 빠지고 칩 밖의 일(장판)은 남아요
    assert (got["value"], got["evidence_quote"]) == ("장판 직접", "장판은 제가 직접 깔려고요")


def test_rejected_diy_card_drops_only_the_unsaved_work(api, script):
    _, pid = home(api)
    chips(api, pid, ["silicone"])
    memory_row(api, pid, "diy", "문틀 페인트 직접 · 욕실 실리콘", "페인트랑 실리콘은 제가 해요")
    a = propose_home(api, script, pid, {"diy": ["paint", "silicone"]})
    r = api.post(f"/assistant/actions/{a['action_id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected", r.text
    assert memory()["value"] == "욕실 실리콘"  # 저장된 실리콘은 남고, 저장 안 된 페인트만 빠져요
    # 줄이는 카드(실리콘 빼기)를 거둬도 저장된 일은 지우지 않아요
    c = propose_home(api, script, pid, {"diy": []})
    r = api.post(f"/assistant/actions/{c['action_id']}/reject")
    assert r.status_code == 200 and memory()["value"] == "욕실 실리콘"


def test_saved_chip_change_reissues_the_open_visit_request_card(api, script):
    kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    chips(api, pid, ["paint"])
    req = picks_request(api, pid)
    assert told_rows(req["summary"]["rows"]) == ["고객이 직접 해요 — 페인트(문틀 · 몰딩)"]
    a = propose_home(api, script, pid, {"diy": []})
    done = approve(api, a["action_id"], seen=a["target_ver"]).json()
    assert done["status"] == "executed"
    assert done["result"]["text"].endswith(actions.DIY_REISSUED)
    old = action_row(req["action_id"])
    assert (old["status"], result(req["action_id"])["reason"]) == ("expired", "replaced")
    new_id = result(req["action_id"])["replaced_by"]
    new = action_row(new_id)
    assert new["status"] == "proposed" and new["kind"] == "visit_request"
    pl = payload(new_id)  # 같은 업체 · 같은 조건 + 새 직접 할 일
    assert "diy" not in pl and pl["supersedes"] == req["action_id"]
    old_pl = payload(req["action_id"])
    assert {k: v for k, v in pl.items() if k != "supersedes"} == {
        k: v for k, v in old_pl.items() if k != "diy"
    }
    assert told_rows(summary(new_id)["rows"]) == []
    assert summary(new_id)["amounts"] == summary(req["action_id"])["amounts"]
    r = approve(api, new_id)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert query("select diy from visits")[0]["diy"] == []  # 업체에 페인트가 가지 않아요


def test_screen_chip_change_remakes_the_request_card_when_pressed(api):
    kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    chips(api, pid, ["outlet", "paint"])
    req = picks_request(api, pid)
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["light"]})  # 화면에서 칩을 바꿈
    assert r.status_code == 200, r.text
    r = approve(api, req["action_id"])
    assert code(r) == (409, actions.DIY_CHANGED)
    assert r.json()["error"]["message"] == actions.DIY_CHANGED_TEXT
    assert query("select id from visits") == []  # 옛 목록으로 보내지 않아요
    assert action_row(req["action_id"])["status"] == "failed"
    new_id = result(req["action_id"])["superseded_by"]
    assert payload(new_id)["diy"] == ["light"] and payload(new_id)["supersedes"] == req["action_id"]
    assert told_rows(summary(new_id)["rows"]) == ["고객이 직접 해요 — 조명 교체"]
    (shown,) = api.get("/assistant/actions", params={"status": "proposed"}).json()
    assert shown["action_id"] == new_id and shown["supersedes"] == req["action_id"]
    r = approve(api, new_id)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert query("select diy from visits")[0]["diy"] == ["light"]
    assert code(approve(api, req["action_id"])) == (409, "action_closed")  # 옛 카드는 닫혀 있어요


def test_again_request_takes_the_saved_chips(api):
    a = kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = kit.customer(api)
    assert kit.add(api, pid, a).status_code == 201 and kit.ask(api, pid, [a]).status_code == 201
    first = kit.visit_of(pid, a)
    chips(api, pid, ["paint"])
    query("update visits set diy = '{paint}' where id = $1", uuid.UUID(first))
    r = api.post(f"/projects/{pid}/visits/{first}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["light"]})  # 취소한 뒤 칩을 바꿈
    assert r.status_code == 200 and r.json()["told"] == []
    r = api.post(f"/projects/{pid}/visits/{first}/again")
    assert r.status_code == 201, r.text
    (row,) = query("select diy from visits where id = $1", uuid.UUID(r.json()["visit_id"]))
    assert row["diy"] == ["light"]  # 앞 사본(페인트)이 아니라 지금 칩


# ---- 2. 확정 업체에 늘 '따로 알리세요'(c2 21턴 · c3 · c6) ----


def test_started_work_keeps_the_copy_and_asks_to_tell_only_when_missing(api, script):
    customer, pid, va, _vb, _vc = setup(api)
    assert confirm(api, pid, va).status_code == 200
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["silicone"]})  # 공사 시작 전: 사본을 고쳐요
    assert r.json()["told"] == ["마루와벽"]
    query(
        "update deals set status = 'scheduled', start_date = $1, end_date = $2 where visit_id = $3",
        TODAY,
        TODAY + timedelta(days=2),
        uuid.UUID(va),
    )  # 공사가 오늘 시작했어요
    # 사본에 지금 직접 할 일이 이미 있으면 따로 알리라고 하지 않아요(결정 4)
    got = diy_plan(api, script, pid)
    assert "vendors" not in got
    # 공사가 시작된 뒤 바꾸면 사본은 그대로, 알림 없이 '따로 알려야 해요'
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["silicone", "light"]})
    out = r.json()
    assert out["told"] == [] and out["notice"] == f"{DIY_DEALT_NOTE}(마루와벽)"
    assert query("select diy from visits where id = $1", uuid.UUID(va))[0]["diy"] == ["silicone"]
    assert len(notes("maru@mitjip.test", "visit_diy_changed")) == 1
    use(api, customer)
    got = diy_plan(api, script, pid)
    assert got["vendors"] == {
        "deals": ["마루와벽"],
        "notes": [diy_tools.REACH_DEALT.format(note=DIY_DEALT_NOTE)],
    }


# ---- 5. 종 알림 조사 '오후를'(r2 c6) ----


def test_object_particle_follows_the_last_sound():
    assert flow._eul("11.23(월) 오후") == "11.23(월) 오후를"
    assert flow._eul("11.23(월) 오전") == "11.23(월) 오전을"
    assert flow._eul("A") == "A을"


@pytest.mark.parametrize(("half", "word"), [("pm", "오후를"), ("am", "오전을")])
def test_picked_bell_says_ohureul(api, half, word):
    f = kit.offered(api, instant=False)
    r = kit.choose(api, f["pid"], f["visit"], half=half)
    assert r.status_code == 200 and r.json()["status"] == "picked", r.text
    (n,) = notes(f["email"], "visit_picked")
    assert f" {word} 골랐어요. 수락해 주세요 · " in n["body"]

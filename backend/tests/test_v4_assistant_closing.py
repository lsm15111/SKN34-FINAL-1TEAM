"""v4 먼저 말 건 줄을 서버에서 닫기: 줄에 달린 승인 카드(같은 대상)를 실행하면 그 줄은 바로 닫힌다(expired acted) ·
승인 카드가 없는 줄(견적 도착 · 업체 추천)도 대상 상태가 바뀌면 정리(2분)가 닫는다(expired handled) · 닫힌 줄은 대화
기록 · 턴 끝 제안(suggest)에 오지 않는다 · 새 카드로 바뀐 제안은 바꾼 행동 id(replaced_by)를 내보낸다. 유료 호출 0회."""

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive
from app.assistant import service as assistant_service
from app.shared.clock import now_utc
from tests.conftest import query
from tests.test_deal import confirm
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import quiet
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_free import cards_of
from tests.test_v4_assistant_nudges import at, nudges, offered_nudge, run
from tests.test_v4_assistant_turns import ask, ok


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def line(nid) -> tuple[str, str | None]:
    (row,) = query("select status, reason from assistant_nudges where id = $1", nid)
    return row["status"], row["reason"]


def feed_ids(api, pid: str) -> set[str]:
    return {x["id"] for x in api.get("/assistant/feed", params={"project_id": pid}).json()["items"]}


def test_approving_the_line_action_closes_the_line_at_once(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    assert line(n["id"]) == ("sent", None)
    r = approve(api, str(n["action_id"]))
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert line(n["id"]) == ("expired", "acted")  # 정리(2분)를 기다리지 않는다
    assert f"n-{n['id']}" not in feed_ids(api, f["pid"])
    ev = ok(ask(api, f["pid"], "오늘 뭐 하면 돼요?"))
    assert all(x.get("nudge_id") != str(n["id"]) for x in ev[-1][1]["suggest"])


def test_new_card_replaces_the_line_action_and_its_approval_closes_the_line(api, monkeypatch):
    """비서에게 다시 물어 다른 반나절을 고르면 줄의 승인 카드는 새 카드로 바뀌고(replaced_by), 새 카드를 승인하면
    같은 대상의 줄도 닫힌다."""
    f, n = offered_nudge(api, monkeypatch)
    ev = ok(ask(api, f["pid"], "실측은 언제 할 수 있어요?"))
    (slots,) = cards_of(ev, "visit_slots")
    other = slots["data"]["candidates"][-1]["ref"]
    press = {"card_id": slots["card_id"], "choice": f"visit_slot:{other}"}
    ev = ok(ask(api, f["pid"], "이 시간이요", context=press))
    (new,) = [a for a in acts(ev) if a["status"] == "proposed"]
    (old,) = [a for a in acts(ev) if a["status"] == "expired"]
    assert old["action_id"] == str(n["action_id"]) and old["error_code"] == "replaced"
    assert old["replaced_by"] == new["action_id"]
    assert new["replaced_by"] is None
    assert line(n["id"]) == ("sent", None)  # 아직 아무것도 실행하지 않았다
    assert approve(api, new["action_id"]).json()["status"] == "executed"
    assert line(n["id"]) == ("expired", "acted")


def test_sweep_closes_lines_without_action_when_the_target_moved(api, monkeypatch):
    """견적 도착 줄(승인 카드 없음)은 화면에서 업체를 확정해 실측 상태가 바뀌면 정리가 닫는다."""
    _token, pid, va, _vb, _ = deal_setup(api)
    quiet(monkeypatch)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    shown = nudges(trigger="quote_sent")
    assert len(shown) == 2 and all(x["status"] == "sent" and x["action_id"] is None for x in shown)
    run(api, assistant_service.sweep, now_utc())
    assert all(line(x["id"]) == ("sent", None) for x in shown)  # 그대로면 닫지 않는다
    seen = {
        x["visit_id"]: x["seen_ver"]
        for x in api.get(f"/projects/{pid}/quotes?trade=dobae").json()["vendors"]
    }
    assert confirm(api, pid, va, seen[va]).status_code == 200  # v3 화면에서 확정
    tally = run(api, assistant_service.sweep, now_utc())
    assert tally["settled"] >= 2
    for x in shown:
        assert line(x["id"]) == ("expired", "handled")
    ids = feed_ids(api, pid)
    assert not any(f"n-{x['id']}" in ids for x in shown)

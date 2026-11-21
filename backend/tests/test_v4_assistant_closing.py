"""v4 먼저 말 건 줄을 서버에서 닫기: 줄에 달린 승인 카드(같은 대상)를 실행하면 그 줄은 바로 닫힌다(expired acted) ·
승인 카드가 없는 줄(견적 도착 · 업체 추천)도 대상 상태가 바뀌면 정리(2분)가 닫는다(expired handled) · 닫힌 줄은 턴 끝
제안(suggest)에 오지 않고, 대화 기록에는 '완료'(settled, 다음에 물을 말 없음 · 카드는 보낸 때 모습)로 남는다 ·
새 카드로 바뀐 제안은 바꾼 행동 id(replaced_by)를 내보낸다 · 보내고 닫을 때 그 사람에게 화면 신호(state)를 보낸다.
유료 호출 0회."""

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive
from app.assistant import service as assistant_service
from app.shared.clock import now_utc
from tests.conftest import query
from tests.test_deal import confirm
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import offered, quiet
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


def feed(api, pid: str, **params) -> dict:
    r = api.get("/assistant/feed", params={"project_id": pid, **params})
    assert r.status_code == 200, r.text
    return r.json()


def feed_line(api, pid: str, nid) -> dict:
    (item,) = [x for x in feed(api, pid)["items"] if x["id"] == f"n-{nid}"]
    return item


def record(monkeypatch) -> list[tuple[str, str, dict]]:
    """실시간 줄기 쓰기를 모은다(사람 id, 이벤트, 몸통). Redis에는 쓰지 않는다."""
    from app.realtime import service as realtime

    got: list[tuple[str, str, dict]] = []

    async def push(user_ids, event, data) -> int:
        got.extend((str(u), event, data) for u in user_ids if u is not None)
        return 1

    monkeypatch.setattr(realtime, "push", push)
    return got


def test_approving_the_line_action_closes_the_line_at_once(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    assert line(n["id"]) == ("sent", None)
    shown = feed_line(api, f["pid"], n["id"])
    assert shown["settled"] is False
    r = approve(api, str(n["action_id"]))
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert line(n["id"]) == ("expired", "acted")  # 정리(2분)를 기다리지 않는다
    # 대화 기록에는 '완료'로 남는다: 문장 · 보낸 때 카드 · 실행한 승인 카드 · 작업 카드, 다음에 물을 말은 없다
    item = feed_line(api, f["pid"], n["id"])
    assert item["settled"] is True and item["nudge_id"] == str(n["id"])
    assert [p["t"] for p in item["parts"]] == ["text", "card", "action", "task"]
    sent_card, card = shown["parts"][1]["card"], item["parts"][1]["card"]
    assert card["card_id"] == f"{sent_card['card_id']}@{n['id']}"  # 뒤 턴의 같은 카드와 합치지 않게
    assert (card["kind"], card["data"]) == ("visit_slots", sent_card["data"])
    assert item["parts"][2]["action"]["status"] == "executed"
    ev = ok(ask(api, f["pid"], "오늘 뭐 하면 돼요?"))
    assert all(x.get("nudge_id") != str(n["id"]) for x in ev[-1][1]["suggest"])
    today = api.get("/assistant/today", params={"project_id": f["pid"]}).json()
    assert today["nudge_id"] is None  # '오늘은 그만'은 열린 줄만 닫는다
    assert feed_line(api, f["pid"], n["id"])["settled"] is True  # 턴 뒤에도 그 자리에 남는다


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
    # 줄은 '완료'로 남고 승인 카드 자리에는 그 대상의 지금 행동(새 카드로 바뀐 옛 카드)이 그대로 보인다
    item = feed_line(api, f["pid"], n["id"])
    assert item["settled"] is True
    (a,) = [p["action"] for p in item["parts"] if p["t"] == "action"]
    assert a["action_id"] == str(n["action_id"])
    assert (a["status"], a["error_code"]) == ("expired", "replaced")
    assert all(p["t"] != "suggest" for p in item["parts"])


def test_sweep_closes_lines_without_action_when_the_target_moved(api, monkeypatch):
    """견적 도착 줄(승인 카드 없음)은 화면에서 업체를 확정해 실측 상태가 바뀌면 정리가 닫는다. 같은 공사의 견적서 줄은
    새 줄 하나로 합친다(앞 줄은 replaced, QA r1). 닫은 줄은 대화 기록에 '완료'로 남고, 열어 둔 화면이 다시 읽게 그
    사람에게 화면 신호를 보낸다."""
    _token, pid, va, _vb, _ = deal_setup(api)
    quiet(monkeypatch)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    shown = nudges(trigger="quote_sent")
    assert len(shown) == 2 and all(x["action_id"] is None for x in shown)
    (live,) = [x for x in shown if x["status"] == "sent"]
    (old,) = [x for x in shown if x["id"] != live["id"]]
    assert line(old["id"]) == ("expired", "replaced")  # 같은 공사의 견적서 줄은 새 줄 하나로
    run(api, assistant_service.sweep, now_utc())
    assert line(live["id"]) == ("sent", None)  # 그대로면 닫지 않는다
    seen = {
        x["visit_id"]: x["seen_ver"]
        for x in api.get(f"/projects/{pid}/quotes?trade=dobae").json()["vendors"]
    }
    assert confirm(api, pid, va, seen[va]).status_code == 200  # v3 화면에서 확정
    got = record(monkeypatch)
    tally = run(api, assistant_service.sweep, now_utc())
    assert tally["settled"] >= 1
    assert line(live["id"]) == ("expired", "handled")
    assert line(old["id"]) == ("expired", "replaced")  # 바뀐 줄은 그대로
    items = {x["id"]: x for x in feed(api, pid)["items"]}
    assert f"n-{old['id']}" not in items  # 바뀐 줄은 기록에서 빠진다
    item = items[f"n-{live['id']}"]
    assert item["settled"] is True and all(p["t"] != "suggest" for p in item["parts"])
    (card,) = [p["card"] for p in item["parts"] if p["t"] == "card"]
    assert card["kind"] == "quote_compare" and card["card_id"].endswith(f"@{live['id']}")
    owner = str(live["user_id"])
    signals = {(d["id"], d["project_id"]) for u, e, d in got if u == owner and e == "state"}
    assert (str(live["ref_id"]), pid) in signals


def test_sending_a_nudge_signals_the_open_screen(api, monkeypatch):
    """먼저 말 걸기를 보내면 commit 뒤 그 사람 · 그 공사로 화면 신호(state)를 보낸다. 열어 둔 대화는 이 신호로
    기록을 다시 읽어 문장 · 카드 · 승인 카드를 한꺼번에 붙인다(rev는 그대로라 신호가 없으면 다시 읽지 않았다)."""
    got = record(monkeypatch)
    f = offered(api)
    run(api, proactive.scan_events, at(14))
    got.clear()
    assert run(api, proactive.evaluate_due, at(14)) == {"sent": 1, "expired": 1}
    (n,) = nudges(trigger="visit_offered")
    owner = str(n["user_id"])
    state = [d for u, e, d in got if u == owner and e == "state"]
    assert state == [{"kind": "visit", "project_id": f["pid"], "id": str(n["ref_id"])}]
    thread = api.get("/assistant/threads/latest", params={"project_id": f["pid"]}).json()
    item = feed_line(api, f["pid"], n["id"])
    assert [p["t"] for p in item["parts"]] == ["text", "card", "action", "task", "suggest"]
    assert thread["rev"] == 1  # 대화 번호표는 그대로: 화면은 신호로 다시 읽는다


def test_replaced_and_dismissed_lines_leave_the_feed(api, monkeypatch):
    """'완료'로 남는 것은 할 일이 끝난 줄(acted · handled)만이다. 새 줄에 밀린 줄(replaced) · 고객이 닫은 줄(dismissed)은
    대화 기록에서 빠진다."""
    f, n = offered_nudge(api, monkeypatch)
    query(
        "update assistant_nudges set sent_at = sent_at - interval '49 hours' where id = $1", n["id"]
    )
    assert run(api, proactive.scan_time, at(14)) == 1
    run(api, proactive.evaluate_due, at(9, 1))
    (late,) = nudges(channel="notify")
    assert line(n["id"]) == ("expired", "replaced") and late["status"] == "sent"
    ids = {x["id"] for x in feed(api, f["pid"])["items"]}
    assert f"n-{late['id']}" in ids and f"n-{n['id']}" not in ids
    assert api.post(f"/assistant/nudges/{late['id']}/dismiss").status_code == 200
    assert feed(api, f["pid"])["items"] == []


def test_lines_go_to_the_page_of_their_time(api, monkeypatch):
    """먼저 말 건 줄은 보낸 때가 속한 쪽에만 한 번 온다(앞 쪽을 읽어도 '완료' 줄이 빠지지 않는다)."""
    f, n = offered_nudge(api, monkeypatch)
    for text in ("오늘 뭐 하면 돼요?", "표준견적서 보여 줘", "업체 추천해 줘"):
        ok(ask(api, f["pid"], text))
    turns = query(
        "select m.turn, min(m.created_at) as at from chat_messages m join chats c on c.id = m.chat_id"
        " where c.project_id = $1 and c.kind = 'assistant' group by m.turn order by m.turn",
        f["pid"],
    )
    assert [t["turn"] for t in turns] == [1, 2, 3]
    # 줄을 1턴과 2턴 사이에 보낸 것으로 옮기고 할 일을 끝낸다(완료 줄)
    mid = turns[0]["at"] + (turns[1]["at"] - turns[0]["at"]) / 2
    query("update assistant_nudges set sent_at = $2 where id = $1", n["id"], mid)
    assert approve(api, str(n["action_id"])).json()["status"] == "executed"
    pages, before = [], None
    while True:
        page = feed(api, f["pid"], limit=2, **({"before": before} if before else {}))
        pages.append(page)
        before = page["before"]
        if not before:
            break
    assert len(pages) == 3
    where = [[x["id"] for x in p["items"] if x["id"] == f"n-{n['id']}"] for p in pages]
    assert where == [[], [], [f"n-{n['id']}"]]  # 1턴 쪽(가장 앞 쪽)에만
    first = [x["id"] for x in pages[2]["items"]]
    assert first.index(f"n-{n['id']}") == len(first) - 1  # 1턴 말 뒤에
    item = next(x for x in pages[2]["items"] if x["id"] == f"n-{n['id']}")
    assert item["settled"] is True
    assert all(p["t"] != "task" for p in item["parts"])  # 앞 쪽에는 작업 카드를 붙이지 않는다

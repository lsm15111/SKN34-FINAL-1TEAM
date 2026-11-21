"""v4 비서 카드 단추와 이름표(RefTable): 긴 card_id(slots- · brief- · dates- + 실측 id) · 먼저 말 걸기 카드 단추가
대화 이름표 표를 같이 쓰는지 · 모르는(지난) 이름표 단추는 카드를 새로 불러오는지(무료 · LLM 모드) · 표가 지워져도
이름표 번호를 다시 쓰지 않는지 · 두 곳이 같은 번호를 다른 대상에 쓰면 버리는지 · 업체 브리핑 카드의 기간 이름표(w#).
유료 호출 0회(LLM 꺼짐 = 무료 모드, LLM 모드는 Claude 대본)."""

import json
import uuid

import pytest
import redis
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive
from app.assistant.runtime import RefTable
from tests.conftest import REDIS_URL, query
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import offered, quiet, requested
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_free import cards_of, said, vendor_turn
from tests.test_v4_assistant_nudges import at, nudges, run
from tests.test_v4_assistant_turns import ask, ok
from tests.test_visit_inbox import login

RELOADED = "카드를 새로 불러왔어요. 다시 골라 주세요."


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


def table(chat_id: str) -> dict:
    raw = redis.Redis.from_url(REDIS_URL).get(f"assistant:refs:{chat_id}")
    return json.loads(raw) if raw else {}


def forget_items(chat_id: str) -> None:
    """이름표 표(값)만 지운다(만료 · Redis 정리 흉내). 번호 기록은 남는다."""
    redis.Redis.from_url(REDIS_URL).delete(f"assistant:refs:{chat_id}")


def proposed(ev) -> list[dict]:
    return [a for a in acts(ev) if a["status"] == "proposed"]


def visit_of_action(a: dict) -> str:
    row = query("select payload from assistant_actions where id = $1", uuid.UUID(a["action_id"]))
    return json.loads(row[0]["payload"])["visit_id"]


def quote_nudges(api, monkeypatch) -> None:
    """견적서가 온 알림(아웃박스) → 먼저 말 걸기를 보낸다(대화 기록 줄 + 견적 비교 카드)."""
    quiet(monkeypatch)
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))


def col_ref(card: dict, visit_id: str) -> str:
    return next(c["ref"] for c in card["data"]["cols"] if c["visit_id"] == visit_id)


# ---- card_id 길이 ----


def test_long_card_ids_from_cards_are_accepted(api):
    """slots- · brief- · dates- · check- + 실측 id는 42자예요. 화면처럼 보내도 422가 아니에요."""
    f = offered(api)
    ev = ok(ask(api, f["pid"], "실측은 언제 할 수 있어요?"))
    (slots,) = cards_of(ev, "visit_slots")
    assert len(slots["card_id"]) == 42
    ref = slots["data"]["candidates"][0]["ref"]
    r = ask(
        api,
        f["pid"],
        "이 시간이요",
        context={"card_id": slots["card_id"], "choice": f"visit_slot:{ref}"},
    )
    (a,) = proposed(ok(r))
    assert a["kind"] == "visit_slot"
    login(api, f["email"])
    r = vendor_turn(api, f["visit"], "이 요청 어때요?", context={"card_id": f"brief-{f['visit']}"})
    assert r.status_code == 200, r.text
    too_long = {"card_id": "x" * 65}
    assert vendor_turn(api, f["visit"], "이 요청 어때요?", context=too_long).status_code == 422


# ---- 먼저 말 걸기 카드 단추 · 지난 이름표 ----


def test_nudge_card_button_uses_the_chat_refs(api, monkeypatch):
    """먼저 말 걸기 견적 비교 카드의 [마루와벽 할래요]가 그 업체 확정 승인 카드를 만든다.
    대화 표에 같은 번호(m1)가 다른 업체로 있어도 카드가 가리킨 업체로 간다(이름표 표를 같이 쓴다)."""
    _token, pid, va, vb, _ = deal_setup(api)
    first = ok(ask(api, pid, "오늘 뭐 하면 돼요?"))
    chat = first[0][1]["chat_id"]
    # 대화 표에 m1 = 결도배가 이미 있다(다른 카드에서 받은 이름표)
    redis.Redis.from_url(REDIS_URL).set(
        f"assistant:refs:{chat}",
        json.dumps({"m1": {"kind": "visit", "id": vb, "vendor_name": "결도배"}}),
    )
    quote_nudges(api, monkeypatch)
    (n,) = nudges(trigger="quote_sent", ref_id=uuid.UUID(va))
    card = json.loads(n["card"])
    ref = col_ref(card, va)
    assert table(chat)[ref]["id"] == va  # 먼저 말 걸기가 만든 이름표가 대화 표에 있다
    ev = ok(
        ask(
            api,
            pid,
            "마루와벽으로 확정할래요",
            context={"card_id": card["card_id"], "choice": f"vendor_confirm:{ref}"},
        )
    )
    (a,) = proposed(ev)
    assert a["kind"] == "vendor_confirm" and visit_of_action(a) == va
    assert "아직 도배 업체만" not in said(ev)


def test_unknown_ref_reloads_the_card_in_free_and_llm_mode(api, monkeypatch):
    """이름표 표가 지워진 뒤(30분 · 정리) 누른 단추는 버리지 않고 그 카드를 새로 불러와 다시 고르게 한다."""
    _token, pid, va, _vb, _ = deal_setup(api)
    ev = ok(ask(api, pid, "견적서 비교해 줘"))
    chat = ev[0][1]["chat_id"]
    (old,) = cards_of(ev, "quote_compare")
    old_ref = col_ref(old, va)
    forget_items(chat)
    press = {"card_id": old["card_id"], "choice": f"vendor_confirm:{old_ref}"}
    ev = ok(ask(api, pid, "마루와벽으로 확정할래요", context=press))
    assert proposed(ev) == [] and said(ev) == RELOADED
    (new,) = cards_of(ev, "quote_compare")
    new_ref = col_ref(new, va)
    ev = ok(
        ask(
            api,
            pid,
            "마루와벽으로 확정할래요",
            context={**press, "choice": f"vendor_confirm:{new_ref}"},
        )
    )
    (a,) = proposed(ev)
    assert visit_of_action(a) == va
    # LLM 모드도 같다(LLM을 부르지 않고 카드를 새로 불러와요)
    forget_items(chat)
    log = llm.set_claude_script([{"text": "확정 카드를 만들었어요."}])
    ev = ok(
        ask(
            api,
            pid,
            "마루와벽으로 확정할래요",
            context={**press, "choice": f"vendor_confirm:{new_ref}"},
        )
    )
    assert log == [] and cards_of(ev, "quote_compare") and said(ev) == RELOADED


def test_ref_numbers_are_not_reused_after_the_table_is_gone(api):
    """표가 지워져도 번호를 다시 쓰지 않는다: 지난 카드의 m1이 새 대상을 가리키지 않게."""
    _token, pid, _va, _vb, _ = deal_setup(api)
    ev = ok(ask(api, pid, "견적서 비교해 줘"))
    chat = ev[0][1]["chat_id"]
    before = {c["ref"] for c in cards_of(ev, "quote_compare")[0]["data"]["cols"]}
    forget_items(chat)
    ev = ok(ask(api, pid, "견적서 비교해 줘"))
    after = {c["ref"] for c in cards_of(ev, "quote_compare")[0]["data"]["cols"]}
    assert before and after and not (before & after)


def test_same_number_for_two_targets_is_dropped(api):
    """두 곳(턴 · 먼저 말 걸기)이 같은 번호를 다른 대상에 쓰면 그 번호를 버린다(모르는 이름표 → 카드를 새로 불러옴).
    그 사이 표를 읽은 세 번째 곳이 저장해도 다시 살리지 않는다."""
    chat = uuid.uuid4()
    x, y = str(uuid.uuid4()), str(uuid.uuid4())

    async def go():
        a = await RefTable.load(chat)
        b = await RefTable.load(chat)
        ra, rb = a.put("visit", {"id": x}), b.put("visit", {"id": y})
        await a.save()
        c = await RefTable.load(chat)  # ra = x를 읽었다
        await b.save()
        await c.save()
        keep = await RefTable.load(chat)
        nxt = keep.put("visit", {"id": str(uuid.uuid4())})
        return ra, rb, keep, nxt

    ra, rb, keep, nxt = run(api, go)
    assert ra == rb and not keep.known(ra) and nxt != ra


# ---- 업체 브리핑 카드 기간 이름표 ----


def test_vendor_brief_card_has_window_refs_for_buttons(api, monkeypatch):
    """요청함이면 브리핑 카드에 기간 후보 이름표(w#)가 있어 무료 모드에서도 window_answer 단추를 누를 수 있다.
    REST 브리핑 · 먼저 말 걸기 카드도 업체 대화 표를 같이 쓴다."""
    f = requested(api)
    quiet(monkeypatch)
    login(api, f["email"])
    brief = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()
    wins = brief["windows"]
    assert wins and all(w["ref"].startswith("w") for w in wins)
    assert (wins[0]["start"], wins[0]["end"]) == (
        brief["suggest"]["start"],
        brief["suggest"]["end"],
    )
    w = wins[-1]
    ev = ok(
        vendor_turn(
            api, f["visit"], "이 기간으로 답할래요",
            context={"card_id": f"brief-{f['visit']}", "choice": f"window_answer:{w['ref']}"},
        )
    )  # fmt: skip
    (a,) = proposed(ev)
    assert a["kind"] == "window_answer"
    payload = query(
        "select payload from assistant_actions where id = $1", uuid.UUID(a["action_id"])
    )
    assert json.loads(payload[0]["payload"])["start"] == w["start"]
    # 무료 모드 브리핑 카드(새 제안 없이)도 기간 이름표를 준다
    ev = ok(vendor_turn(api, f["visit"], "이 요청 어때요?"))
    (card,) = cards_of(ev, "vendor_brief")
    assert [x["ref"] for x in card["data"]["windows"]]
    # 먼저 말 걸기 브리핑 카드의 기간 단추도 된다
    run(api, proactive.scan_events, at(14))
    run(api, proactive.evaluate_due, at(14))
    (n,) = nudges(trigger="visit_requested")
    ncard = json.loads(n["card"])
    w = ncard["data"]["windows"][-1]
    ev = ok(
        vendor_turn(
            api, f["visit"], "이 기간으로 답할래요",
            context={"card_id": ncard["card_id"], "choice": f"window_answer:{w['ref']}"},
        )
    )  # fmt: skip
    (a,) = proposed(ev)
    payload = query(
        "select payload from assistant_actions where id = $1", uuid.UUID(a["action_id"])
    )
    assert json.loads(payload[0]["payload"])["start"] == w["start"]
    assert approve(api, a["action_id"], prefix="/vendor/assistant").json()["status"] == "executed"

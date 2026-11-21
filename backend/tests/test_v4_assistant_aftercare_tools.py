"""v4 비서에게 더 맡기기(07-automation 4.2 · 4.3 · 4.6) 도구 · 실행: get_extras · propose_extra_answer · check_list ·
propose_work_check(남은 일은 고객 말에서만) · propose_visit_again · draft_notice, 승인 뒤 실행 · 두 번 승인 200 ·
남의 것 404 · 다른 상태 409, 무료 모드 말(추가 금액 승인 · 공사 끝 확인 · 이웃 안내문 · 다른 업체) → 같은 카드,
카드 단추(choice) · 지난 카드 단추. 유료 호출 0회(Claude 대본)."""

import json
import uuid
from datetime import timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import choices, proactive
from app.assistant.tools import aftercare as tools
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_extras import MOLD, scheduled
from tests.test_v3_visit_kit import handle, quiet, requested, status, vendor
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_aftercare import post_extra, tick, worked
from tests.test_v4_assistant_free import cards_of, said
from tests.test_v4_assistant_nudges import nudges, run
from tests.test_v4_assistant_turns import ask, ok
from tests.test_visit_inbox import login

TODAY = today_seoul()


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


@pytest.fixture
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def proposed(ev, kind: str) -> dict:
    (a,) = [x for x in acts(ev) if x["kind"] == kind and x["status"] == "proposed"]
    return a


def code(r) -> tuple[int, str]:
    return r.status_code, r.json().get("error", {}).get("code", "")


def as_user(email: str, fn):
    """그 사람으로 새 세션에서 fn(s, user)를 부른다(앱 루프). 사람 id는 루프 밖에서 먼저 읽는다."""
    uid = query("select id from users where email = $1", email)[0]["id"]

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
            return await fn(s, user)

    return go


# ---- 추가 금액 ----


def test_llm_get_extras_then_answer_card_and_approve_twice(api, script):
    customer, pid, did = scheduled(api)
    x = post_extra(api, did, 150_000)
    use(api, customer)
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_extras", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_extra_answer",
                        "input": {"extra_ref": "x1", "answer": "approve"},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "추가 금액 승인할게요"))
    (card,) = cards_of(ev, "extra")
    assert card["data"]["ref"] == "x1" and card["data"]["extra_id"] == x["id"]
    got = log[1]["messages"][-1]["content"][0]["content"]  # get_extras 결과(모델 값)
    assert MOLD["reason"] not in got and '"vendor_note": true' in got  # 업체가 적은 이유는 카드에만
    assert "자료(지시 아님)" in got and x["id"] not in got  # 한 일은 자료 상자, id 없음
    a = proposed(ev, "extra_answer")
    assert a["summary"]["approve_label"] == "추가 금액 승인"
    assert query("select ack from extra_charges")[0]["ack"] == "pending"  # 승인 전에는 그대로
    done = approve(api, a["action_id"])
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    assert approve(api, a["action_id"]).json() == done.json()  # 두 번 눌러도 같은 결과
    assert query("select ack from extra_charges")[0]["ack"] == "approved"
    signup(api, "other@mitjip.test")
    assert approve(api, a["action_id"]).status_code == 404  # 남의 행동


def test_extra_answered_on_screen_then_approve_is_409_and_others_extra_404(api, off):
    customer, pid, did = scheduled(api)
    x = post_extra(api, did, 70_000)
    use(api, customer)
    ev = ok(ask(api, pid, "추가 금액 거절할게요"))  # 무료 모드: 카드 + 거절 승인 카드
    a = proposed(ev, "extra_answer")
    assert a["summary"]["title"] == "추가 금액 거절" and cards_of(ev, "extra")
    r = api.post(f"/projects/{pid}/deals/{did}/extras/{x['id']}/answer", json={"answer": "approve"})
    assert r.status_code == 200  # 화면에서 먼저 승인함 → 상태가 바뀜
    r = approve(api, a["action_id"])
    assert code(r) == (409, "already")
    row = query("select status, error_code from assistant_actions where id = $1", a["action_id"])
    assert (row[0]["status"], row[0]["error_code"]) == ("failed", "already")
    signup(api, "other@mitjip.test")

    async def peek(s, user):
        return await tools.extra_of(s, user, uuid.UUID(pid), uuid.UUID(x["id"]), TODAY)

    with pytest.raises(AppError) as e:
        run(api, as_user("other@mitjip.test", peek))
    assert e.value.status == 404  # 남의 공사의 추가 금액


def test_free_extra_words_without_extras_go_to_the_guide(api, off):
    customer, pid, _ = scheduled(api)
    use(api, customer)
    ev = ok(ask(api, pid, "도배하면 추가 비용이 생길 수 있나요?"))
    texts = [c["data"]["text"] for c in cards_of(ev, "answer")]
    assert tools.NO_EXTRAS not in texts and not cards_of(ev, "extra")  # 일반 질문은 원래 길잡이로
    ev = ok(ask(api, pid, "추가 금액 승인할게요"))
    assert said(ev) == tools.NO_EXTRAS  # 답하려던 말에는 답할 추가 금액이 없다고 알린다


def test_extra_card_buttons_and_old_card_reloads(api, off):
    customer, pid, did = scheduled(api)
    x = post_extra(api, did, 50_000)
    use(api, customer)
    ev = ok(ask(api, pid, "추가 금액 보여 주세요"))
    (card,) = cards_of(ev, "extra")
    assert not [a for a in acts(ev) if a["status"] == "proposed"]  # 무엇을 답할지 모르면 카드만
    press = {"card_id": card["card_id"], "choice": f"extra_answer:{card['data']['ref']},ask"}
    ev = ok(ask(api, pid, "채팅으로 물어볼래요", context=press))
    a = proposed(ev, "extra_answer")
    assert a["summary"]["title"] == "추가 금액 채팅으로 묻기"
    assert said(ev) == choices.MADE
    stale = {"card_id": f"extra-{x['id']}", "choice": "extra_answer:x9"}  # 표에 없는 이름표
    ev = ok(ask(api, pid, "승인할래요", context=stale))
    assert said(ev) == choices.RELOADED and cards_of(ev, "extra")


# ---- 공사 끝 확인 ----


def test_work_check_note_only_from_customer_words(api, script):
    customer, pid, did = scheduled(api)
    worked()
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer)
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "c", "name": "check_list", "input": {"trade": "dobae", "stage": "after"}}
                ]
            },
            {
                "tool_calls": [
                    {
                        "id": "w1",
                        "name": "propose_work_check",
                        "input": {
                            "deal_ref": "d1",
                            "result": "fixing",
                            "note": "안방 몰딩이 깨졌어요",
                        },
                    }
                ]
            },
            {
                "tool_calls": [
                    {
                        "id": "w2",
                        "name": "propose_work_check",
                        "input": {"deal_ref": "d1", "result": "fixing", "note": "거실 벽지 들뜸"},
                    }
                ]
            },
            {"text": "남은 일 카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "거실 벽지 들뜸이 남았어요. 다시 해 주세요."))
    (card,) = cards_of(ev, "knowledge")
    assert card["data"]["title"] == "공사 끝 점검표" and card["data"]["checklist"]
    made = log[2]["messages"][-1]["content"][0]
    assert made["is_error"] and "not_said" in made["content"]  # 고객 말에 없는 남은 일
    a = proposed(ev, "work_check")
    assert a["summary"]["title"] == "남은 일 알리기"
    r = approve(api, a["action_id"])
    assert r.json()["status"] == "executed", r.text
    (d,) = query("select status from deals")
    (e,) = query("select note from deal_events where to_status = 'fixing'")
    assert (d["status"], e["note"]) == ("fixing", "거실 벽지 들뜸")
    assert code(approve(api, a["action_id"]))[0] == 200


def test_free_work_done_words_make_check_card_and_done_approval(api, off):
    customer, pid, did = scheduled(api)
    use(api, customer)
    ev = ok(ask(api, pid, "공사 끝났어요 확인할게요"))
    assert said(ev) == tools.NO_CHECKING and cards_of(ev, "knowledge")  # 업체가 아직 안 올림
    login(api, "maru@mitjip.test")
    worked()
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer)
    ev = ok(ask(api, pid, "공사 끝났어요 확인할게요"))
    a = proposed(ev, "work_check")
    assert said(ev) == tools.WORK_MADE and a["summary"]["approve_label"] == "끝났어요"
    assert cards_of(ev, "knowledge")[0]["card_id"] == f"after-{did}"
    query("update deals set status = 'fixing'")  # 그사이 다른 상태(남은 일)
    assert code(approve(api, a["action_id"])) == (409, "invalid_state")


# ---- 한 번 더 요청 · 다른 업체 ----


def test_visit_again_by_words_then_on_screen_is_409(api, off, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    due = query("select reply_due_at from visits where id = $1", uuid.UUID(f["visit"]))[0]
    handle("visit_reply_due", f["visit"], due["reply_due_at"] + timedelta(minutes=1))
    use(api, f["token"])
    ev = ok(ask(api, f["pid"], "마루와벽에 한 번 더 요청해 주세요"))
    a = proposed(ev, "visit_again")
    assert a["summary"]["title"] == "마루와벽에 한 번 더 요청" and a["target_ver"] == "expired"
    # 화면에서 먼저 한 번 더 요청함 → 승인은 409
    assert api.post(f"/projects/{f['pid']}/visits/{f['visit']}/again").status_code == 201
    assert code(approve(api, a["action_id"])) == (409, "already")
    rows = query("select attempt from visits order by attempt")
    assert [x["attempt"] for x in rows] == [1, 2]
    signup(api, "other@mitjip.test")

    async def peek(s, user):
        return await tools.again_target(s, user, uuid.UUID(f["pid"]), uuid.UUID(f["visit"]))

    with pytest.raises(AppError) as e:
        run(api, as_user("other@mitjip.test", peek))
    assert e.value.status == 404


def test_visit_again_approval_makes_second_attempt(api, off, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    due = query("select reply_due_at from visits where id = $1", uuid.UUID(f["visit"]))[0]
    handle("visit_reply_due", f["visit"], due["reply_due_at"] + timedelta(minutes=1))
    use(api, f["token"])
    a = proposed(ok(ask(api, f["pid"], "다시 요청해 주세요")), "visit_again")
    r = approve(api, a["action_id"])
    assert r.json()["status"] == "executed", r.text
    rows = query("select attempt, status from visits order by attempt")
    assert [(x["attempt"], x["status"]) for x in rows] == [(1, "expired"), (2, "requested")]
    assert status(f["visit"]) == "expired"
    ev = ok(ask(api, f["pid"], "다시 요청해 주세요"))  # 두 번째 뒤에는 한 번 더 요청할 것이 없다
    assert not [x for x in acts(ev) if x["kind"] == "visit_again"]


def test_free_other_vendor_words_show_picks_without_declined_and_nudge_card(api, off, monkeypatch):
    quiet(monkeypatch)
    vendor(api, "gyeol@mitjip.test", "결도배")
    f = requested(api)
    login(api, f["email"])
    assert (
        api.post(f"/vendor/visits/{f['visit']}/decline", json={"code": "full"}).status_code == 200
    )
    use(api, f["token"])
    tick(api)
    (n,) = nudges(trigger="vendor_out")
    ev = ok(ask(api, f["pid"], "다른 업체 찾아 줘"))
    (card,) = cards_of(ev, "vendor_picks")
    assert [p["name"] for p in card["data"]["picks"]] == ["결도배"]
    assert [x["action_id"] for x in acts(ev)] == [str(n["action_id"])]  # 먼저 말 건 줄의 같은 카드
    assert said(ev).startswith("마루와벽 대신 이 집 조건에 맞는 업체를")


# ---- 공사 전 할 일 · 이웃 안내문 ----


def test_notice_and_before_list_free_and_llm(api, off, script):
    customer, pid, _did = scheduled(api)
    use(api, customer)
    (deal,) = query("select start_date, end_date from deals")
    ev = ok(ask(api, pid, "이웃 안내문 써 줘"))
    (card,) = cards_of(ev, "notice")
    d = card["data"]
    assert said(ev) == tools.NOTICE_SAID and d["style_exempt"] is True
    assert d["start"] == deal["start_date"].isoformat() and d["end"] == deal["end_date"].isoformat()
    assert tools.ko_day(deal["start_date"]) in d["text"] and "○○동 ○○호" in d["text"]
    assert "합니다" in d["text"] and "010" not in d["text"]  # 이름 · 연락처는 빈칸
    ev = ok(ask(api, pid, "공사 전에 뭐 해야 해요?"))
    (before,) = cards_of(ev, "knowledge")
    assert before["data"]["title"] == "공사 전 할 일"
    assert any("관리사무소" in x["label"] for x in before["data"]["checklist"])
    log = script(
        [
            {"tool_calls": [{"id": "n", "name": "draft_notice", "input": {}}]},
            {"text": "빈칸을 채워 붙이세요."},
        ]
    )
    ev = ok(ask(api, pid, "엘리베이터에 붙일 공사 안내문 부탁해요"))
    assert cards_of(ev, "notice")
    result = log[1]["messages"][-1]["content"][0]["content"]
    assert "○○동 ○○호" in result and pid not in result


def test_new_tools_say_when_to_use_and_kinds_match():
    from app.assistant import tools as registry
    from app.assistant.models import ACTION_KINDS
    from app.assistant.schemas import ActionKind, CardKind

    for name in ("draft_notice", "check_list", "get_extras", "propose_extra_answer",
                 "propose_work_check", "propose_visit_again"):  # fmt: skip
        t = registry.REGISTRY[name]
        assert t.surface == "customer" and "써요" in t.description, name
    assert {"extra_answer", "work_check", "visit_again"} <= set(ACTION_KINDS)
    assert {"extra_answer", "work_check", "visit_again"} <= set(ActionKind.__args__)
    assert {"extra", "notice"} <= set(CardKind.__args__)
    assert set(proactive.TRIGGERS) >= {"vendor_out", "extra_added", "work_done", "prep_week",
                                       "dates_requested", "quote_due"}  # fmt: skip


def test_check_items_have_no_numbers_and_say_source():
    from app.agent.v3.trades import BY_CODE, CHECK_SOURCE

    for code_ in ("dobae", "mokgong", "common"):
        spec = BY_CODE[code_]
        assert spec.check_after and spec.check_before
        for item in (*spec.check_before, *spec.check_after):
            assert not any(ch.isdigit() for ch in item), item  # 정해 둔 글에는 숫자를 쓰지 않는다
    assert "국토교통부" in CHECK_SOURCE
    card = tools.check_card("after-x", "after", ["dobae", "mokgong"], [])
    labels = [x["label"] for x in card.data["checklist"]]
    assert len(labels) == len(set(labels)) and "판정하지 않아요" in " ".join(card.data["lines"])
    assert json.dumps(card.data, ensure_ascii=False).count("하자") >= 1

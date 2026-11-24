"""v4 비서에게 더 맡기기(07-automation 4.1 · 4.6) 먼저 말 걸기 트리거: 업체가 빠짐 · 추가 금액 · 공사 끝 · 공사 1주 전 ·
날짜 바꾸기 요청(업체) · 견적서 기한(업체) · 업체 확정 무응답 알림. 트리거마다 상태가 그대로일 때만 보냄 · 상태가 바뀌면
닫힘(거짓 경보 0) · 밤 · 하루 상한 · 같은 대상 보이는 줄 하나 · 승인 뒤 줄 닫힘. 유료 호출 0회(Claude 대본)."""

import json
import uuid
from datetime import datetime, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive
from app.assistant import service as assistant_service
from app.calc.common import from_entered
from app.db import SessionLocal
from app.jobs.models import Job
from app.schedule.jobs import HANDLERS as DEAL_HANDLERS
from app.shared.clock import now_utc, today_seoul
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose, ready
from tests.test_extras import MOLD, scheduled
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import booked, handle, quiet, requested, status, vendor
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_nudges import add_nudge, at, nudges, run
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


def line(nid) -> tuple[str, str | None]:
    (row,) = query("select status, reason from assistant_nudges where id = $1", nid)
    return row["status"], row["reason"]


def action(aid) -> dict:
    (row,) = query("select * from assistant_actions where id = $1", aid)
    out = dict(row)
    for k in ("payload", "summary", "result"):
        if isinstance(out.get(k), str):
            out[k] = json.loads(out[k])
    return out


def card_of(n: dict):
    return json.loads(n["card"]) if isinstance(n["card"], str) else n["card"]


def tick(api, hour: int = 14, day_shift: int = 0):
    """worker 한 차례(고정 시계): 아웃박스 → 평가."""
    now = at(hour, day_shift)
    run(api, proactive.scan_events, now)
    return run(api, proactive.evaluate_due, now)


def deal_job(kind: str, ref_id, now: datetime):
    """확정 기한 일 처리 함수를 앱 루프에서 한 번 돌리고 commit."""

    async def go():
        async with SessionLocal() as s:
            job = Job(id=uuid.uuid4(), kind=kind, ref_id=uuid.UUID(str(ref_id)), run_at=now)
            out = await DEAL_HANDLERS[kind](s, job, now)
            await s.commit()
            return out

    return go


def post_extra(api, did: str, amount: int = 150_000):
    r = api.post(
        f"/vendor/jobs/{did}/extras",
        json={**MOLD, "entered_amount": amount, "vat_mode": "excluded"},
    )
    assert r.status_code == 201, r.text
    return r.json()["extras"]["items"][-1]


# ---- 업체가 빠짐(vendor_out) ----


def test_vendor_out_declined_recommends_another_and_request_closes_line(api, monkeypatch):
    quiet(monkeypatch)
    gyeol = vendor(api, "gyeol@mitjip.test", "결도배")
    f = requested(api)
    login(api, f["email"])
    r = api.post(f"/vendor/visits/{f['visit']}/decline", json={"code": "full"})
    assert r.status_code == 200, r.text
    use(api, f["token"])
    tick(api)
    (n,) = nudges(trigger="vendor_out")
    assert (n["status"], n["channel"], str(n["ref_id"])) == ("sent", "feed", f["visit"])
    assert n["body"] == "마루와벽이 이번 요청을 받지 못해요. 맞는 업체를 더 골라 뒀어요."
    card = card_of(n)
    assert card["kind"] == "vendor_picks" and card["card_id"] == "picks-dobae-out"
    assert [p["name"] for p in card["data"]["picks"]] == ["결도배"]  # 못 받은 업체는 뺀다
    a = action(n["action_id"])
    assert (a["kind"], a["origin"], a["status"]) == ("visit_request", "nudge", "proposed")
    assert a["payload"]["vendor_ids"] == [gyeol]
    (v,) = query("select wish_end from visits where id = $1", uuid.UUID(f["visit"]))
    assert a["payload"]["wish_end"] == v["wish_end"].isoformat()  # 원래 요청의 희망 기간
    feed = api.get("/assistant/feed", params={"project_id": f["pid"]}).json()
    (item,) = [x for x in feed["items"] if x.get("nudge_id") == str(n["id"])]
    assert [p["t"] for p in item["parts"]] == ["text", "card", "action", "suggest"]
    assert item["parts"][-1]["suggest"]["say"] == "다른 업체 찾아 줘"
    # 승인 → 결도배에 실측 요청, 줄은 바로 닫힘
    r = approve(api, str(n["action_id"]))
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert line(n["id"]) == ("expired", "acted")
    rows = query("select status from visits where vendor_id = $1", uuid.UUID(gyeol))
    assert [x["status"] for x in rows] == ["requested"]
    # 다른 업체에 요청한 뒤 2일 무응답 알림 줄은 보내지 않는다(상태가 바뀜 → 거짓 경보 0)
    late = add_nudge(
        n["user_id"], trigger="vendor_out", ref=n["ref_id"], project_id=n["project_id"],
        dedup_key=n["dedup_key"] + ":notify",
    )  # fmt: skip
    run(api, proactive.evaluate_due, at(15))
    assert line(late) == ("expired", "gone")
    assert not query("select 1 from notifications where kind = 'assistant_nudge'")


def test_vendor_out_needs_another_vendor_and_follow_notify_after_two_days(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)  # 이 구에 다른 업체가 없다
    due = query("select reply_due_at from visits where id = $1", uuid.UUID(f["visit"]))[0]
    handle("visit_reply_due", f["visit"], due["reply_due_at"] + timedelta(minutes=1))
    assert status(f["visit"]) == "expired"
    tick(api)
    (n,) = nudges(trigger="vendor_out")
    assert line(n["id"]) == ("expired", "gone")  # 이을 업체가 없으면 '골라 뒀어요'라고 하지 않는다
    vendor(api, "gyeol@mitjip.test", "결도배")
    query("delete from assistant_nudges")
    use(api, f["token"])
    tick(api)
    (n,) = nudges(trigger="vendor_out")
    assert n["status"] == "sent" and n["body"].startswith("마루와벽이 48시간 안에 답하지 않았어요.")
    # 2일 뒤 상태가 그대로면 알림(notify) 한 번, 밤이면 9시로
    query(
        "update assistant_nudges set sent_at = sent_at - interval '49 hours' where id = $1", n["id"]
    )
    assert run(api, proactive.scan_time, at(14)) == 1
    assert run(api, proactive.scan_time, at(14)) == 0
    assert run(api, proactive.evaluate_due, at(22)) == {"deferred": 1}
    assert run(api, proactive.evaluate_due, at(9, 1)) == {"sent": 1}
    (late,) = nudges(channel="notify")
    assert late["body"] == "마루와벽 대신 맞는 업체를 골라 뒀어요. 추천을 확인해 주세요."
    assert line(n["id"]) == ("expired", "replaced")  # 같은 대상 보이는 줄은 하나


# ---- 추가 금액(extra_added) ----


def test_extra_added_card_amounts_and_approve_closes_line(api, monkeypatch):
    quiet(monkeypatch)
    customer, pid, did = scheduled(api)
    query("delete from notifications")  # 앞 단계 알림은 이 시험과 상관없다
    x = post_extra(api, did, 150_000)
    use(api, customer)
    tick(api)
    (n,) = nudges(trigger="extra_added")
    assert (n["status"], str(n["ref_id"])) == ("sent", x["id"])
    # 금액(계산 엔진 합계)을 넣어 같은 업체 추가 금액 여럿이 구분돼요(F: QA 2차 t1 N9)
    assert n["body"] == "마루와벽이 추가 금액 165,000원을 올렸어요. 금액을 확인해 주세요."
    card = card_of(n)
    d, m = card["data"], from_entered(150_000, "excluded")
    assert card["kind"] == "extra" and card["card_id"] == f"extra-{x['id']}"
    assert (d["supply_won"], d["vat_won"], d["total_won"]) == (m.supply, m.vat, m.total)
    extras = api.get(f"/projects/{pid}/schedule").json()["trades"][0]["extras"]
    assert d["after_total_won"] == extras["items"][0]["after_total"]  # 계산 엔진 값 그대로
    assert d["grand_total_won"] == extras["grand_total"]
    assert (d["title"], d["vendor_note"], d["ref"]) == (MOLD["title"], MOLD["reason"], "x1")
    # 승인 카드는 미리 만들지 않아요(망설이는 고객을 승인 쪽으로 밀지 않게): 카드 단추로 고른 답의 승인 카드
    assert n["action_id"] is None and not query("select 1 from assistant_actions")
    choice = {"card_id": card["card_id"], "choice": f"extra_answer:{d['ref']}"}
    ev = ok(ask(api, pid, "추가 금액 승인할래요", context=choice))
    (a,) = [x for x in acts(ev) if x["kind"] == "extra_answer" and x["status"] == "proposed"]
    a = action(uuid.UUID(a["action_id"]))
    assert (a["kind"], a["target_kind"], a["payload"]["answer"]) == (
        "extra_answer",
        "extra",
        "approve",
    )
    assert a["summary"]["amount_won"] == m.total
    assert a["summary"]["diff"]["to_won"] == d["after_total_won"]
    assert MOLD["reason"] not in json.dumps(
        a["summary"], ensure_ascii=False
    )  # 업체 글은 카드 칸에만
    r = approve(api, str(a["id"]))
    assert r.json()["status"] == "executed", r.text
    assert query("select ack from extra_charges")[0]["ack"] == "approved"
    assert line(n["id"]) == ("expired", "acted")
    acked = query("select dedup_key from notifications where kind = 'extra_acked'")
    assert [x["dedup_key"] for x in acked] == [f"extra:{x['id']}:approved"]


def test_extra_answered_on_screen_closes_line_and_waiting_line(api, monkeypatch):
    quiet(monkeypatch)
    customer, pid, did = scheduled(api)
    query("delete from notifications")
    one, two = post_extra(api, did, 50_000), post_extra(api, did, 70_000)
    use(api, customer)
    run(api, proactive.scan_events, at(14))
    # 평가 전에 화면에서 둘째를 거절했다: 기다리던 줄은 보내지 않는다
    r = api.post(
        f"/projects/{pid}/deals/{did}/extras/{two['id']}/answer", json={"answer": "reject"}
    )
    assert r.status_code == 200, r.text
    run(api, proactive.evaluate_due, at(14))
    rows = {str(n["ref_id"]): n for n in nudges(trigger="extra_added")}
    assert rows[two["id"]]["status"] == "expired" and rows[two["id"]]["reason"] == "gone"
    first = rows[one["id"]]
    assert first["status"] == "sent"
    # 보낸 뒤 화면에서 답하면 정리(2분)가 줄 · 열린 승인 카드를 닫는다
    r = api.post(
        f"/projects/{pid}/deals/{did}/extras/{one['id']}/answer", json={"answer": "approve"}
    )
    assert r.status_code == 200
    run(api, assistant_service.sweep, now_utc())
    assert line(first["id"]) == ("expired", "handled")
    assert first["action_id"] is None  # 승인 카드는 미리 만들지 않아요(카드 단추로 고른 답만)


# ---- 공사 끝(work_done · done_remind) ----


def worked() -> None:
    query("update deals set start_date = $1, end_date = $2", TODAY - timedelta(days=3), TODAY)


def test_work_done_checklist_then_remind_notify_and_approve(api, monkeypatch):
    quiet(monkeypatch)
    customer, _pid, did = scheduled(api)
    worked()
    query("delete from notifications")
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer)
    tick(api)
    (n,) = nudges(trigger="work_done")
    assert (n["status"], n["channel"], str(n["ref_id"])) == ("sent", "feed", did)  # 이력 → 확정
    card = card_of(n)
    assert card["kind"] == "knowledge" and card["data"]["title"] == "공사 끝 점검표"
    labels = [x["label"] for x in card["data"]["checklist"]]
    assert any("들뜬" in x for x in labels) and any("이음매" in x for x in labels)
    assert "하자" in card["data"]["source"] and any(
        "자동으로 끝나요" in x for x in card["data"]["lines"]
    )
    a = action(n["action_id"])
    assert (a["kind"], a["payload"]["result"], a["target_ver"]) == (
        "work_check",
        "done",
        "checking",
    )
    # 4일 뒤 '자동으로 끝나요' 알림 → 새 줄(앞 줄을 바꿈)
    query(
        "update assistant_nudges set sent_at = sent_at - interval '4 days' where id = $1", n["id"]
    )
    (deal,) = query("select done_posted_at from deals where id = $1", uuid.UUID(did))
    run(
        api,
        deal_job("deal_done_remind", did, deal["done_posted_at"] + timedelta(days=4, minutes=1)),
    )
    tick(api)
    remind = [x for x in nudges(trigger="work_done") if x["id"] != n["id"]]
    assert len(remind) == 1 and remind[0]["status"] == "sent"
    # 근원 done_remind 알림이 이미 울려 비서는 종 없이 대화 줄로 보내요(하루 알림 상한에 세지 않음, 점검 R1b #17)
    assert remind[0]["channel"] == "feed"
    assert remind[0]["body"] == "마루와벽 공사가 곧 자동으로 끝나요. 점검표로 확인해 주세요."
    assert line(n["id"]) == ("expired", "replaced")
    # 같은 사건 종 알림은 하나: 시스템 done_remind 알림이 이미 울려 비서 알림은 더하지 않는다(QA edge P17)
    assert not query("select 1 from notifications where kind = 'assistant_nudge'")
    assert len(query("select 1 from notifications where kind = 'done_remind'")) == 1
    r = approve(api, str(remind[0]["action_id"]))
    assert r.json()["status"] == "executed", r.text
    assert query("select status from deals")[0]["status"] == "done"
    assert line(remind[0]["id"]) == ("expired", "acted")


# ---- 공사 1주 전(prep_week, 시간) ----


def start_in(n: int) -> str:
    """수락한 공사 날짜를 오늘 + n일부터 3일로 옮긴다(시간 트리거는 시작일만 본다)."""
    start = TODAY + timedelta(days=n)
    query("update deals set start_date = $1, end_date = $2", start, start + timedelta(days=2))
    return start.isoformat()


def test_prep_week_time_trigger_two_cards_night_cap_and_moved_start(api, monkeypatch, script):
    quiet(monkeypatch)
    customer, pid, did = scheduled(api)
    use(api, customer)
    query("delete from notifications")
    start_in(3)
    assert run(api, proactive.scan_time, at(14)) == 0  # 시작 3일 안이면 만들지 않는다
    start_in(8)
    assert run(api, proactive.scan_time, at(14)) == 0  # 아직 일주일보다 멀다
    start = start_in(6)
    assert run(api, proactive.scan_time, at(14)) == 1
    assert run(api, proactive.scan_time, at(14)) == 0  # 같은 확정 · 같은 시작일은 한 번
    (n,) = nudges(trigger="prep_week")
    assert (n["channel"], n["dedup_key"]) == ("feed", f"prep_week:{did}:{start}")
    # 대화 줄(feed)이라 밤 · 하루 알림 상한에 걸리지 않아요
    # 점수 65(기한 7일 · 날짜 결정 +15 · 승인 카드 없음): Haiku 판정 → 보냄
    # AI 글은 붙은 카드(공사 전 할 일 · 이웃 안내문)를 말해야 써요(F: QA 2차 t1 N7)
    script(
        [
            {"json": {"send": True}},
            {"json": {"text": "도배 공사가 일주일 남았어요. 공사 전 할 일을 챙겨 볼까요?"}},
        ]
    )
    assert run(api, proactive.evaluate_due, at(22)) == {"sent": 1}
    (n,) = nudges(trigger="prep_week")
    assert (n["status"], n["score"], n["src"]) == ("sent", 65, "ai")
    before, notice = card_of(n)  # 카드 둘: 공사 전 할 일 + 이웃 안내문 초안
    assert before["kind"] == "knowledge" and before["data"]["title"] == "공사 전 할 일"
    assert any("관리사무소" in x["label"] for x in before["data"]["checklist"])
    d = notice["data"]
    assert notice["kind"] == "notice" and d["start"] == start and d["style_exempt"] is True
    assert "○○동 ○○호" in d["text"] and "합니다" in d["text"] and "010" not in d["text"]
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    (item,) = [x for x in feed["items"] if x.get("nudge_id") == str(n["id"])]
    assert [p["t"] for p in item["parts"]] == ["text", "card", "card", "suggest"]
    today = api.get("/assistant/today", params={"project_id": pid}).json()
    assert [k["id"] for k in today["know"]] == [f"k-{n['id']}"]  # 알아 두기
    # 판정을 못 부르면 알림은 기록만, 시작일이 바뀌면 그 줄은 닫힌다
    llm.clear_stubs()
    moved = add_nudge(
        n["user_id"], trigger="prep_week", channel="feed", ref=uuid.UUID(did),
        project_id=n["project_id"], dedup_key=f"prep_week:{did}:{start}:x",
    )  # fmt: skip
    run(api, proactive.evaluate_due, at(10, 2))
    assert line(moved)[0] == "sent"  # 판정을 못 불러도 대화 줄(feed)은 보내요
    query("update assistant_nudges set status = 'pending' where id = $1", moved)
    start_in(10)
    run(api, proactive.evaluate_due, at(10, 2))
    assert line(moved) == ("expired", "gone")


# ---- 업체: 날짜 바꾸기 요청(dates_requested) · 견적서 기한(quote_due) · 확정 무응답 ----


def test_dates_requested_vendor_line_uses_customer_start_and_closes(api, monkeypatch):
    quiet(monkeypatch)
    customer, pid, did, _ = ready(api)
    assert propose(api, did, *days(14)).status_code == 200
    use(api, customer)
    w1, w2 = days(28, 2)
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [w2, w1]})
    assert r.status_code == 201, r.text
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'dates_requested'")
    tick(api)
    (n,) = nudges(trigger="dates_requested")
    assert (n["surface"], n["status"], str(n["ref_id"])) == ("vendor", "sent", did)  # 요청 → 확정
    assert "고객이 공사 날짜를 바꾸고 싶어 해요. 고른 날로 후보를 골라 뒀어요." in n["body"]
    a = action(n["action_id"])
    assert (a["kind"], a["target_ver"], a["payload"]["kind"]) == ("dates", "requested", "initial")
    assert a["payload"]["days"][0] == w1  # 고객이 고른 시작일
    login(api, "maru@mitjip.test")
    r = approve(api, str(n["action_id"]), prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    (req,) = query("select status from date_requests")
    assert req["status"] == "answered" and line(n["id"]) == ("expired", "acted")
    (p,) = query("select start_date, kind from date_proposals where status = 'pending'")
    assert (p["start_date"].isoformat(), p["kind"]) == (w1, "initial")


def test_change_request_after_accept_sends_change_dates(api, monkeypatch):
    quiet(monkeypatch)
    customer, pid, did = scheduled(api)  # 날짜를 수락한 공사
    use(api, customer)
    w1 = days(35, 1)[0]
    body = {"wish_dates": [w1], "reason": "이사 날짜가 바뀌었어요."}
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body)
    assert r.status_code == 201, r.text
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'dates_requested'")
    tick(api)
    (n,) = nudges(trigger="dates_requested")
    a = action(n["action_id"])
    assert (a["target_ver"], a["payload"]["kind"], a["payload"]["days"][0]) == (
        "change_requested",
        "change",
        w1,
    )
    login(api, "maru@mitjip.test")
    r = approve(api, str(n["action_id"]), prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    (p,) = query("select start_date, kind from date_proposals where status = 'pending'")
    assert (p["start_date"].isoformat(), p["kind"]) == (w1, "change")
    assert query("select link from notifications where kind = 'dates_proposed'")


def test_quote_due_vendor_notify_until_quote_is_sent(api, monkeypatch):
    quiet(monkeypatch)
    f = booked(api)
    now = at(14)
    due = now + timedelta(hours=20)  # 실측 뒤 견적서 기한이 하루 안
    query(
        "update visits set status = 'visited', visited_at = now(), quote_due_at = $1 where id = $2",
        due,
        uuid.UUID(f["visit"]),
    )
    query("delete from assistant_nudges")
    query("delete from notifications")
    assert run(api, proactive.scan_time, now - timedelta(hours=6)) == 0  # 아직 하루보다 멀다
    assert run(api, proactive.scan_time, now) == 1
    assert run(api, proactive.scan_time, now) == 0
    (n,) = nudges(trigger="quote_due")
    assert (n["surface"], n["channel"], n["project_id"]) == ("vendor", "notify", None)
    assert run(api, proactive.evaluate_due, now) == {"sent": 1}  # 점수: 기한 24시간 안 +50
    (n,) = nudges(trigger="quote_due")
    assert n["score"] == 100 and card_of(n)["kind"] == "quote_checklist"
    assert n["body"].endswith("견적서 기한이 하루 남았어요. 빠진 항목을 같이 볼까요?")
    (note,) = query("select link from notifications where kind = 'assistant_nudge'")
    assert note["link"] == f"/vendor/requests/{f['visit']}/quote"
    # 견적서를 보낸 뒤에는 보내지 않는다
    login(api, f["email"])
    quote(api, f["visit"], 3_080_000)
    extra = add_nudge(
        n["user_id"], trigger="quote_due", surface="vendor", ref=uuid.UUID(f["visit"]),
        dedup_key=n["dedup_key"] + ":again",
    )  # fmt: skip
    run(api, proactive.evaluate_due, at(15))
    assert line(extra) == ("expired", "gone")


def test_deal_confirmed_follow_notify_until_dates_sent(api, monkeypatch):
    quiet(monkeypatch)
    _customer, _pid, did, _ = ready(api)
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'deal_confirmed'")
    tick(api)
    (n,) = nudges(trigger="deal_confirmed")
    assert n["status"] == "sent"
    query(
        "update assistant_nudges set sent_at = sent_at - interval '25 hours' where id = $1", n["id"]
    )
    assert run(api, proactive.scan_time, at(14)) == 1
    assert run(api, proactive.evaluate_due, at(14)) == {"sent": 1}
    (late,) = nudges(channel="notify")
    assert "요청의 공사 날짜를 아직 내지 않았어요." in late["body"]
    (note,) = query("select link from notifications where kind = 'assistant_nudge'")
    assert note["link"] == f"/vendor/jobs/{did}"
    # 날짜를 낸 뒤에는 무응답 알림을 다시 보내지 않는다
    assert propose(api, did, *days(14)).status_code == 200
    again = add_nudge(
        n["user_id"], trigger="deal_confirmed", surface="vendor", ref=uuid.UUID(did),
        dedup_key=n["dedup_key"] + ":again",
    )  # fmt: skip
    run(api, proactive.evaluate_due, at(15))
    assert line(again) == ("expired", "gone")

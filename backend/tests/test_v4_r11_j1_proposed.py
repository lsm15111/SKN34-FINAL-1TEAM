"""QA 11차 뒤 고침 J1-2(c1 '그대로', 유료 호출 0회): 업체가 실측 다른 날을 제안하면 종 알림(visit_proposed)만 오고
고객 비서 대화에는 줄이 없었어요. 정해 둔 틀 줄 하나 + 업체가 낸 날 카드를 대화 줄로 보내요(종 알림은 더하지 않아요)."""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.agent import llm
from app.assistant import proactive
from app.assistant import repository as repo
from app.db import SessionLocal
from app.shared.clock import now_utc
from tests.conftest import query
from tests.helpers import use
from tests.test_v3_visit_kit import d, handle, notes, picked, quiet
from tests.test_v4_assistant_nudges import nudges, run
from tests.test_visit_inbox import login

TEXT = "마루와벽이 실측 날짜로 다른 날을 제안했어요. 고르실 날을 확인해 주세요."
SLOTS = [{"day": d(7), "half": "pm"}, {"day": d(8), "half": "am"}]


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def _proposed(api) -> dict:
    """고객이 고른 실측 날짜에 업체가 다른 날 둘을 제안해요. 고객으로 로그인한 채 끝나요."""
    f = picked(api)
    login(api, f["email"])
    body = {"reason_code": "other_site", "note": "앞 현장이 늦게 끝나요", "slots": SLOTS}
    r = api.post(f"/vendor/visits/{f['visit']}/propose", json=body)
    assert r.status_code == 200, r.text
    use(api, f["token"])
    return f


def test_vendor_other_day_sends_one_feed_line(api, monkeypatch, script):
    quiet(monkeypatch)
    f = _proposed(api)
    # Haiku 대본: 부르면 안 돼요(틀만 써요)
    log = script([{"json": {"text": "마루와벽이 반나절 두 개를 냈어요."}}])
    now = now_utc()
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    (line,) = nudges(trigger="visit_proposed")
    assert str(line["ref_id"]) == f["visit"]  # 대상은 실측 요청(다른 실측 줄과 같게)
    assert (line["status"], line["channel"], line["src"]) == ("sent", "feed", "guide")
    assert line["body"] == TEXT and "반나절" not in line["body"]
    assert log == []  # 판정 · 문장에 Haiku를 부르지 않아요
    # 붙은 카드: 업체가 낸 날(고르면 바로 정해져요)
    card = json.loads(line["card"])
    assert card["kind"] == "visit_slots"
    assert [(c["day"], c["half"]) for c in card["data"]["candidates"]] == [
        (x["day"], x["half"]) for x in SLOTS
    ]
    assert line["action_id"] is None  # 승인 카드는 고객이 날을 고를 때 만들어요
    # 종 알림은 업체가 제안할 때 하나 그대로(비서는 더하지 않아요)
    kinds = [n["kind"] for n in notes("home@mitjip.test")]
    assert kinds.count("visit_proposed") == 1 and "assistant_nudge" not in kinds
    # 고객 대화 기록에 줄 하나
    feed = api.get("/assistant/feed", params={"project_id": f["pid"]}).json()
    shown = [x for x in feed["items"] if x.get("nudge_id")]
    assert len(shown) == 1 and shown[0]["parts"][0]["text"] == TEXT
    # 다시 돌려도 줄은 하나
    run(api, proactive.scan_events, now)
    assert len(nudges(trigger="visit_proposed")) == 1


def test_other_day_line_closes_when_picked(api, monkeypatch):
    """고객이 업체가 낸 날을 고르면(화면) 정리가 줄을 '완료'로 닫아요."""
    quiet(monkeypatch)
    f = _proposed(api)
    now = now_utc()
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    url = f"/projects/{f['pid']}/visits/{f['visit']}/proposal/pick"
    r = api.post(url, json=SLOTS[1])
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text
    run(api, proactive.close_settled, now)
    (line,) = nudges(trigger="visit_proposed")
    assert (line["status"], line["reason"]) == ("expired", "handled")


def test_other_day_line_lapses_when_not_picked(api, monkeypatch):
    """고르지 않아 제안 기한이 지나면(처음 기간으로 돌아감) '완료'가 아니라 지난 줄(lapsed)이에요."""
    quiet(monkeypatch)
    _proposed(api)
    now = now_utc()
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    (p,) = query("select id, due_at from visit_proposals")
    later = p["due_at"] + timedelta(minutes=1)
    handle("visit_proposal_due", p["id"], later)
    assert query("select status from visits")[0]["status"] == "offered"
    run(api, proactive.close_settled, later)
    (line,) = nudges(trigger="visit_proposed")
    assert (line["status"], line["reason"]) == ("expired", repo.LAPSED)


def test_slot_action_closes_other_day_line(api, monkeypatch):
    """업체가 낸 날 · 다시 고르기 승인 카드(visit_slot)가 실행되면 그 실측 요청의 다른 날 줄도 바로 닫아요."""
    quiet(monkeypatch)
    f = _proposed(api)
    now = now_utc()
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    (line,) = nudges(trigger="visit_proposed")
    a = SimpleNamespace(
        user_id=line["user_id"],
        target_kind="visit",
        target_id=uuid.UUID(f["visit"]),
        kind="visit_slot",
        payload={},
    )

    async def close() -> int:
        async with SessionLocal() as s:
            n = await repo.close_lines_of(s, a)
            await s.commit()
            return n

    assert run(api, close) == 1
    (line,) = nudges(trigger="visit_proposed")
    assert (line["status"], line["reason"]) == ("expired", "acted")

"""v4 먼저 말 걸기(계약서 6장): 규칙(하루 상한 · 밤 · 쉬기 · 멈춤, 고정 시계) · 점수 · Haiku 판정 · 문장(대본) ·
아웃박스(상태 전이 알림) → 제안 → 보냄(카드 · 승인 카드 · 알림) · 무응답 알림 · 상태가 바뀌면 닫힘 ·
대화 기록 · 오늘 · 열기 · 닫기 API · 권한(남의 것 404 · 역할 403). 유료 호출 0회(Claude 대본)."""

import uuid
from datetime import UTC, datetime, time, timedelta
from functools import partial

import pytest

from app.agent import llm
from app.assistant import policy, proactive
from app.shared.clock import SEOUL, today_seoul
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v3_visit_kit import offered, quiet, requested
from tests.test_visit_inbox import login

R = policy.NudgeRules()


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def at(hour: int, day_shift: int = 0) -> datetime:
    """오늘(서울) hour시. 시험 시계는 이 값으로 고정해 넘긴다."""
    return datetime.combine(today_seoul() + timedelta(days=day_shift), time(hour), SEOUL)


def run(api, fn, *args, **kw):
    """앱과 같은 이벤트 루프에서 돌린다(Redis 연결을 루프 사이에 섞지 않게)."""
    return api.portal.call(partial(fn, *args, **kw))


def nudges(**where) -> list[dict]:
    sql = "select * from assistant_nudges"
    if where:
        sql += " where " + " and ".join(f"{k} = ${i}" for i, k in enumerate(where, 1))
    return [dict(r) for r in query(sql + " order by created_at", *where.values())]


def add_nudge(user_id, *, trigger="visit_offered", channel="notify", ref=None, **kw) -> uuid.UUID:
    nid = uuid.uuid4()
    cols = {
        "id": nid,
        "user_id": user_id,
        "surface": kw.pop("surface", "customer"),
        "project_id": kw.pop("project_id", None),
        "trigger": trigger,
        "ref_id": ref or uuid.uuid4(),
        "dedup_key": kw.pop("dedup_key", f"test:{nid}"),
        "channel": channel,
        "status": kw.pop("status", "pending"),
        "due_at": kw.pop("due_at", datetime.now(UTC) - timedelta(days=2)),
        **kw,
    }
    names = ", ".join(cols)
    marks = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    query(f"insert into assistant_nudges ({names}) values ({marks})", *cols.values())
    return nid


def sent(user_id, n: int, at_: datetime, trigger="quote_sent", channel="notify") -> None:
    for _ in range(n):
        add_nudge(
            user_id,
            trigger=trigger,
            channel=channel,
            status="sent",
            sent_at=at_,
            body="본문이에요",
            src="guide",
        )


# ---- 규칙 · 점수 (DB 없음, 고정 시계) ----


def test_rules_night_cap_snooze_mute_with_fixed_clock():
    noon, night, dawn = at(14), at(22), at(6)
    ok = {"trigger": "visit_offered", "surface": "customer", "sent_today": 0, "dismissals": []}
    assert R.check(channel="notify", now=noon, **ok).verdict == "send"
    # 밤(21~9시) 알림은 다음 9시로, 대화 기록(feed)은 밤에도 쌓는다
    got = R.check(channel="notify", now=night, **ok)
    assert (got.verdict, got.reason, got.until) == ("defer", "night", at(9, 1))
    assert R.check(channel="notify", now=dawn, **ok).until == at(9)
    assert R.check(channel="feed", now=night, **ok).verdict == "send"
    # 하루 알림 상한: 고객 2 · 업체 3(넘으면 내일 9시로)
    capped = {**ok, "sent_today": 2}
    got = R.check(channel="notify", now=noon, **capped)
    assert (got.verdict, got.reason, got.until) == ("defer", "cap", at(9, 1))
    assert R.check(channel="feed", now=noon, **capped).verdict == "send"
    vendor = {**capped, "surface": "vendor"}
    assert R.check(channel="notify", now=noon, **vendor).verdict == "send"
    assert R.check(channel="notify", now=noon, **{**vendor, "sent_today": 3}).verdict == "defer"
    # 닫으면 같은 trigger 3일 쉬기(feed도), 다른 trigger는 그대로
    d = [policy.Dismissal("visit_offered", noon - timedelta(days=2))]
    got = R.check(channel="feed", now=noon, **{**ok, "dismissals": d})
    assert (got.verdict, got.reason) == ("hold", "snooze")
    other = {**ok, "trigger": "quote_sent", "dismissals": d}
    assert R.check(channel="notify", now=noon, **other).verdict == "send"
    d3 = [policy.Dismissal("visit_offered", noon - timedelta(days=3, minutes=1))]
    assert R.check(channel="feed", now=noon, **{**ok, "dismissals": d3}).verdict == "send"
    # 7일 안에 두 번 닫으면 알림 7일 멈춤(대화 기록은 그대로)
    two = [
        policy.Dismissal("quote_sent", noon - timedelta(days=6)),
        policy.Dismissal("dates_proposed", noon - timedelta(days=4)),
    ]
    got = R.check(channel="notify", now=noon, **{**ok, "dismissals": two})
    assert (got.verdict, got.reason) == ("hold", "mute")
    assert R.muted_until(two) == noon - timedelta(days=4) + timedelta(days=7)
    assert R.check(channel="feed", now=noon, **{**ok, "dismissals": two}).verdict == "send"
    later = noon + timedelta(days=3, minutes=1)  # 멈춤 끝
    assert R.check(channel="notify", now=later, **{**ok, "dismissals": two}).verdict == "send"
    apart = [
        policy.Dismissal("quote_sent", noon - timedelta(days=20)),
        policy.Dismissal("dates_proposed", noon - timedelta(days=4)),
    ]
    assert R.muted_until(apart) is None  # 7일보다 멀리 떨어진 두 번은 멈추지 않는다


def test_score_parts():
    f = proactive.Facts("visit_offered", "feed", "customer")
    assert proactive.score(f) == 50
    f.hours_left = 20
    assert proactive.score(f) == 100
    f.hours_left = 40
    assert proactive.score(f) == 80
    f.hours_left, f.action_ready, f.decision = 100, True, True
    assert proactive.score(f) == 85
    f.read = True
    assert proactive.score(f) == 55
    f.sent_24h = 2
    assert proactive.score(f) == 15
    f.dismissed_same = True
    assert proactive.score(f) == 0  # 0 아래로 내려가지 않는다
    full = proactive.Facts("work_eve", "notify", "customer", 1, True, True)
    assert proactive.score(full) == 100  # 100 위로 올라가지 않는다


def test_triggers_match_the_table():
    from app.assistant.models import NUDGE_TRIGGERS

    assert set(proactive.TRIGGERS) == set(NUDGE_TRIGGERS)
    assert proactive.EVENT_KINDS == {
        "visit_offered": "visit_offered",
        "quote_sent": "quote_sent",
        "quote_resent": "quote_sent",
        "dates_proposed": "dates_proposed",
        "visit_requested": "visit_requested",
        "visit_picked": "visit_picked",
        "deal_confirmed": "deal_confirmed",
        # 07 자동화(aftercare.TRIGGERS)
        "visit_declined": "vendor_out",
        "visit_reply_expired": "vendor_out",
        "visit_vendor_stopped": "vendor_out",
        "quote_late": "vendor_out",
        "extra_added": "extra_added",
        "work_done": "work_done",
        "done_remind": "work_done",
        "dates_requested": "dates_requested",
    }
    names = {"vendor": "결도배", "trade": "도배", "area": "노원구 상계동 도배"}
    for t in proactive.TRIGGERS.values():
        assert t.say and t.why and (t.feed or t.notify)
        for ch in ("feed", "notify"):
            text = proactive.template(proactive.Facts(t.name, ch, t.surface, names=names))
            assert len(text) <= 60 and text.endswith(("요.", "요?")), text


# ---- 판정 · 문장 (대본) ----


def test_judge_and_write_use_haiku_and_fall_back(api, script):
    f = proactive.Facts(
        "visit_offered", "notify", "customer", hours_left=30, names={"vendor": "결도배"}
    )
    log = script([{"json": {"send": False}}])
    assert run(api, proactive.judge, f, None) is False
    assert log[0]["model"] == "claude-haiku-5-5"
    body = log[0]["messages"][0]["content"]
    assert "결도배" in body and "hours_left" in body  # 코드 사실만(JSON)
    script([RuntimeError("down")])
    assert run(api, proactive.judge, f, None) is None  # 못 부르면 None
    llm.clear_stubs()
    assert run(api, proactive.judge, f, None) is None  # 꺼짐
    # 문장: 검사를 지나면 AI 글, 사실에 없는 숫자 · 한 일처럼 · 너무 긴 글은 틀
    script([{"json": {"text": "결도배 실측 날짜를 30시간 안에 골라 주세요."}}])
    assert run(api, proactive.write, f, None) == (
        "결도배 실측 날짜를 30시간 안에 골라 주세요.",
        "ai",
    )
    for bad in (
        "결도배 실측을 3일 안에 골라 주세요.",
        "제가 결도배 실측을 확정했어요.",
        "결도배 실측 날짜를 골라 주세요" + " 꼭" * 30 + "요.",
        "결도배 실측 날짜를 골라 주십시오.",  # '요'로 끝나지 않음
        "결도배 실측은 https://mitjip.test 에서 골라 주세요.",  # 링크
    ):
        script([{"json": {"text": bad}}])
        text, src = run(api, proactive.write, f, None)
        assert src == "guide" and text == proactive.template(f), bad
    usage = query("select purpose, model from llm_usage")
    assert {u["purpose"] for u in usage} == {"nudge"}


# ---- 아웃박스 → 제안 → 보냄 ----


def offered_nudge(api, monkeypatch) -> tuple[dict, dict]:
    quiet(monkeypatch)
    f = offered(api)
    now = at(14)
    made = run(api, proactive.scan_events, now)
    assert made == 2  # 업체 새 요청(visit_requested) · 고객 기간 옴(visit_offered)
    assert run(api, proactive.scan_events, now) == 0  # 같은 알림은 다시 읽지 않는다
    tally = run(api, proactive.evaluate_due, now)
    assert tally == {"sent": 1, "expired": 1}  # 업체 쪽은 이미 답해서(상태 바뀜) 닫힘
    (n,) = nudges(trigger="visit_offered")
    return f, n


def test_visit_offered_sends_feed_card_action_and_api(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    (gone,) = nudges(trigger="visit_requested")
    assert (gone["status"], gone["reason"]) == ("expired", "gone")
    assert (n["status"], n["channel"], n["src"], n["score"]) == ("sent", "feed", "guide", 85)
    assert n["body"].startswith("마루와벽이 실측 기간을 보냈어요")
    card = __import__("json").loads(n["card"])
    assert card["kind"] == "visit_slots" and card["data"]["candidates"]
    (a,) = query("select kind, origin, status from assistant_actions where id = $1", n["action_id"])
    assert (a["kind"], a["origin"], a["status"]) == ("visit_slot", "nudge", "proposed")
    # 대화 기록: 대화가 없어도 먼저 말 건 줄이 보인다(문장 · 카드 · 승인 카드 · 작업 카드 · 다음에 물을 말)
    feed = api.get("/assistant/feed", params={"project_id": f["pid"]}).json()
    (item,) = feed["items"]
    assert item["id"] == f"n-{n['id']}" and item["nudge_id"] == str(n["id"])
    kinds = [p["t"] for p in item["parts"]]
    assert kinds == ["text", "card", "action", "task", "suggest"]
    task = item["parts"][3]["task"]
    assert task["task_id"] == "visits" and task["rows"][0]["state"] == "need"
    sug = item["parts"][4]["suggest"]
    assert sug["nudge_id"] == str(n["id"]) and sug["say"] == "실측 날짜 고를래요"
    today = api.get("/assistant/today", params={"project_id": f["pid"]}).json()
    assert today["nudge_id"] == str(n["id"]) and today["dismissed"] is False
    # 열기 · 닫기(두 번 눌러도 같음) · 닫은 뒤 오늘 카드
    r = api.post(f"/assistant/nudges/{n['id']}/open")
    assert r.status_code == 200 and r.json()["status"] == "opened"
    r = api.post(f"/assistant/nudges/{n['id']}/dismiss")
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["acted_at"]
    assert api.post(f"/assistant/nudges/{n['id']}/dismiss").json()["status"] == "dismissed"
    assert api.post(f"/assistant/nudges/{n['id']}/open").json()["status"] == "dismissed"
    today = api.get("/assistant/today", params={"project_id": f["pid"]}).json()
    assert today["nudge_id"] is None and today["dismissed"] is True
    feed = api.get("/assistant/feed", params={"project_id": f["pid"]}).json()
    assert feed["items"] == []  # 닫은 줄은 대화 기록에서 빠진다
    # 닫은 trigger는 3일 쉰다(같은 대상의 새 제안도 기록만)
    uid = n["user_id"]
    again = add_nudge(
        uid, trigger="visit_offered", channel="feed", ref=n["ref_id"], project_id=n["project_id"]
    )
    run(api, proactive.evaluate_due, at(15))
    (row,) = nudges(id=again)
    assert (row["status"], row["reason"]) == ("held", "snooze")
    # 권한: 남의 제안은 404, 업체는 고객 API 403, 기다리는 줄은 404
    assert api.post(f"/assistant/nudges/{again}/open").status_code == 404
    signup(api, "other@mitjip.test")
    assert api.post(f"/assistant/nudges/{n['id']}/dismiss").status_code == 404
    login(api, f["email"])
    assert api.post(f"/assistant/nudges/{n['id']}/dismiss").status_code == 403
    assert api.post(f"/vendor/assistant/nudges/{n['id']}/dismiss").status_code == 404


def test_follow_up_notify_after_48h_then_state_change_closes(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    query(
        "update assistant_nudges set sent_at = sent_at - interval '49 hours' where id = $1", n["id"]
    )
    noon = at(14)
    assert run(api, proactive.scan_time, noon) == 1
    assert run(api, proactive.scan_time, noon) == 0  # 무응답 알림은 한 번
    late = nudges(channel="notify")[0]
    assert late["dedup_key"] == n["dedup_key"] + ":notify" and late["status"] == "pending"
    # 밤에는 9시로 미룬다
    assert run(api, proactive.evaluate_due, at(22)) == {"deferred": 1}
    assert nudges(id=late["id"])[0]["due_at"] == at(9, 1)
    tally = run(api, proactive.evaluate_due, at(9, 1))
    assert tally == {"sent": 1}
    late = nudges(id=late["id"])[0]
    assert late["status"] == "sent" and late["body"].startswith(
        "마루와벽이 보낸 실측 기간에서 아직"
    )
    (note,) = query("select kind, link, body from notifications where kind = 'assistant_nudge'")
    assert note["link"] == f"/projects/{f['pid']}" and note["body"] == late["body"]
    first = nudges(id=n["id"])[0]
    assert (first["status"], first["reason"]) == (
        "expired",
        "replaced",
    )  # 대상마다 보이는 줄은 하나
    # 상태가 바뀌면(업체 답 → 고객이 고름) 기다리던 제안은 닫힌다
    other = add_nudge(
        n["user_id"], trigger="visit_offered", ref=n["ref_id"], project_id=n["project_id"]
    )
    query("update visits set status = 'booked' where id = $1", n["ref_id"])
    run(api, proactive.evaluate_due, at(15, 1))
    assert (nudges(id=other)[0]["status"], nudges(id=other)[0]["reason"]) == ("expired", "gone")


def test_cap_mute_and_low_score_with_fixed_clock(api, monkeypatch):
    _f, n = offered_nudge(api, monkeypatch)
    uid, ref, pid = n["user_id"], n["ref_id"], n["project_id"]
    noon = at(16)
    # 오늘 알림 2번을 이미 보냈으면 내일 9시로
    sent(uid, 2, noon - timedelta(hours=1))
    capped = add_nudge(uid, ref=ref, project_id=pid)
    assert run(api, proactive.evaluate_due, noon) == {"deferred": 1}
    row = nudges(id=capped)[0]
    assert (row["status"], row["reason"], row["due_at"]) == ("pending", "cap", at(9, 1))
    # 7일 안에 두 번 닫았으면 알림 멈춤(기록만)
    for days in (5, 3):
        add_nudge(
            uid, trigger="no_pick", status="dismissed", sent_at=noon - timedelta(days=days),
            acted_at=noon - timedelta(days=days), body="본문이에요", src="guide",
        )  # fmt: skip
    run(api, proactive.evaluate_due, at(9, 1))
    row = nudges(id=capped)[0]
    assert (row["status"], row["reason"]) == ("held", "mute")
    # 점수 40 미만은 기록만(읽은 알림 −30 · 24시간 안 보낸 2번 −40). 무응답 다시 알림(':notify')이라
    # 감점을 받는다. 업체가 한 일로 생긴 첫 알림은 24시간 감점이 없다(test_v4_assistant_nudge_events, QA r2)
    query("update assistant_nudges set status = 'expired' where status = 'dismissed'")
    query("update notifications set read_at = now()")
    low = add_nudge(
        uid, channel="feed", ref=ref, project_id=pid, dedup_key=n["dedup_key"] + ":notify"
    )
    run(api, proactive.evaluate_due, noon)
    row = nudges(id=low)[0]
    assert (row["status"], row["reason"]) == ("held", "low") and row["score"] < 40


def test_judge_says_no_holds_and_judge_off_sends_only_feed(api, monkeypatch, script):
    _f, n = offered_nudge(api, monkeypatch)
    uid, ref, pid = n["user_id"], n["ref_id"], n["project_id"]
    query("update notifications set read_at = now()")  # 같은 알림 읽음 −30 → 55점(판정)
    query("update assistant_nudges set sent_at = sent_at - interval '2 days'")  # 24시간 밖
    key = n["dedup_key"]
    a = add_nudge(uid, channel="feed", ref=ref, project_id=pid, dedup_key=key + ":a")
    log = script([{"json": {"send": False}}])
    run(api, proactive.evaluate_due, at(14))
    row = nudges(id=a)[0]
    assert (row["status"], row["reason"], row["score"]) == ("held", "judge", 55)
    assert len(log) == 1 and log[0]["model"] == "claude-haiku-5-5"
    b = add_nudge(uid, channel="feed", ref=ref, project_id=pid, dedup_key=key + ":b")
    script([{"json": {"send": True}}, {"json": {"text": "마루와벽 실측 날짜를 골라 주세요."}}])
    run(api, proactive.evaluate_due, at(14))
    row = nudges(id=b)[0]
    assert (row["status"], row["src"], row["body"]) == (
        "sent",
        "ai",
        "마루와벽 실측 날짜를 골라 주세요.",
    )
    llm.clear_stubs()  # 꺼짐: 판정을 못 하면 대화 기록은 보내고 알림은 기록만(b를 보낸 지 24시간 뒤)
    early = datetime.now(UTC) - timedelta(days=3)  # c를 먼저 평가한다(d를 보내면 24시간 안 −20)
    c = add_nudge(
        uid, channel="notify", ref=ref, project_id=pid, dedup_key=key + ":c", due_at=early
    )
    d = add_nudge(uid, channel="feed", ref=ref, project_id=pid, dedup_key=key + ":d")
    run(api, proactive.evaluate_due, at(14, 2))
    assert (nudges(id=c)[0]["status"], nudges(id=c)[0]["reason"]) == ("held", "judge")
    assert (nudges(id=d)[0]["status"], nudges(id=d)[0]["src"]) == ("sent", "guide")


def test_vendor_request_nudge_with_window_answer(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    now = at(14)
    assert run(api, proactive.scan_events, now) == 1
    assert run(api, proactive.evaluate_due, now) == {"sent": 1}
    (n,) = nudges(trigger="visit_requested")
    assert n["surface"] == "vendor" and n["project_id"] is None
    (a,) = query("select kind, origin from assistant_actions where id = $1", n["action_id"])
    assert (a["kind"], a["origin"]) == ("window_answer", "nudge")
    login(api, f["email"])
    feed = api.get("/vendor/assistant/feed").json()
    (item,) = feed["items"]
    assert [p["t"] for p in item["parts"]] == ["text", "card", "action", "suggest"]
    assert item["parts"][1]["card"]["kind"] == "vendor_brief"
    assert item["parts"][1]["card"]["data"]["sentence"]  # 틀 문장
    assert "김믿집" not in str(item) and "01012345678" not in str(item)  # 고객 정보 없음
    r = api.post(f"/vendor/assistant/nudges/{n['id']}/open")
    assert r.status_code == 200 and r.json()["status"] == "opened"
    assert api.post(f"/assistant/nudges/{n['id']}/open").status_code == 403  # 업체가 고객 API
    use(api, f["token"])
    assert api.post(f"/vendor/assistant/nudges/{n['id']}/open").status_code == 403
    assert (
        api.post(f"/assistant/nudges/{n['id']}/open").status_code == 404
    )  # 업체 줄은 고객 API로 못 연다


def test_broken_nudge_is_closed_not_retried(api, monkeypatch):
    """평가 중 오류가 나면 그 줄을 expired(error)로 닫는다(2분마다 끝없이 다시 보지 않게)."""
    signup(api, "home@mitjip.test")
    uid = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    nid = add_nudge(uid)

    async def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(proactive, "context", boom)
    assert run(api, proactive.evaluate_due, at(14)) == {"error": 1}
    row = nudges(id=nid)[0]
    assert (row["status"], row["reason"]) == ("expired", "error")
    assert run(api, proactive.evaluate_due, at(14)) == {}

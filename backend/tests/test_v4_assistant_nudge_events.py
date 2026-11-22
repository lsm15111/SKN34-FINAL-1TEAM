"""먼저 말 걸기: 업체 · 고객이 한 일로 생긴 첫 알림은 24시간 감점 · 쉬기를 받지 않는다(QA r2 c1 · c2 · x1 · t1).

견적서 · 추가 금액 · 기간 같은 새 소식이 앞서 보낸 줄 수(sent_count)로 40점 아래가 되어 보류되던 것, 같은 종류 줄을
[괜찮아요]로 닫은 뒤 새 소식까지 3일 쉬기에 막히던 것을 막는다. 공사 전날 알림도 24시간 감점이 없다.
무응답 다시 알림(':notify')과 그 밖 시간 트리거는 그대로 감점 · 쉬기를 받는다. 유료 호출 0회."""

from datetime import timedelta
from types import SimpleNamespace

from app.assistant import proactive
from tests.test_v3_visit_kit import offered, quiet
from tests.test_v4_assistant_nudges import add_nudge, at, nudges, run, sent


def test_fresh_event_rule_by_trigger_and_key():
    offered_t = proactive.TRIGGERS["visit_offered"]
    eve = proactive.TRIGGERS["work_eve"]  # 시간 트리거(아웃박스 kind 없음)
    first = SimpleNamespace(dedup_key="visit_offered:abc")
    again = SimpleNamespace(dedup_key="visit_offered:abc:notify")
    assert proactive.fresh_event(offered_t, first) is True
    assert proactive.fresh_event(offered_t, again) is False  # 무응답 다시 알림은 감점 받음
    assert proactive.fresh_event(eve, first) is False
    # 공사 전날 알림은 시간 트리거지만 놓치면 안 돼서 24시간 감점이 없다(쉬기는 그대로)
    assert proactive.no_24h_penalty(eve, first) is True
    assert proactive.no_24h_penalty(offered_t, again) is False


def test_new_event_is_sent_even_after_two_sends_today(api, monkeypatch):
    quiet(monkeypatch)
    offered(api)
    now = at(14)
    assert run(api, proactive.scan_events, now) == 2
    (n,) = nudges(trigger="visit_offered")
    sent(
        n["user_id"], 2, now - timedelta(hours=1), channel="feed"
    )  # 오늘 이미 대화 줄 두 개를 보냈다
    tally = run(api, proactive.evaluate_due, now)
    assert tally["sent"] == 1
    (row,) = nudges(id=n["id"])
    # 감점(-40)을 받았다면 45점이라 판정(Haiku, 여기선 꺼짐)으로 갔을 것. 새 소식은 85점 그대로 보낸다
    assert (row["status"], row["score"]) == ("sent", 85)


def test_closed_line_of_same_kind_snoozes_reminders_not_new_events(api, monkeypatch):
    quiet(monkeypatch)
    offered(api)
    now = at(14)
    assert run(api, proactive.scan_events, now) == 2
    (n,) = nudges(trigger="visit_offered")
    uid, ref, pid = n["user_id"], n["ref_id"], n["project_id"]
    add_nudge(
        uid, trigger="visit_offered", channel="feed", status="dismissed",
        sent_at=now - timedelta(hours=2), acted_at=now - timedelta(hours=1),
        body="본문이에요", src="guide",
    )  # fmt: skip
    run(api, proactive.evaluate_due, now)
    (row,) = nudges(id=n["id"])
    assert row["status"] == "sent"  # 새 소식은 닫은 같은 종류 줄의 3일 쉬기에 걸리지 않는다
    again = add_nudge(
        uid, channel="feed", ref=ref, project_id=pid, dedup_key=n["dedup_key"] + ":notify"
    )
    run(api, proactive.evaluate_due, now)
    (row,) = nudges(id=again)
    assert (row["status"], row["reason"]) == ("held", "snooze")  # 무응답 다시 알림은 그대로 쉰다

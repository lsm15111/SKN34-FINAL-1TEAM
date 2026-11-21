"""먼저 말 걸기: 업체 · 고객이 한 일로 생긴 첫 알림은 24시간 감점을 받지 않는다(QA r2 c1 · c2 · x1).

견적서 · 추가 금액 · 기간 같은 새 소식이 앞서 보낸 줄 수(sent_count)로 40점 아래가 되어 보류되던 것을 막는다.
무응답 다시 알림(':notify')과 시간 트리거는 그대로 감점을 받는다. 유료 호출 0회."""

from datetime import timedelta
from types import SimpleNamespace

from app.assistant import proactive
from tests.test_v3_visit_kit import offered, quiet
from tests.test_v4_assistant_nudges import at, nudges, run, sent


def test_fresh_event_rule_by_trigger_and_key():
    offered_t = proactive.TRIGGERS["visit_offered"]
    eve = proactive.TRIGGERS["work_eve"]  # 시간 트리거(아웃박스 kind 없음)
    first = SimpleNamespace(dedup_key="visit_offered:abc")
    again = SimpleNamespace(dedup_key="visit_offered:abc:notify")
    assert proactive.fresh_event(offered_t, first) is True
    assert proactive.fresh_event(offered_t, again) is False  # 무응답 다시 알림은 감점 받음
    assert proactive.fresh_event(eve, first) is False


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

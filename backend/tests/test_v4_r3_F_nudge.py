"""고침 3차 F(먼저 말 걸기 · 알림 글, QA 3차 c1 · c2 · c4 · c6 · 2차 t1): 사건 알림은 판정 없이 보내고, 견적서가 여러 곳이면
이름 모두, 추가 금액은 금액, 업체가 올린 날짜는 시작일 · 고객 요청의 답인지, 공사 전날 · 1주 전 글은 붙은 카드와 맞게,
카드 기한은 끝나는 날로, worker 시작 때 SDK 준비, 업체 공사 날짜 후보는 열린 다른 날짜 카드가 잡은 날을 피한다.
유료 호출 0회(LLM 꺼짐 · Claude 대본)."""

import asyncio
import json
import uuid
from datetime import date, datetime
from functools import partial

import anthropic  # noqa: F401 - 첫 Claude 대본 호출의 늦은 SDK import가 판정 · 문장 10초 제한을 넘지 않게
import pytest
from v3_kb import repo_index

from app import worker
from app.agent import llm
from app.assistant import actions, proactive
from app.assistant.tools import cards
from app.assistant.tools import vendor as vendor_tools
from app.calc.common import from_entered
from app.db import SessionLocal
from app.shared.clock import SEOUL
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose
from tests.test_dates import ready as dates_ready
from tests.test_deal import setup
from tests.test_extras import scheduled
from tests.test_v3_visit_kit import quiet
from tests.test_v4_assistant_actions import approve
from tests.test_v4_assistant_aftercare import post_extra, tick
from tests.test_v4_assistant_nudges import at, nudges, run
from tests.test_v4_vendor_jobs import second_deal
from tests.test_visit_inbox import login


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


def write(api, f: proactive.Facts) -> tuple[str, str]:
    return api.portal.call(partial(proactive.write, f, None))


# ---- 사건 알림: 판정 없이 · 여러 곳 이름(리드 결정 1, c1 P4 · c2 · c4) ----


def test_quote_lines_skip_the_judge_and_name_every_vendor(api, monkeypatch, script):
    quiet(monkeypatch)
    customer, _pid, _va, _vb, _vc = setup(api)  # 마루와벽 · 결도배가 견적서를 보냄
    use(api, customer)
    query("delete from notifications where kind <> 'quote_sent'")
    query("update notifications set read_at = now()")  # 같은 알림 읽음 −30: 전에는 기록만 · 판정
    log = script([{"json": {"send": False}}, {"json": {"send": False}}])  # 판정을 부르면 '안 보냄'
    tick(api)
    rows = nudges(trigger="quote_sent")
    assert len(rows) == 2
    (shown,) = [n for n in rows if n["status"] == "sent"]
    assert [n["reason"] for n in rows if n["status"] != "sent"] == ["replaced"]  # 한 줄로 합침
    # 대본 '안 보냄'은 문장 자리로 갔다(꼴이 틀려 틀): 판정을 부르지 않았다
    assert shown["score"] < proactive.SEND_AT and shown["src"] == "guide"
    assert shown["body"] == "마루와벽 · 결도배에서 실측 견적서가 왔어요. 받은 견적서를 견줘 볼까요?"
    assert not [x for x in log if "판정기" in json.dumps(x.get("system"), ensure_ascii=False)]
    card = json.loads(shown["card"]) if isinstance(shown["card"], str) else shown["card"]
    assert card["kind"] == "quote_compare" and len(card["data"]["cols"]) >= 2


def test_news_is_only_the_first_event_of_the_five():
    t = proactive.TRIGGERS
    first, again = (
        type("N", (), {"dedup_key": "ev:abc"})(),
        type("N", (), {"dedup_key": "ev:abc:notify"})(),
    )
    for name in ("quote_sent", "dates_proposed", "extra_added", "vendor_out", "work_done"):
        assert proactive.news(t[name], first) and not proactive.news(t[name], again), name
    for name in ("visit_offered", "work_eve", "prep_week", "no_pick", "deal_confirmed"):
        assert not proactive.news(t[name], first), name  # 판정 · 점수 그대로


def test_ai_line_must_name_every_quoted_vendor(api, script):
    names = {"vendor": "결도배", "quoted": "마루와벽 · 결도배"}
    f = proactive.Facts("quote_sent", "feed", "customer", names=names)
    script([{"json": {"text": "결도배에서 실측 견적서가 왔어요! 견줘 볼까요?"}}])
    assert write(api, f) == (proactive.template(f), "guide")
    assert (
        proactive.template(f)
        == "마루와벽 · 결도배에서 실측 견적서가 왔어요. 받은 견적서를 견줘 볼까요?"
    )
    script([{"json": {"text": "마루와벽 · 결도배 견적서가 모두 왔어요! 견줘 볼까요?"}}])
    assert write(api, f) == ("마루와벽 · 결도배 견적서가 모두 왔어요! 견줘 볼까요?", "ai")
    one = proactive.Facts("quote_sent", "feed", "customer", names={"vendor": "결도배"})
    assert proactive.template(one) == "결도배가 실측 견적서를 보냈어요. 받은 견적서를 견줘 볼까요?"


# ---- 추가 금액: 금액으로 서로 구분(2차 t1 N9 · N10) ----


def test_extra_lines_tell_amounts_apart(api, monkeypatch, script):
    quiet(monkeypatch)
    customer, _pid, did = scheduled(api)
    query("delete from notifications")
    amounts = (150_000, 80_000, 50_000)
    for amount in amounts:
        post_extra(api, did, amount)
    use(api, customer)
    tick(api)
    bodies = sorted(n["body"] for n in nudges(trigger="extra_added") if n["status"] == "sent")
    want = sorted(
        f"마루와벽이 추가 금액 {from_entered(a, 'excluded').total:,}원을 올렸어요. 금액을 확인해 주세요."
        for a in amounts
    )
    assert bodies == want and len(set(bodies)) == 3
    # 무응답 다시 알림도 금액으로 구분 · '아직 답을 기다려요'
    f = proactive.Facts(
        "extra_added", "notify", "customer", names={"vendor": "결도배", "won": "165,000"}
    )
    assert proactive.template(f) == "결도배가 올린 추가 금액 165,000원이 아직 답을 기다려요."
    feed = proactive.Facts(
        "extra_added", "feed", "customer", names={"vendor": "결도배", "won": "165,000"}
    )
    script([{"json": {"text": "결도배가 추가 금액을 올렸어요. 금액부터 볼까요?"}}])
    assert write(api, feed) == (proactive.template(feed), "guide")  # 금액을 빠뜨린 AI 글은 틀
    script([{"json": {"text": "결도배가 추가 금액 165,000원을 올렸어요. 금액부터 볼까요?"}}])
    assert write(api, feed)[1] == "ai"


# ---- 업체가 올린 날짜: 시작일 · 고객 요청의 답(c4 #24) ----


def test_dates_lines_say_the_start_and_answer_to_the_request(api, monkeypatch):
    quiet(monkeypatch)
    customer, pid, did, _ = dates_ready(api)
    start = days(14)[0]
    assert propose(api, did, *days(14)).status_code == 200
    use(api, customer)
    query("delete from notifications where kind <> 'dates_proposed'")
    tick(api)
    (n,) = nudges(trigger="dates_proposed")
    ko = proactive._ko_day(date.fromisoformat(start))
    assert n["body"] == f"마루와벽이 공사 날짜를 {ko}부터로 올렸어요. 확인하고 수락해 주세요."
    # 수락한 뒤 고객이 날짜 바꾸기를 요청 → 업체가 답한 날짜: 요청의 답이라고
    x = query("select id from date_proposals where status = 'pending'")[0]["id"]
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json={"seen_version": 0})
    assert r.status_code == 200, r.text
    w1 = days(35, 1)[0]
    body = {"wish_dates": [w1], "reason": "이사 날짜가 바뀌었어요."}
    assert api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body).status_code == 201
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'dates_requested'")
    tick(api)  # 업체 줄(dates_requested) + 고객이 고른 날로 날짜 보내기 승인 카드
    (v,) = nudges(trigger="dates_requested")
    login(api, "maru@mitjip.test")
    r = approve(api, str(v["action_id"]), prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    (p,) = query("select kind, request_id from date_proposals where status = 'pending'")
    assert p["kind"] == "change" and p["request_id"] is not None
    use(api, customer)
    tick(api)
    (n,) = nudges(trigger="dates_proposed")
    ko = proactive._ko_day(date.fromisoformat(w1))
    assert (
        n["body"]
        == f"요청하신 날짜 바꾸기에 마루와벽이 {ko}부터로 답했어요. 확인하고 수락해 주세요."
    )


def test_dates_templates_for_vendor_change_and_ai_check(api, script):
    names = {
        "vendor": "마루와벽",
        "start": "3월 2일(화)",
        "change": "업체가 공사 날짜를 바꾸자고 함",
    }
    f = proactive.Facts("dates_proposed", "feed", "customer", names=names)
    assert (
        proactive.template(f)
        == "마루와벽이 공사 날짜를 3월 2일(화)부터로 바꾸자고 했어요. 확인해 주세요."
    )
    asked = {"vendor": "마루와벽", "start": "3월 2일(화)", "asked": "다른 날짜"}
    g = proactive.Facts("dates_proposed", "feed", "customer", names=asked)
    want = "요청하신 다른 날짜에 마루와벽이 3월 2일(화)부터로 답했어요. 확인하고 수락해 주세요."
    assert proactive.template(g) == want
    script([{"json": {"text": "마루와벽이 3월 2일(화)로 공사 날짜를 올렸어요. 확인해 주세요."}}])
    assert write(api, g) == (want, "guide")  # 요청의 답이라는 말이 없으면 틀
    script(
        [{"json": {"text": "요청하신 날짜에 마루와벽이 3월 2일(화)로 답했어요. 확인해 주세요."}}]
    )
    assert write(api, g)[1] == "ai"
    for t in proactive.TRIGGERS.values():  # 더 쓰는 틀도 60자 · '요' 끝(긴 이름 · 날짜로)
        for ch, keys, raw in t.more:
            long = {k: "가나다라마바사아자" for k in keys} | {"vendor": "믿집시험도배인테리어"}
            text = proactive.template(proactive.Facts(t.name, ch, t.surface, names=long))
            assert len(text) <= proactive.TEMPLATE_MAX and text.endswith(("요.", "요?")), text


# ---- 공사 1주 전 · 전날: 글이 붙은 카드와 맞게(2차 t1 N6 · N7) ----


def test_eve_and_week_lines_match_the_card(api, script):
    eve = proactive.Facts("work_eve", "notify", "customer", names={"trade": "도배"})
    script([{"json": {"text": "내일 도배 공사가 시작돼요. 업체 일정을 한 번 확인해 보실래요?"}}])
    assert write(api, eve) == ("내일 도배 공사가 시작돼요. 준비물을 챙겨 주세요.", "guide")
    script([{"json": {"text": "내일 도배 공사가 시작돼요! 준비물만 챙겨 볼까요?"}}])
    assert write(api, eve)[1] == "ai"
    week = proactive.Facts("prep_week", "feed", "customer", names={"trade": "도배"})
    script([{"json": {"text": "도배 공사가 일주일 남았어요. 대화에서 한번 확인해 보실래요?"}}])
    text, src = write(api, week)
    assert src == "guide" and "이웃 안내문 초안" in text
    script([{"json": {"text": "도배 공사가 일주일 남았어요. 공사 전 할 일을 챙겨 볼까요?"}}])
    assert write(api, week)[1] == "ai"
    assert "이웃 안내문" in proactive.STEPS["prep_week"][1]


# ---- 카드 기한은 끝나는 날로(c4 #16 '12월 22일까지') ----


def test_midnight_deadline_reads_as_the_day_it_ends():
    assert cards.seoul_text(datetime(2026, 12, 22, 0, 0, tzinfo=SEOUL)) == "12월 21일(월) 밤 12시"
    assert cards.seoul_text(datetime(2026, 12, 22, 18, 0, tzinfo=SEOUL)) == "12월 22일(화) 오후 6시"
    # 0시 정각(기한 끝)만 본다. 0시대 나머지(0시 30분 …)는 K 판 seoul_text가 정한다
    now = datetime(2026, 11, 22, 10, 0, tzinfo=SEOUL)
    expiry = actions.confirm_expiry(date(2026, 12, 21), now)  # 유효기간 12.21 견적서 확정 카드
    assert cards.seoul_text(expiry) == "12월 21일(월) 밤 12시"


# ---- worker 시작 때 SDK 준비(N 남김) ----


def test_worker_startup_warms_the_sdk(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(llm, "warm", lambda: called.append("warm"))
    assert worker.WorkerSettings.on_startup is worker.startup
    asyncio.run(worker.startup({}))
    assert called == ["warm"]

    def boom():
        raise RuntimeError("import 실패")

    monkeypatch.setattr(llm, "warm", boom)
    asyncio.run(worker.startup({}))  # 준비 실패로 worker 시작을 막지 않는다


# ---- 업체: 열린 다른 공사 날짜 카드가 잡은 날은 후보에서 뺀다(c6) ----


def test_open_date_card_days_are_not_offered_to_the_next_job(api, monkeypatch):
    quiet(monkeypatch)
    _, _, did, _ = dates_ready(api)
    _, did2 = second_deal(api)  # 같은 업체(마루와벽)의 두 번째 확정 공사
    now = at(14)
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    rows = query(
        "select ref_id, action_id from assistant_nudges where trigger = 'deal_confirmed'"
        " and status = 'sent'"
    )
    assert len(rows) == 2 and all(r["action_id"] for r in rows)
    picked = {}
    for r in rows:
        (a,) = query("select payload from assistant_actions where id = $1", r["action_id"])
        picked[str(r["ref_id"])] = {date.fromisoformat(x) for x in json.loads(a["payload"])["days"]}
    assert picked[did] and picked[did2] and not picked[did] & picked[did2], picked
    vendor_user = query("select id from users where email = 'maru@mitjip.test'")[0]["id"]

    async def held(deal: str):
        async with SessionLocal() as s:
            return await vendor_tools.held_days(s, vendor_user, uuid.UUID(deal), now)

    assert api.portal.call(partial(held, did2)) == frozenset(picked[did])  # 자기 카드는 빼고 센다
    # 업체가 그 카드를 누르면(보낸 날) 바쁜 날로 넘어가고, 열린 카드 날은 더 세지 않는다
    (first,) = [r for r in rows if str(r["ref_id"]) == did]
    login(api, "maru@mitjip.test")
    r = approve(api, str(first["action_id"]), prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    assert api.portal.call(partial(held, did2)) == frozenset()
    assert set(api.get(f"/vendor/jobs/{did2}").json()["busy_days"]) == {
        d.isoformat() for d in picked[did]
    }

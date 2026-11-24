"""점검 고침 X2(기억 · 한 일 말 · 이름표, 2026-11-24). 보고 R1b #1 · #2 · #8 · #9 · #10 · #13 · #17, R1a B1 · B3 ·
B4 · B6 · B7을 재현 그대로 고정한다. 유료 호출 0회(무료 모드 · Claude 대본)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import get_args

import pytest
from redis.exceptions import ConnectionError as RedisDown
from sqlalchemy.exc import OperationalError
from v3_kb import repo_index

from app.agent import llm
from app.agent.v3 import check
from app.assistant import memory, proactive, prompts, runtime
from app.assistant import service as assistant_service
from app.assistant.memory import Item
from app.assistant.runtime import RefTable, claims_done
from app.assistant.schemas import CardKind
from app.shared.clock import now_utc, today_seoul
from tests.conftest import query
from tests.helpers import use
from tests.test_extras import scheduled as built
from tests.test_v3_visit_kit import quiet
from tests.test_v4_assistant_aftercare import deal_job, line, tick, worked
from tests.test_v4_assistant_nudges import add_nudge, at, nudges, offered_nudge, run
from tests.test_v4_assistant_offers import scheduled
from tests.test_v4_assistant_turns import ask, home, ok


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


def sweep(api) -> None:
    from app import worker

    api.portal.call(partial(worker.sweep, datetime.now(UTC)))


def remember(api, pid: str, text: str, items: list[dict]) -> None:
    """고객 말 한 턴(무료 모드) 뒤 기억 뽑기 일을 대본 답으로 돌린다."""
    query("delete from jobs")
    llm.clear_stubs()
    assert ok(ask(api, pid, text))[-1][0] == "done"
    llm.set_claude_script([{"json": {"items": items}}])
    sweep(api)
    llm.clear_stubs()


def mem() -> dict[str, dict]:
    return {r["key"]: dict(r) for r in query("select * from assistant_memory")}


def it(key: str, value: str, quote: str) -> Item:
    return Item(key=key, value=value, evidence_quote=quote)


def said(key: str, value: str, quote: str) -> dict:
    return {"key": key, "value": value, "evidence_quote": quote}


# ---- R1b #1: 한글 수 · 단위로 말한 금액 ----


@pytest.mark.parametrize(
    ("msg", "value"),
    [
        ("3백만 원 안쪽으로 하는 게 제일 중요해요", "3백만 원 안쪽"),
        ("삼백만 원 넘지 않게 하는 게 중요해요", "삼백만 원 넘지 않게"),
        ("백만원대로 맞추는 게 우선이에요", "백만원대"),
        ("평당 만오천원 넘으면 안 돼요 그게 중요해요", "평당 만오천원"),
        ("천만 원 밑으로 끝내는 게 우선이에요", "천만 원 밑으로"),
        ("삼백 안쪽이면 좋겠어요 그게 중요해요", "삼백 안쪽"),
        ("몇십만 원 차이면 품질이 중요해요", "몇십만 원 차이면 품질"),
    ],
)
def test_money_in_korean_numbers_is_not_remembered(msg, value):
    why: list[str] = []
    assert memory.validate([it("priority", value, msg)], msg, why) == []
    assert why == ["priority:money"]


@pytest.mark.parametrize(
    ("key", "value", "msg"),
    [
        ("style", "천장은 밝은 느낌", "천장은 밝은 느낌이 좋아요"),
        ("priority", "꼼꼼한 마감", "천천히 해도 꼼꼼한 마감이 중요해요"),
        ("priority", "만족스러운 마감", "만족스러운 마감이 제일 중요해요"),
        ("material", "암막 커튼", "안방은 암막 커튼 달 거라 벽지는 밝게"),
        ("style", "화강암 느낌", "화강암 느낌 나는 벽지가 좋아요"),
        ("move_in", "12월 말 이사", "12월 말 이사라서 그 전에 끝나야 해요"),
    ],
)
def test_everyday_words_near_money_and_health_are_kept(key, value, msg):
    (got,) = memory.validate([it(key, value, msg)], msg)
    assert (got.value, got.evidence_quote) == (value, msg)


# ---- R1b #2: 건강 말(조사 붙은 '암' · 기관지 · 우울증 …) ----


@pytest.mark.parametrize(
    ("msg", "key", "value"),
    [
        ("엄마가 암이라 냄새 안 나는 친환경 벽지가 중요해요", "priority", "친환경"),
        ("아이가 기관지가 약해서 친환경 자재가 중요해요", "priority", "친환경 자재"),
        ("남편이 허리 디스크라 공사 빨리 끝나는 게 중요해요", "priority", "빨리 끝나는 게"),
        ("우울증 때문에 밝은 느낌이 좋아요", "style", "밝은 느낌"),
        ("아버지가 폐암이라 먼지 안 나는 게 중요해요", "priority", "먼지 안 나는 게"),
        ("엄마가 무릎이 안 좋아서 문턱 없는 게 중요해요", "priority", "문턱 없는 게"),
    ],
)
def test_health_words_never_stay_in_the_saved_quote(msg, key, value):
    (got,) = memory.validate([it(key, value, msg)], msg)
    assert (got.value, got.evidence_quote) == (value, value)  # 근거 인용도 값으로 줄여요


@pytest.mark.parametrize(
    ("value", "msg"),
    [
        ("암 환자라 친환경", "엄마가 암 환자라 친환경이 중요해요"),
        ("기관지 때문에 친환경", "아이 기관지 때문에 친환경이 중요해요"),
        ("우울증 때문에 밝은 느낌", "우울증 때문에 밝은 느낌이 좋아요"),
    ],
)
def test_health_words_in_the_value_drop_the_memory(value, msg):
    why: list[str] = []
    assert memory.validate([it("priority", value, msg)], msg, why) == []
    assert why == ["priority:health"]


def test_money_and_health_said_in_turns_are_not_saved_or_shown(api):
    _, pid = home(api)
    money = "3백만 원 안쪽으로 하는 게 제일 중요해요"
    remember(api, pid, money, [said("priority", "3백만 원 안쪽", money)])
    assert "priority" not in mem()
    health = "엄마가 암이라 냄새 안 나는 친환경 벽지가 중요해요"
    remember(api, pid, health, [said("priority", "친환경", health)])
    (shown,) = [m for m in api.get("/assistant/memory").json() if m["key"] == "priority"]
    assert (shown["value"], shown["evidence_quote"]) == ("친환경", "친환경")


# ---- R1b #8 · #9: 지운 기억 · 나중 말 지키기 ----


def test_deleted_memory_does_not_come_back_from_a_deferred_job(api):
    _, pid = home(api)
    remember(api, pid, "주말이 편해요", [said("avail_days", "주말", "주말이 편해요")])
    old = mem()["avail_days"]
    query("delete from jobs")
    ok(ask(api, pid, "토요일이 좋아요"))  # LLM 꺼짐: 기억 뽑기를 뒤로 미뤄요
    sweep(api)
    assert query("select 1 from jobs where dedup_key like '%:later%' and status = 'pending'")
    assert api.delete(f"/assistant/memory/{old['id']}").status_code == 204
    query("update jobs set run_at = now() - interval '1 minute' where dedup_key like '%:later%'")
    llm.set_claude_script([{"json": {"items": [said("avail_days", "토요일", "토요일이 좋아요")]}}])
    sweep(api)
    llm.clear_stubs()
    assert "avail_days" not in mem()  # 지우기 전에 한 말로 다시 생기지 않아요
    # 지운 뒤에 한 새 말은 기억해요
    remember(api, pid, "일요일이 편해요", [said("avail_days", "일요일", "일요일이 편해요")])
    assert mem()["avail_days"]["value"] == "일요일"


def test_retried_old_words_do_not_overwrite_newer_memory(api):
    _, pid = home(api)
    query("delete from jobs")
    ok(ask(api, pid, "평일 오전이 편해요"))  # M1
    ok(ask(api, pid, "아 주말이 더 편해요"))  # M2(나중 말)
    m2 = said("avail_days", "주말", "아 주말이 더 편해요")
    llm.set_claude_script([llm.LLMError("일시 오류"), {"json": {"items": [m2]}}])
    sweep(api)  # M1: 공급자 일시 오류 → 같은 줄을 다시 해요 · M2: 주말 저장
    llm.clear_stubs()
    assert mem()["avail_days"]["value"] == "주말"
    query(
        "update jobs set run_at = now() - interval '1 minute'"
        " where kind = 'assistant_memory' and status = 'pending'"
    )
    m1 = said("avail_days", "평일", "평일 오전이 편해요")
    llm.set_claude_script([{"json": {"items": [m1]}}])
    sweep(api)
    llm.clear_stubs()
    assert mem()["avail_days"]["value"] == "주말"  # 옛 말이 나중 말을 덮지 않아요


def test_two_words_in_one_sweep_keep_the_later_one(api):
    """같은 차례에 앞 말 · 뒤 말을 차례로 뽑아도 뒤 말이 남아요(저장한 때가 아니라 말한 때로 견줘요)."""
    _, pid = home(api)
    query("delete from jobs")
    ok(ask(api, pid, "평일 오전이 편해요"))
    ok(ask(api, pid, "아 주말이 더 편해요"))
    llm.set_claude_script(
        [
            {"json": {"items": [said("avail_days", "평일", "평일 오전이 편해요")]}},
            {"json": {"items": [said("avail_days", "주말", "아 주말이 더 편해요")]}},
        ]
    )
    sweep(api)
    llm.clear_stubs()
    assert mem()["avail_days"]["value"] == "주말"


# ---- R1b #10: 기한 · 날이 지나 닫은 줄은 '완료'가 아니에요 ----


def feed_line(api, pid: str, nid) -> dict | None:
    items = api.get("/assistant/feed", params={"project_id": pid}).json()["items"]
    return next((x for x in items if x["id"] == f"n-{nid}"), None)


def test_pick_deadline_passed_line_is_lapsed_not_done(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    # 고객이 고르지 않아 고르기 기한이 지남(visit.jobs와 같은 값)
    query(
        "update visits set status = 'expired', expired_reason = 'pick' where id = $1::uuid",
        f["visit"],
    )
    assert run(api, proactive.close_settled, now_utc()) == 1
    assert line(n["id"]) == ("expired", "lapsed")
    got = feed_line(api, f["pid"], n["id"])
    assert got is None or not got["settled"]  # 대화 기록에 '완료'로 보이지 않아요


def test_sweep_closes_the_lapsed_line_of_an_open_slot_card_as_lapsed(api, monkeypatch):
    """반나절 승인 카드가 열린 채 요청 기한이 지나면 정리(화면 처리 닫기)가 줄도 닫아요: '지남'이지 '완료'가 아니에요."""
    f, n = offered_nudge(api, monkeypatch)
    query(
        "update visits set status = 'expired', expired_reason = 'pick' where id = $1::uuid",
        f["visit"],
    )
    run(api, assistant_service.sweep, now_utc())
    assert line(n["id"]) == ("expired", "lapsed")
    got = feed_line(api, f["pid"], n["id"])
    assert got is None or not got["settled"]


def test_work_day_and_week_lines_lapse_when_the_day_comes(api):
    _t, pid, did = scheduled(api)
    uid = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    shown = {
        "status": "sent",
        "src": "guide",
        "project_id": uuid.UUID(pid),
        "ref": uuid.UUID(did),
        "sent_at": now_utc() - timedelta(days=1),
    }
    today = today_seoul()

    def start_on(day) -> None:
        query(
            "update deals set start_date = $1, end_date = $2 where id = $3::uuid",
            day,
            day + timedelta(days=2),
            did,
        )

    # 공사 날짜를 뒤로 옮겼다(사람이 한 일): 공사 전날 줄은 할 일이 끝나 닫혀요
    moved = add_nudge(uid, trigger="work_eve", body="내일 도배 공사가 시작돼요.", **shown)
    start_on(today + timedelta(days=5))
    run(api, proactive.close_settled, now_utc())
    assert line(moved) == ("expired", "handled")
    # 공사 날이 왔다: 공사 전날 · 1주 전 줄은 날이 지나 닫혀요
    eve = add_nudge(uid, trigger="work_eve", body="내일 도배 공사가 시작돼요.", **shown)
    week = add_nudge(
        uid,
        trigger="prep_week",
        channel="feed",
        body="도배 공사가 일주일 남았어요.",
        dedup_key=f"prep_week:{did}:{today.isoformat()}",
        **shown,
    )
    start_on(today)
    run(api, proactive.close_settled, now_utc())
    assert line(eve) == ("expired", "lapsed") and line(week) == ("expired", "lapsed")


# ---- R1b #13: 공사 1주 전 줄은 남은 날을 그대로 ----


@pytest.mark.parametrize(("days", "left"), [(4, "4일"), (7, "일주일")])
def test_prep_week_line_says_the_days_left(api, monkeypatch, days, left):
    quiet(monkeypatch)
    _t, _pid, did = scheduled(api)
    start = today_seoul() + timedelta(days=days)
    query(
        "update deals set start_date = $1, end_date = $2 where id = $3::uuid",
        start,
        start + timedelta(days=2),
        did,
    )
    now = at(14)
    run(api, proactive.scan_time, now)
    run(api, proactive.evaluate_due, now)
    (n,) = nudges(trigger="prep_week")
    assert n["status"] == "sent"
    assert n["body"] == f"도배 공사가 {left} 남았어요. 미리 할 일과 이웃 안내문 초안을 준비했어요."


# ---- R1b #17: 이미 울린 공사 끝 알림 줄은 종 알림으로 세지 않아요 ----


def test_done_remind_line_adds_no_bell_and_is_not_held_for_the_night(api, monkeypatch):
    quiet(monkeypatch)
    customer, _pid, did = built(api)
    worked()
    query("delete from notifications")
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer)
    tick(api)
    (first,) = nudges(trigger="work_done")
    query(
        "update assistant_nudges set sent_at = sent_at - interval '4 days' where id = $1",
        first["id"],
    )
    (deal,) = query("select done_posted_at from deals where id = $1", uuid.UUID(did))
    run(
        api,
        deal_job("deal_done_remind", did, deal["done_posted_at"] + timedelta(days=4, minutes=1)),
    )
    tick(api, 22)  # 밤 10시: 종 알림 줄이면 아침으로 미뤄요
    (remind,) = [x for x in nudges(trigger="work_done") if x["id"] != first["id"]]
    # 시스템 done_remind 알림이 이미 울렸어요: 비서는 종 없이 대화 줄로(하루 알림 상한 · 밤에 세지 않아요)
    assert (remind["status"], remind["channel"]) == ("sent", "feed")
    assert remind["body"] == "마루와벽 공사가 곧 자동으로 끝나요. 점검표로 확인해 주세요."
    assert not query("select 1 from notifications where kind = 'assistant_nudge'")


# ---- R1a B1: 승인 전 '취소해 드렸어요' · '보내 놨어요' ----

ALLOWED = """지금: 11월 24일(화) 오후 3시
업체: 결도배(m1) 견적서 옴(1판 · 부가세 포함 3,520,000원)
공정표: 예상 공정표 · 예상 공사 12월 14일(월)~16일(수) · 일하는 날 3일
집: 노원구 · 32평형(공급) · 방 3개"""

CLAIMED = [
    "실측 요청을 취소해 드렸어요.",
    "결도배에 보낸 실측 요청은 취소했어요.",
    "요청 보내 놨어요.",
    "공사 날짜 수락 끝냈어요.",
    "결도배 실측 예약 잡아 뒀어요.",
    "취소 처리해 놨어요.",
]


@pytest.mark.parametrize("text", CLAIMED)
def test_claims_of_cancel_and_done_forms_are_caught(text):
    assert claims_done(text)


@pytest.mark.parametrize(
    "text",
    [
        "12월 14일(월) 시작으로 넣었어요.",  # 카드에 넣었어요(시험 test_v4_r3_a2_gate)
        "업체가 실측 요청을 취소했어요.",  # 다른 사람이 한 일
        "결도배가 공사를 끝냈어요.",
        "취소하려면 카드에서 눌러 주세요.",
        "취소 카드를 만들었어요. 확인하고 눌러 주세요.",
    ],
)
def test_card_words_and_others_deeds_still_pass(text):
    assert not claims_done(text)


def test_gate_does_not_send_cancel_claims_before_approval():
    sent: list[str] = []

    async def emit(_name, data):
        sent.append(data.get("text", ""))

    async def go(text: str) -> str:
        sent.clear()
        g = runtime.SentenceGate(emit, prompts.rules("customer"), ALLOWED)
        await g.feed(text + " ")
        await g.flush()
        await g.settle()
        return "".join(sent).strip()

    for text in CLAIMED:
        assert asyncio.run(go(text)) == "", text
    assert asyncio.run(go("12월 14일(월) 시작으로 넣었어요.")) == "12월 14일(월) 시작으로 넣었어요."


def test_v3_check_catches_ai_cancel_and_accept():
    assert check.AI_ACTS.search("제가 실측 요청을 취소해 드렸어요.")
    assert check.AI_ACTS.search("공사 날짜는 수락해 놨어요.")
    assert not check.AI_ACTS.search("취소는 카드에서 눌러야 해요.")


# ---- R1a B3: 이름표 표가 차면 오래 안 쓴 것부터 ----


def slot(day: str) -> dict:
    return {"visit_id": "v-1", "day": day, "half": "am"}


def test_reused_ref_moves_back_and_is_not_dropped_first():
    t = RefTable(uuid.uuid4())
    m1 = t.put("visit", {"id": "v-1"})
    slots = [t.put("slot", slot(f"d{i}")) for i in range(RefTable.MAX - 1)]
    assert len(t.items) == RefTable.MAX
    assert t.put("visit", {"id": "v-1"}) == m1  # 턴마다 다시 넣는 이름표(턴 사실 · 업체 요청)
    t.put("slot", slot("new"))
    assert t.known(m1) and not t.known(slots[0])


def test_merge_keeps_the_ref_put_again_this_turn():
    theirs = {"m1": {"kind": "visit", "id": "v-1"}}
    theirs |= {f"s{i}": {"kind": "slot", **slot(f"d{i}")} for i in range(1, RefTable.MAX)}
    t = RefTable(uuid.uuid4(), items=dict(theirs), top={"m": 1, "s": RefTable.MAX - 1})
    assert t.put("visit", {"id": "v-1"}) == "m1"
    new = t.put("slot", slot("new"))
    items, _ = t.merged(theirs, {}, {})
    assert len(items) == RefTable.MAX
    assert "m1" in items and new in items and "s1" not in items


# ---- R1a B4: 첫 저장이 Redis 오류면 둘째 저장이 새 이름표를 버림 ----


def test_second_save_keeps_new_refs_after_the_first_save_failed(api):
    from app import queue

    _, pid = home(api)
    chat = uuid.UUID(ok(ask(api, pid, "안녕하세요"))[0][1]["chat_id"])

    def down(*_a, **_k):
        raise RedisDown("down")

    async def go():
        t = await RefTable.load(chat)
        ref = t.put("visit", {"id": str(uuid.uuid4())})
        queue.redis.pipeline = down  # 첫 저장: DB 번호는 올리고 Redis만 실패
        try:
            await t.save()
        finally:
            del queue.redis.pipeline
        await t.save()  # 턴 끝 저장(finish_turn 뒤)
        return ref, await RefTable.load(chat)

    ref, keep = run(api, go)
    assert keep.known(ref)


# ---- R1a B6: 저장에 실패한 턴이 다음 턴 글을 가져감 ----


def test_failed_save_turn_does_not_take_the_next_turn_text(api, monkeypatch):
    from app.chat import repository as chat_repo

    _, pid = home(api)
    real = chat_repo.bump_rev
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("bump_rev", {}, Exception("db down"))
        return await real(*a, **k)

    monkeypatch.setattr(chat_repo, "bump_rev", flaky)
    first = ok(ask(api, pid, "오늘 뭐 하면 돼요?"))
    assert first[-1][0] == "error"
    second = ok(ask(api, pid, "도배는 며칠 걸려요?"))
    assert second[-1][0] == "done"
    failed_id, done_id = first[0][1]["turn_id"], second[0][1]["turn_id"]
    failed = api.get(f"/assistant/turns/{failed_id}").json()
    done = api.get(f"/assistant/turns/{done_id}").json()
    assert failed["status"] == "failed" and failed["text"] is None
    assert done["text"]
    items = api.get("/assistant/feed", params={"project_id": pid}).json()["items"]
    answers = [x for x in items if x["role"] == "assistant" and x.get("turn_id")]
    assert answers and all(x["turn_id"] == done_id for x in answers)


# ---- R1a B7: 카드 이름 표 ----

NEW_NAMES = {"extra", "grade_compare", "market_range", "notice", "options", "product_estimate"}


def test_every_card_kind_has_a_screen_name():
    assert set(get_args(CardKind)) <= set(runtime.CARD_NAME)
    assert runtime.STEP_CARDS.isdisjoint(NEW_NAMES | {"research"})  # 다음 일 카드 묶음은 그대로

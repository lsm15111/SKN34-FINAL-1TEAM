"""v4 비서 카드 상태 고침(QA r1 · edge, 갈래 D1): 다른 종류 카드끼리 바꾸지 않기(직접 할 일 ↔ 실측 요청) · 먼저 말
걸기 카드 다시 만들기(멱등 키 · 기한 지난 행) · 실행 중 commit 순서(mark 앞에서 미리 맞추기) · 직접 할 일 칩 판 ·
칩 저장 잠금 · 닫힌 까닭 문구 · 거절한 카드를 분명히 다시 부탁 · 추천에서 요청한 업체 빼기 · 카드 글 날짜.
유료 호출 0회(Claude 대본 · 무료 모드)."""

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions
from app.assistant import repository as repo
from app.assistant import service as assistant_service
from app.assistant.schemas import ActionSummary
from app.assistant.tools import cards, propose
from app.auth.models import User
from app.db import SessionLocal
from app.project import diy
from app.shared.clock import SEOUL, now_utc, today_seoul
from app.v2 import guard
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import SEEN0, days
from tests.test_dates import propose as post_dates
from tests.test_dates import ready as dates_ready
from tests.test_extras import scheduled
from tests.test_v3_visit_kit import add, handle, quiet, requested, vendor, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import action_row, acts, approve, code, propose_home
from tests.test_v4_assistant_aftercare import action, deal_job, line, tick, worked
from tests.test_v4_assistant_free import cards_of
from tests.test_v4_assistant_nudges import nudges, run
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")  # 고객 화면 글에 나가면 안 되는 날짜 꼴


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


def sweep(api) -> dict:
    return run(api, assistant_service.sweep, now_utc())


def diy_keys() -> list[str]:
    rows = query("select key from project_conditions where key like 'diy.%' order by key")
    return [x["key"] for x in rows]


def tool_result(log, call: int) -> dict:
    """대본 log의 call번째 LLM 호출이 받은 마지막 도구 결과(모델에 간 값)."""
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


def user_of(email: str) -> uuid.UUID:
    return query("select id from users where email = $1", email)[0]["id"]


def picks_request(api, pid: str) -> dict:
    """무료 모드: 업체 추천 → 첫 업체 단추로 실측 요청 승인 카드(사람이 누른 고르기)."""
    llm.clear_stubs()
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    ref = picks["data"]["picks"][0]["ref"]
    ctx = {"card_id": picks["card_id"], "choice": f"visit_request:{ref}"}
    (req,) = [
        x
        for x in acts(ok(ask(api, pid, "여기에 요청할래요", context=ctx)))
        if x["status"] == "proposed"
    ]
    assert req["kind"] == "visit_request"
    return req


# ---- B2 · B1: 다른 종류 카드끼리 바꾸지 않기 ----


def test_diy_card_and_visit_request_card_stay_open_together(api, script, monkeypatch):
    """같은 공사의 직접 할 일 카드와 실측 요청 카드는 서로를 바꾸지 않는다(같은 종류 새 카드만 옛 카드를 바꾼다).
    요청한 뒤(잠김)에도 직접 할 일 카드는 정리가 닫지 않고 실행된다(B1)."""
    quiet(monkeypatch)
    vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    d1 = propose_home(api, script, pid, {"diy": ["paint"]})
    req = picks_request(api, pid)
    assert action_row(d1["action_id"])["status"] == "proposed"
    assert not ISO.search(json.dumps(req["summary"], ensure_ascii=False))  # #4 희망 기간
    d2 = propose_home(api, script, pid, {"diy": ["paint", "clean"]})
    assert action_row(d1["action_id"])["status"] == "expired"  # 같은 종류는 새 카드로 바뀐다
    assert action_row(req["action_id"])["status"] == "proposed"
    r = approve(api, req["action_id"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert sweep(api)["handled"] == 0
    r = approve(api, d2["action_id"], seen=d2["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert diy_keys() == ["diy.clean", "diy.paint"]


def test_diy_approval_leaves_the_vendor_out_line_and_its_card(api, script, monkeypatch):
    """업체 빠짐 줄의 실측 요청 카드는 직접 할 일 카드를 만들어도 그대로이고, 직접 할 일을 실행해도 그 줄을
    '완료'(acted)로 닫지 않는다(다른 업체를 잇지 않았다). 실행하면 그 카드는 같은 업체 · 같은 조건에 바뀐 직접 할
    일을 넣은 새 판으로 바뀐다(QA r3 s6 리드 결정 11-22, 예전 기대: 옛 카드 그대로)."""
    quiet(monkeypatch)
    maru = vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = home(api)
    assert add(api, pid, maru).status_code == 201
    assert ask_visits(api, pid, [maru]).status_code == 201
    login(api, "maru@mitjip.test")
    r = api.post(f"/vendor/visits/{visit_of(pid, maru)}/decline", json={"code": "full"})
    assert r.status_code == 200, r.text
    use(api, token)
    tick(api)
    (n,) = nudges(trigger="vendor_out")
    assert n["status"] == "sent" and action(n["action_id"])["kind"] == "visit_request"
    d = propose_home(api, script, pid, {"diy": ["clean"]})
    assert action(n["action_id"])["status"] == "proposed"
    r = approve(api, d["action_id"], seen=d["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert line(n["id"]) == ("sent", None)
    old = action(n["action_id"])
    assert (old["status"], old["result"]["reason"]) == ("expired", "replaced")
    new = action(old["result"]["replaced_by"])
    assert new["status"] == "proposed" and new["payload"]["diy"] == ["clean"]
    assert new["payload"]["vendor_ids"] == old["payload"]["vendor_ids"]


# ---- B5 · L4: 먼저 말 걸기 카드 멱등 키 ----


def test_remind_line_gets_a_new_card_after_the_first_one_expired(api, monkeypatch):
    """끝 확인 카드가 기한(3일)으로 닫힌 뒤 '곧 자동으로 끝나요' 알림 줄에도 승인 카드가 붙는다."""
    quiet(monkeypatch)
    customer_token, _pid, did = scheduled(api)
    worked()
    query("delete from notifications")
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer_token)
    tick(api)
    (n,) = nudges(trigger="work_done")
    first = n["action_id"]
    query(
        "update assistant_actions set created_at = now() - interval '4 days',"
        " expires_at = now() - interval '1 hour' where id = $1",
        first,
    )
    run(api, actions.expire_due, now_utc())  # 정리: 기한 지난 카드 → expired(due)
    query(
        "update assistant_nudges set sent_at = sent_at - interval '4 days' where id = $1", n["id"]
    )
    (deal,) = query("select done_posted_at from deals where id = $1", uuid.UUID(did))
    at = deal["done_posted_at"] + timedelta(days=4, minutes=1)
    run(api, deal_job("deal_done_remind", did, at))
    tick(api)
    (remind,) = [x for x in nudges(trigger="work_done") if x["channel"] == "notify"]
    assert remind["status"] == "sent" and remind["action_id"] not in (None, first)
    assert action(remind["action_id"])["status"] == "proposed"
    assert action(first)["status"] == "expired"
    r = approve(api, str(remind["action_id"]))
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text


def test_offer_does_not_reuse_an_idem_row_past_its_due(api):
    """같은 멱등 키의 행이 기한이 지났으면(정리 전 2분) 죽은 카드를 붙이지 않고 새로 만든다. 옛 행은 expired(due)."""
    _, pid = home(api)
    uid, p = user_of("home@mitjip.test"), uuid.UUID(pid)
    kw = {
        "surface": "customer",
        "kind": "home_info",
        "target_kind": "project",
        "target_id": p,
        "target_ver": "1",
        "payload": {"fields": {"rooms": 2}},
        "summary": ActionSummary(title="집 정보 저장", approve_label="맞아요, 저장"),
        "project_id": p,
        "turn_id": None,
        "origin": "nudge",
    }

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
            now = now_utc()
            a, _ = await actions.propose(
                s, user, now=now, expires_at=now + timedelta(hours=1), **kw
            )
            await s.commit()
            same, _ = await actions.propose(s, user, now=now, **kw)  # 열린 같은 행은 그대로 쓴다
            later = now + timedelta(hours=2)
            b, _ = await actions.propose(s, user, now=later, **kw)
            await s.commit()
            return a.id, same.id, b.id, b.status

    a, same, b, status = run(api, go)
    assert same == a and b != a and status == "proposed"
    row = action_row(str(a))
    assert row["status"] == "expired" and json.loads(row["result"]) == {"reason": "due"}


# ---- B6: 실행 중 commit이 mark(executed)를 먼저 확정하지 않기 ----


def test_accept_that_fails_after_plan_resave_is_failed_not_executed(api, script, monkeypatch):
    """예상 공정표가 낡은 때(배포로 계산식 판이 바뀜) 수락이 실패하면 행동은 failed이고 기능 오류 말을 남긴다."""
    from app.schedule import service as schedule_service

    quiet(monkeypatch)
    customer_token, pid, did, _ = dates_ready(api)
    assert post_dates(api, did, *days(10)).status_code == 200
    use(api, customer_token)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_dates_accept", "input": {"proposal_ref": "p1"}}
                ]
            },
            {"text": "수락 카드를 만들었어요."},
        ]
    )
    (c,) = [x for x in acts(ok(ask(api, pid, "공사 날짜 어때요?"))) if x["status"] == "proposed"]
    monkeypatch.setattr(schedule_service, "FORMULA_VERSION", "d1-test")
    query(
        "update date_proposals set start_date = $1 where status = 'pending'",
        today_seoul() - timedelta(days=1),
    )
    assert code(approve(api, c["action_id"])) == (409, "start_passed")
    row = action_row(c["action_id"])
    assert (row["status"], row["error_code"]) == ("failed", "start_passed")
    assert json.loads(row["result"])["message"].startswith("시작일이 지났어요.")  # R7
    assert query("select count(*) as n from date_proposals where status = 'pending'")[0]["n"] == 1
    assert code(approve(api, c["action_id"])) == (409, "action_closed")
    assert not ISO.search(c["summary"]["title"])  # #4


def test_vendor_dates_that_fail_after_plan_resave_are_failed_not_executed(api, script, monkeypatch):
    from app.schedule import service as schedule_service

    quiet(monkeypatch)
    customer_token, pid, did, _ = dates_ready(api)  # 업체(마루와벽)로 로그인해 있다
    script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "d",
                        "name": "propose_dates",
                        "input": {"deal_ref": "d1", "days_ref": "n1"},
                    }
                ]
            },
            {"text": "공사 날짜 카드를 만들었어요."},
        ]
    )
    r = api.post(
        "/vendor/assistant/turns", json={"client_key": uuid.uuid4().hex, "text": "날짜 보낼래요"}
    )
    (v,) = [x for x in acts(ok(r)) if x["status"] == "proposed"]
    assert v["kind"] == "dates"
    assert post_dates(api, did, *days(10)).status_code == 200  # 화면에서 직접 날짜를 보냄
    use(api, customer_token)
    xid = query("select id from date_proposals where status = 'pending'")[0]["id"]
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{xid}/accept", json=SEEN0)
    assert r.status_code == 200, r.text  # 고객이 화면에서 수락
    monkeypatch.setattr(schedule_service, "FORMULA_VERSION", "d1-test")
    login(api, "maru@mitjip.test")
    assert code(approve(api, v["action_id"], prefix="/vendor/assistant")) == (409, "invalid_state")
    row = action_row(v["action_id"])
    assert (row["status"], row["error_code"]) == ("failed", "invalid_state")
    assert not ISO.search(v["summary"]["title"])  # #4


def test_visit_again_that_fails_after_standard_resave_is_failed_not_executed(api, monkeypatch):
    from app.quote import service as quote_service

    quiet(monkeypatch)
    llm.clear_stubs()  # 무료 모드
    f = requested(api)
    due = query("select reply_due_at from visits where id = $1", uuid.UUID(f["visit"]))[0]
    handle("visit_reply_due", f["visit"], due["reply_due_at"] + timedelta(minutes=1))
    use(api, f["token"])
    ev = ok(ask(api, f["pid"], "마루와벽에 한 번 더 요청해 주세요"))
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_again" and x["status"] == "proposed"]
    assert api.post(f"/projects/{f['pid']}/visits/{f['visit']}/again").status_code == 201
    monkeypatch.setattr(quote_service, "FORMULA_VERSION", "d1-test")  # 표준견적서가 낡음
    assert code(approve(api, a["action_id"])) == (409, "already")
    row = action_row(a["action_id"])
    assert (row["status"], row["error_code"]) == ("failed", "already")


# ---- L6 · D9: 직접 할 일 칩 판 · 저장 잠금 ----


def test_diy_card_from_before_chips_changed_on_screen_is_stale(api, script):
    """화면에서 칩을 바꾼 뒤 옛 직접 할 일 카드를 승인해도 옛 목록으로 덮지 않는다(409 stale). 정리도 그 카드를 닫는다."""
    _, pid = home(api)
    a = propose_home(api, script, pid, {"diy": ["paint"]})
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["clean"]}).status_code == 200
    assert code(approve(api, a["action_id"], seen=a["target_ver"])) == (409, "stale")
    assert diy_keys() == ["diy.clean"]
    b = propose_home(api, script, pid, {"diy": ["clean", "light"]})
    assert b["target_ver"] != a["target_ver"]
    assert api.put(f"/projects/{pid}/diy", json={"diy": []}).status_code == 200
    assert sweep(api)["handled"] == 1
    assert action_row(b["action_id"])["status"] == "expired"
    assert diy_keys() == ["diy.none"]


def test_two_diy_saves_at_once_do_not_merge(api):
    """같은 공사의 칩 저장 둘이 겹쳐도 공사 행 잠금으로 줄 서서 뒤 저장만 남는다('없어요'와 칩이 같이 남지 않음)."""
    _, pid = home(api)
    p = uuid.UUID(pid)

    async def save(s, keys):
        await diy.set_diy(s, p, keys)
        await s.commit()

    async def go():
        async with SessionLocal() as first, SessionLocal() as second:
            await diy.set_diy(first, p, [])  # 없어요(아직 commit 전)
            later = asyncio.create_task(save(second, ["paint"]))
            await asyncio.sleep(0.5)
            await first.commit()
            await later

    run(api, go)
    assert diy_keys() == ["diy.paint"]


# ---- R7 · P10: 닫힌 까닭 문구 ----


def test_due_card_says_it_expired_and_stays_in_recent_cards(api, script):
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 2})
    query(
        "update assistant_actions set created_at = now() - interval '3 days',"
        " expires_at = now() - interval '1 minute' where id = $1",
        uuid.UUID(a["action_id"]),
    )
    run(api, actions.expire_due, now_utc())
    r = approve(api, a["action_id"])
    assert code(r) == (409, "expired")
    assert r.json()["error"]["message"] == actions.CLOSED["expired"]
    for n in (3, 4, 5, 1):  # 오래전에 처리한 카드 넷
        b = propose_home(api, script, pid, {"rooms": n})
        assert api.post(f"/assistant/actions/{b['action_id']}/reject").status_code == 200
    query(
        "update assistant_actions set decided_at = now() - interval '1 hour' where decided_at is not null"
    )
    uid = user_of("home@mitjip.test")

    async def go():
        async with SessionLocal() as s:
            rows = await repo.decided_of(
                s,
                uid,
                "customer",
                project_id=uuid.UUID(pid),
                closed=assistant_service.CLOSED_REASONS,
            )
            return [str(x.id) for x in rows], assistant_service.decided_line(rows)

    ids, said = run(api, go)
    assert ids[0] == a["action_id"]  # 방금 기한이 지난 카드는 기한으로 줄 선다(만든 때 아님)
    assert "까닭: 기한이 지난 제안이에요." in said


def test_decided_line_uses_due_words_and_the_saved_failure_message():
    def card(status: str, result: dict, error_code: str | None = None):
        return SimpleNamespace(
            status=status,
            result=result,
            error_code=error_code,
            summary={"title": "실측 시간"},
            kind="visit_slot",
        )

    said = assistant_service.decided_line(
        [
            card("expired", {"reason": "due"}),
            card(
                "failed",
                {"reason": "slot_taken", "message": "방금 다른 고객이 골랐어요."},
                "slot_taken",
            ),
        ]
    )
    assert said == (
        "최근 처리한 카드: 실측 시간(실행 안 됨 · 닫힘 · 까닭: 기한이 지난 제안이에요.)"
        " · 실측 시간(승인했지만 실행 못 함 · 까닭: 방금 다른 고객이 골랐어요.)"
    )


# ---- P6: 거절한 카드를 고객이 분명히 다시 부탁 ----


def test_fresh_reads_the_model_flag_and_this_turn_words_not_word_rules():
    """다시 해 달라는 뜻은 모델이 asked_again으로 정하고, 코드는 이번 턴 고객 말이 있는지만 본다(QA r6 c1 H2: 낱말
    규칙이 '아 그냥 그거 다시 해 줘'를 못 읽음). 카드 단추는 늘 새 결정, 무료 모드는 말로 다시 만들지 않는다."""

    def tc(**kw):
        return SimpleNamespace(
            **{"pressed": False, "mode": "llm", "asked_again": False, "text": "", **kw}
        )

    yes = [
        tc(pressed=True),
        tc(asked_again=True, text="아 그냥 그거 다시 해 줘"),
        tc(asked_again=True, text="실수로 거절했어요 다시 해 줘요"),
    ]
    no = [
        tc(text="아까 그거 32평 맞아요. 저장해 주세요"),  # 낱말은 보지 않아요(모델이 켜야 해요)
        tc(asked_again=True, text="  "),  # 이번 턴 고객 말이 없음
        tc(asked_again=True, text="다시 해 줘", mode="free"),  # 무료 모드는 말로 다시 만들지 않아요
    ]
    assert [propose.fresh(x) for x in yes] == [True] * len(yes)
    assert [propose.fresh(x) for x in no] == [False] * len(no)


def test_rejected_home_card_is_made_again_only_when_asked_clearly(api, script):
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 2})
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"

    def call(again: bool) -> list[dict]:
        args = {"fields": {"rooms": 2}, **({"asked_again": True} if again else {})}
        return [
            {"tool_calls": [{"id": "p", "name": "propose_home_info", "input": args}]},
            {"text": "확인해 주세요."},
        ]

    log = script(call(False))
    ev = ok(ask(api, pid, "방 개수는 어떻게 돼 있어요?"))  # 다시 부탁하지 않았다: 다시 밀지 않는다
    assert not [x for x in acts(ev) if x["status"] == "proposed"]
    got = tool_result(log, 1)
    assert got["state"] == "rejected" and "asked_again=true" in got["note"]
    script(call(True))
    ev = ok(ask(api, pid, "아까 그거 방 두 개 맞아요. 저장해 주세요"))
    (b,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert b["action_id"] != a["action_id"]
    r = approve(api, b["action_id"], seen=b["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text


# ---- P9: 추천에서 요청한 · 빠진 업체 빼기 ----


def test_picks_leave_out_requested_and_declined_vendors(api, script, monkeypatch):
    quiet(monkeypatch)
    names = {"maru": "마루와벽", "gyeol": "결도배", "hangyeol": "한결도배", "nuri": "누리도배"}
    ids = {k: vendor(api, f"{k}@mitjip.test", n) for k, n in names.items()}
    token, pid = home(api)
    asked = [ids["maru"], ids["gyeol"], ids["hangyeol"]]
    for vid in asked:
        assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, asked).status_code == 201
    for k in ("maru", "gyeol"):  # 두 곳은 못 받아요
        login(api, f"{k}@mitjip.test")
        r = api.post(f"/vendor/visits/{visit_of(pid, ids[k])}/decline", json={"code": "full"})
        assert r.status_code == 200, r.text
    use(api, token)
    log = script(
        [
            {"tool_calls": [{"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}]},
            {"text": "누리도배가 남았어요."},
        ]
    )
    ev = ok(ask(api, pid, "두 곳이 못 한대요. 다른 업체 더 찾아 줘"))
    got = tool_result(log, 1)
    assert [p["name"] for p in got["picks"]] == ["누리도배"]
    assert "한결도배" in got["note"]  # 요청한 업체는 추천에서 뺐다고 알린다
    (card,) = cards_of(ev, "vendor_picks")
    assert [p["name"] for p in card["data"]["picks"]] == ["누리도배"]


# ---- #4: 승인 카드 · 카드 글 날짜 ----


def test_home_start_date_card_shows_korean_dates(api, script):
    _, pid = home(api)
    new = today_seoul() + timedelta(days=50)
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"start_date": new.isoformat()}},
                    }
                ]
            },
            {"text": "카드를 확인해 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "공사는 좀 늦게 시작해요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    summary = json.dumps(a["summary"], ensure_ascii=False)
    assert not ISO.search(summary) and cards.md_long(new) in summary
    (card,) = cards_of(ev, "home_info")
    assert not ISO.search(json.dumps(card["data"], ensure_ascii=False))


def test_slot_and_confirm_summaries_show_korean_dates():
    w = SimpleNamespace(
        start=date(2026, 12, 14),
        end=date(2026, 12, 18),
        pick_due_at=datetime(2026, 12, 13, 9, tzinfo=SEOUL),
        instant=True,
    )
    v = SimpleNamespace(
        status="offered", window=w, proposal=None, vendor_name="마루와벽", visit_id=uuid.uuid4()
    )
    got = propose.slot_offer(v, {"via": "pick", "day": "2026-12-15", "half": "am"})["summary"]
    assert got.title == "마루와벽 실측 12월 15일(화) 오전"
    # 제목은 긴 꼴: 비서가 '12월 15일'이라고 말해도 문장 숫자 검사를 지난다
    assert {12, 15} <= guard.numbers(got.title)
    assert got.version == "업체가 답한 기간 12.14(월)~12.18(금)"
    s = actions.confirm_summary("마루와벽", 2, 3_000_000, 3, date(2026, 12, 31))
    assert {r.label: r.value for r in s.rows}["유효기간"] == "12.31(목)까지"
    # 카피 가이드 F2: 0을 붙이지 않는다
    assert cards.md_range(date(2026, 12, 7), date(2026, 12, 21)) == "12.7(월)~12.21(월)"
    assert cards.long_range(date(2026, 12, 1), date(2026, 12, 4)) == "12월 1일(화)~4일(금)"
    assert cards.long_range(date(2026, 12, 29), date(2027, 1, 2)) == "12월 29일(화)~1월 2일(토)"

"""v4 비서 새 도구 넷(갈래 T, 피클 표본 6 · 7): compare_grades(벽지 두 종류 견주기, 계산 엔진 · 저장 안 함) ·
market_range(시세 범위, 출처 한 줄 · 표본이 모자라면 말하지 않음) · withdraw_proposal(실행 전 카드를 고객 말로 거둠,
거절과 같게 남김) · propose_visit_cancel(보낸 실측 요청 취소 승인 카드) · 무료 모드 '취소해 줘' 길 · ActionOut
target_id · D2에서 넘어온 셋(화면 처리 정리 창 · 채팅으로 묻기 줄 · 보이는 줄 due_at 색인) · QA 2차에서 넘어온
둘(받은 견적서가 없거나 한 곳일 때 견적 비교 · 날짜 바꾸기 앞당기기 후보).
권한(남의 것 404 · 역할 403) · 동시 요청(실행 한 번). 유료 호출 0회(Claude 대본 · 무료 모드)."""

import asyncio
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions
from app.assistant import service as assistant_service
from app.assistant.tools import cards
from app.auth.models import User
from app.calc import quick_budget
from app.calc.common import pyeong_to_m2
from app.calc.schedule import workdays
from app.db import SessionLocal
from app.refprice.holidays import days_off
from app.refprice.market import MARKET_2026_11
from app.shared.clock import now_utc, today_seoul
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_extras import scheduled
from tests.test_project import body as project_body
from tests.test_quote_compare import quote
from tests.test_v3_project_home import HOME, PART
from tests.test_v3_visit_kit import (
    add,
    answer,
    choose,
    customer,
    offered,
    quiet,
    requested,
    user_id,
    vendor,
)
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v3_visit_kit import status as visit_status
from tests.test_v4_assistant_actions import action_row, acts, approve, code, propose_home
from tests.test_v4_assistant_aftercare import card_of, line, post_extra, tick
from tests.test_v4_assistant_nudges import nudges, run
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본이 없으면 LLM_LIVE=false라 무료 모드
    yield
    llm.clear_stubs()


@pytest.fixture
def script():
    yield llm.set_claude_script


def cards_of(ev, kind: str) -> list[dict]:
    return [d for e, d, _ in ev if e == "card" and d["kind"] == kind]


def said(ev) -> str:
    return cards_of(ev, "answer")[-1]["data"]["text"]


def results(log: list[dict], i: int = -1) -> list[dict]:
    """i번째(기본 마지막) Claude 호출에 보낸 도구 결과(모델이 받은 값)."""
    last = log[i]["messages"][-1]
    return [
        json.loads(b["content"])
        for b in last["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]


def call(script, api, pid: str, text: str, *tools: tuple[str, dict]) -> tuple[list, list]:
    """도구를 차례로 부르는 Claude 대본 턴 하나. (이벤트, 보낸 요청 기록)."""
    steps: list[dict] = [
        {"tool_calls": [{"id": f"t{i}", "name": name, "input": args}]}
        for i, (name, args) in enumerate(tools)
    ]
    log = script([*steps, {"text": "카드를 확인해 주세요."}])
    return ok(ask(api, pid, text)), log


def two_requests(api) -> dict:
    """업체 둘(마루와벽 · 결도배)에 실측 요청(고객으로 로그인한 채 끝난다)."""
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = customer(api)
    for vid in (a, b):
        assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [a, b]).status_code == 201, "요청"
    rows = query("select id, vendor_name from visits order by vendor_name")
    return {"token": token, "pid": pid, "visits": {r["vendor_name"]: str(r["id"]) for r in rows}}


# ---- compare_grades: 벽지 두 종류 견주기 ----


def test_compare_grades_counts_both_papers_with_the_calc_and_saves_nothing(api, script):
    signup(api, "eco@mitjip.test")
    eco = api.post("/projects", json={**HOME, "grade": "economy"}).json()["id"]
    eco_total = api.get(f"/projects/{eco}/standard").json()["total"]
    _, pid = home(api)  # HOME: 노원구 · 공급 69.4㎡ · 빈 집 · 실크
    silk_total = api.get(f"/projects/{pid}/standard").json()["total"]
    saved = query("select count(*) as n from standard_quotes")[0]["n"]
    ev, log = call(script, api, pid, "실크랑 합지 중에 뭐가 나아?", ("compare_grades", {}))
    (card,) = cards_of(ev, "grade_compare")
    d = card["data"]
    # 두 합계는 표준견적서 계산 엔진과 같은 값(그 벽지로 저장한 표준견적서와 같음), 차액도 계산 엔진
    assert (d["economy_won"], d["basic_won"]) == (eco_total, silk_total)
    assert d["diff_won"] == silk_total - eco_total > 0
    assert d["current"] == "basic" and d["can_change"] is True
    assert d["rows"][0]["name"] == "벽지 값"  # 달라지는 줄은 벽지 줄 먼저
    assert all(r["economy_won"] != r["basic_won"] for r in d["rows"])
    assert "%" not in json.dumps(d, ensure_ascii=False)  # 표준 대비 % 없음
    # 저장 안 함: 표준견적서 행 · 고른 벽지 그대로
    assert query("select count(*) as n from standard_quotes")[0]["n"] == saved
    assert api.get(f"/projects/{pid}").json()["home"]["grade"] == "basic"
    (got,) = results(log)
    assert got["diff_won"] == d["diff_won"]
    assert [x["grade"] for x in got["items"]] == ["합지", "실크"]
    assert got["items"][1]["picked"] is True and "id" not in json.dumps(got)
    # 카드 단추 [합지로 바꾸기] = choice grade:economy → 집 정보 승인 카드(무료 모드도)
    llm.clear_stubs()
    ev = ok(
        ask(
            api, pid, "합지로 바꿔 볼래요", context={"card_id": "grades", "choice": "grade:economy"}
        )
    )
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["kind"] == "home_info" and a["target_id"] == pid
    assert a["summary"]["rows"][0] == {"label": "벽지", "value": "합지", "sub": "지금 실크"}


def test_compare_grades_needs_dobae_and_market_range_reads_mokgong_items(api, script):
    _, pid = customer(api)  # v2 공사(기본 정보 없음 · 도배 실크): 전체 공사로 센다
    ev, log = call(script, api, pid, "벽지 비교해 줘", ("compare_grades", {}))
    (card,) = cards_of(ev, "grade_compare")
    assert card["data"]["can_change"] is False  # 집 정보 카드로 고칠 수 없는 v2 공사
    signup(api, "mok@mitjip.test")
    mok = {"mokgong": {"spaces": ["a"], "items": ["molding", "base"]}}
    only = api.post("/projects", json=project_body(trades=mok)).json()["id"]
    ev, log = call(script, api, only, "벽지 비교해 줘", ("compare_grades", {}))
    assert not cards_of(ev, "grade_compare") and results(log)[0]["error"] == "no_dobae"
    ev, log = call(script, api, only, "목공 시세", ("market_range", {"trade": "mokgong"}))
    (m,) = cards_of(ev, "market_range")
    want = quick_budget.quick(
        quick_budget.QuickIn(
            area_m2=pyeong_to_m2(Decimal(34)),  # 30평대 → 대표 34평(공급)
            area_basis="supply",
            dobae=False,
            molding=True,
            base=True,
            door="none",
            occupied=True,
        ),
        MARKET_2026_11,
    ).trades[0]
    assert (m["data"]["low_won"], m["data"]["high_won"]) == (want.lo, want.hi)
    assert m["data"]["trade"] == "목공" and "몰딩 · 걸레받이" in m["data"]["label"]


# ---- market_range: 시세 범위 ----


def test_market_range_reads_the_calc_band_with_one_source_line(api, script):
    _, pid = home(api)
    ev, log = call(
        script, api, pid, "32평 도배 보통 얼마 해요?", ("market_range", {"trade": "dobae"})
    )
    (card,) = cards_of(ev, "market_range")
    d = card["data"]
    want = quick_budget.quick(
        quick_budget.QuickIn(
            area_m2=Decimal("69.4"),
            area_basis="supply",
            dobae=True,
            door="none",
            grade="basic",
            ceiling=True,
            occupied=False,
        ),
        MARKET_2026_11,
    ).trades[0]
    assert (d["low_won"], d["high_won"], d["count"]) == (want.lo, want.hi, want.n)
    assert d["found"] is True and d["low_won"] % 10_000 == 0 and d["high_won"] % 10_000 == 0
    assert (
        d["source"] == f"믿집이 모은 아파트 도배 실견적 {want.n}건 · 가운데 절반 범위 · 부가세 포함"
    )
    # 원자료(줄 · 업체 · 글 주소)는 없다
    assert set(d) == {
        "trade", "label", "found", "low_won", "high_won", "count", "source", "assumed", "note",
    }  # fmt: skip
    assert "http" not in json.dumps(d)
    (got,) = results(log)
    assert [r["won"] for r in got["rows"]] == [want.lo, want.hi]
    assert got["source"] == d["source"] and got["count"] == want.n


def test_market_range_says_nothing_when_samples_are_short(api, script, monkeypatch):
    signup(api, "part@mitjip.test")
    part = api.post("/projects", json=PART).json()["id"]
    ev, log = call(script, api, part, "보통 얼마예요?", ("market_range", {"trade": "dobae"}))
    assert not cards_of(ev, "market_range")
    (got,) = results(log)
    assert got["found"] is False and "모자라" in got["note"] and "rows" not in got
    # 목공을 고르지 않은 공사 · 근거 수가 모자란 판도 범위를 말하지 않는다
    _, pid = home(api)
    ev, log = call(script, api, pid, "목공 시세는요?", ("market_range", {"trade": "mokgong"}))
    assert results(log)[0]["found"] is False and not cards_of(ev, "market_range")
    from app.assistant.tools import cards as cards_mod

    monkeypatch.setattr(cards_mod, "MIN_SAMPLES", 10_000)  # 근거 수가 기준보다 적은 판
    ev, log = call(script, api, pid, "시세는요?", ("market_range", {"trade": "dobae"}))
    assert results(log)[0]["found"] is False and not cards_of(ev, "market_range")


# ---- withdraw_proposal: 실행 전 카드를 고객 말로 거둔다 ----


def test_withdraw_one_open_card_is_kept_like_a_rejection(api, script):
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 3})
    assert a["target_id"] == pid  # ActionOut에 대상 id
    ev, log = call(
        script,
        api,
        pid,
        "아까 그 카드 취소해 줘",
        ("withdraw_proposal", {"kind": "any", "about": ""}),
    )
    (got,) = [x for x in acts(ev) if x["action_id"] == a["action_id"]]
    assert (got["status"], got["error_code"]) == ("rejected", "withdrawn")
    assert results(log)[0]["state"] == "withdrawn"
    row = action_row(a["action_id"])
    assert row["status"] == "rejected" and row["decided_at"] is not None
    assert json.loads(row["result"]) == {"reason": "withdrawn"}
    r = approve(api, a["action_id"])
    assert (
        code(r) == (409, "action_closed")
        and r.json()["error"]["message"] == "고객이 거둔 제안이에요."
    )
    # 거절과 같게: 비서가 스스로 같은 카드를 다시 내면 만들지 않는다
    ev, _ = call(script, api, pid, "방은 세 개", ("propose_home_info", {"fields": {"rooms": 3}}))
    assert not [x for x in acts(ev) if x["status"] == "proposed"]
    # 거둘 카드가 없으면 none(실행된 카드는 거두지 않는다)
    b = propose_home(api, script, pid, {"rooms": 2})
    assert approve(api, b["action_id"]).json()["status"] == "executed"
    ev, log = call(
        script, api, pid, "취소해 줘", ("withdraw_proposal", {"kind": "any", "about": ""})
    )
    assert results(log)[0]["state"] == "none" and action_row(b["action_id"])["status"] == "executed"


def test_withdraw_asks_with_chips_when_several_cards_are_open(api, script):
    vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = home(api)
    ev, _ = call(
        script,
        api,
        pid,
        "마루와벽에 요청해 줘",
        ("recommend_vendors", {"trade": "dobae"}),
        ("propose_visit_request", {"trade": "dobae", "vendor_refs": ["v1"]}),
    )
    (req,) = [x for x in acts(ev) if x["kind"] == "visit_request"]
    home_card = propose_home(api, script, pid, {"rooms": 3})
    ev, log = call(
        script, api, pid, "카드 취소해 줘", ("withdraw_proposal", {"kind": "any", "about": ""})
    )
    got = results(log)[0]
    assert got["state"] == "choose" and len(got["items"]) == 2
    (pick,) = cards_of(ev, "options")
    labels = [o["label"] for o in pick["data"]["options"]]
    assert labels == ["마루와벽에 실측 요청 보내기", "집 정보 저장"]
    assert [o["say"] for o in pick["data"]["options"]][1] == "집 정보 저장 카드 거둬 줘"
    assert {action_row(x)["status"] for x in (req["action_id"], home_card["action_id"])} == {
        "proposed"
    }
    # 제목으로 하나만 거둔다
    ev, log = call(
        script,
        api,
        pid,
        "집 정보 저장 카드 거둬 줘",
        ("withdraw_proposal", {"kind": "any", "about": "집 정보 저장"}),
    )
    assert results(log)[0]["state"] == "withdrawn"
    assert action_row(home_card["action_id"])["status"] == "rejected"
    assert action_row(req["action_id"])["status"] == "proposed"
    # 종류 · 업체 이름으로도 고른다
    ev, log = call(
        script,
        api,
        pid,
        "마루와벽 요청 카드 거둬",
        ("withdraw_proposal", {"kind": "visit_request", "about": "마루와벽에"}),
    )
    assert results(log)[0]["state"] == "withdrawn"
    assert action_row(req["action_id"])["status"] == "rejected"


def test_withdraw_and_approve_at_once_only_one_wins(api, script, monkeypatch):
    quiet(monkeypatch)
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 2})
    uid = user_id("home@mitjip.test")

    async def both():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
            row = await s.get(actions.AssistantAction, uuid.UUID(a["action_id"]))

        async def take():
            async with SessionLocal() as s:
                got = await actions.withdraw(s, row, now_utc())
                await s.commit()
                return got

        return await asyncio.gather(
            actions.execute(user, row.id, "customer", None, now_utc()),
            take(),
            return_exceptions=True,
        )

    done, took = run(api, both)
    row = action_row(a["action_id"])
    if isinstance(done, AppError):  # 거두기가 이겼다: 승인은 409, 집 정보 그대로
        assert done.status == 409 and row["status"] == "rejected"
        assert api.get(f"/projects/{pid}").json()["rev"] == 1
    else:  # 승인이 이겼다: 거두기는 아무것도 안 바꿈
        assert took is None and row["status"] == "executed"
        assert api.get(f"/projects/{pid}").json()["rev"] == 2


# ---- propose_visit_cancel: 보낸 실측 요청 취소 승인 카드 ----


def test_visit_cancel_card_waits_for_approval_then_cancels_and_tells_the_vendor(api, script):
    f = requested(api)
    pid, visit = f["pid"], f["visit"]
    ev, log = call(
        script,
        api,
        pid,
        "아까 보낸 요청 취소해 줘",
        ("withdraw_proposal", {"kind": "any", "about": ""}),
        ("propose_visit_cancel", {"visit_ref": "m1", "code": "changed"}),
    )
    (got,) = results(log, 1)  # 거둘 카드는 없고 보낸 요청(m1)을 알려 준다
    assert got["state"] == "none"
    assert got["requests"] == [{"ref": "m1", "vendor_name": "마루와벽", "state": "업체 답 기다림"}]
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_cancel"]
    assert (a["status"], a["target_id"], a["target_ver"]) == ("proposed", visit, "requested")
    assert a["summary"]["title"] == "마루와벽에 보낸 실측 요청 취소"
    assert {r["label"]: r["value"] for r in a["summary"]["rows"]}["까닭"] == "일정이 바뀌었어요"
    assert visit_status(visit) == "requested"  # 승인 전에는 그대로
    # 권한: 남의 것 404 · 업체 403
    home(api, "other@mitjip.test")
    assert approve(api, a["action_id"]).status_code == 404
    login(api, f["email"])
    assert approve(api, a["action_id"]).status_code == 403
    use(api, f["token"])
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert r.json()["result"]["text"] == "마루와벽에 보낸 실측 요청을 취소했어요"
    row = query(
        "select status, cancel_code, cancel_note from visits where id = $1", uuid.UUID(visit)
    )[0]
    assert (row["status"], row["cancel_code"], row["cancel_note"]) == ("cancelled", "changed", None)
    sent = query(
        "select body from notifications where user_id = $1 and kind = 'visit_cancelled'",
        uuid.UUID(f["vendor"]),
    )
    assert len(sent) == 1
    again = approve(api, a["action_id"])
    assert again.status_code == 200 and again.json() == r.json()  # 같은 승인 두 번 → 같은 결과
    # 끝난 요청은 다시 취소 카드를 만들지 않는다(고침 3차 B2: 오류 대신 닫힌 까닭을 값으로)
    ev, log = call(
        script,
        api,
        pid,
        "취소해 줘",
        ("propose_visit_cancel", {"visit_ref": "m1", "code": "other"}),
    )
    got = results(log)[0]
    assert got["state"] == "closed" and got["note"].startswith("이미 취소한 요청이에요")
    assert not acts(ev)


def test_visit_cancel_two_approvals_at_once_cancel_once(api, script, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    ev, _ = call(
        script,
        api,
        f["pid"],
        "취소",
        ("today_tasks", {}),
        ("propose_visit_cancel", {"visit_ref": "m1", "code": "other"}),
    )
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_cancel"]
    uid = user_id("home@mitjip.test")

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
        aid = uuid.UUID(a["action_id"])
        return await asyncio.gather(
            actions.execute(user, aid, "customer", None, now_utc()),
            actions.execute(user, aid, "customer", None, now_utc()),
            return_exceptions=True,
        )

    got = run(api, go)
    errs = [x for x in got if isinstance(x, BaseException)]
    assert all(isinstance(e, AppError) and e.status == 409 for e in errs)
    assert [x.status for x in got if not isinstance(x, BaseException)] == ["executed"] * (
        2 - len(errs)
    )
    assert visit_status(f["visit"]) == "cancelled"
    events = query(
        "select count(*) as n from visit_events where visit_id = $1 and to_status = 'cancelled'",
        uuid.UUID(f["visit"]),
    )
    assert events[0]["n"] == 1
    sent = query("select count(*) as n from notifications where kind = 'visit_cancelled'")
    assert sent[0]["n"] == 1


def test_visit_cancel_closes_the_slot_card_of_that_visit_and_survives_the_vendor_answer(
    api, script, monkeypatch
):
    quiet(monkeypatch)
    f = offered(api)  # 업체가 기간을 답함(offered)
    pid = f["pid"]
    ev, _ = call(
        script,
        api,
        pid,
        "실측 시간 골라 줘",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1"}),
        ("propose_visit_slot", {"slot_ref": "s1"}),
        ("propose_visit_cancel", {"visit_ref": "m1", "code": "other_vendor"}),
    )
    slot = next(x for x in acts(ev) if x["kind"] == "visit_slot")
    cancel = next(x for x in acts(ev) if x["kind"] == "visit_cancel")
    assert slot["target_id"] == cancel["target_id"] == f["visit"]
    # 업체 답으로 상태가 바뀌어도 취소할 수 있는 동안 취소 카드는 열려 있다(정리가 닫지 않음)
    assert run(api, actions.close_handled) == 0
    r = approve(api, cancel["action_id"])
    assert r.json()["status"] == "executed", r.text
    # 같은 요청의 반나절 카드는 같은 트랜잭션에서 닫힌다
    s = action_row(slot["action_id"])
    assert s["status"] == "expired" and json.loads(s["result"]) == {"reason": "handled_elsewhere"}
    assert code(approve(api, slot["action_id"])) == (409, "action_closed")


# ---- 무료 모드 '취소해 줘' ----


def test_free_cancel_withdraws_the_only_open_card(api, script):
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 4})
    llm.clear_stubs()
    ev = ok(ask(api, pid, "아까 그 카드 취소해 줘"))
    assert ev[-1][1]["mode"] == "free"
    (got,) = [x for x in acts(ev) if x["action_id"] == a["action_id"]]
    assert (got["status"], got["error_code"]) == ("rejected", "withdrawn")
    assert said(ev) == "네, 집 정보 저장 카드를 거뒀어요! 다른 걸로 보시려면 말씀해 주세요."


def test_free_cancel_of_a_sent_request_makes_an_approval_card(api):
    f = requested(api)
    ev = ok(ask(api, f["pid"], "보낸 실측 요청 취소해 주세요. 다른 업체로 할래요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert (a["kind"], a["target_id"]) == ("visit_cancel", f["visit"])
    assert {r["label"]: r["value"] for r in a["summary"]["rows"]}["까닭"] == "다른 업체로 할래요"
    assert said(ev).startswith("마루와벽에 보낸 실측 요청을 취소하는 카드를 만들었어요")
    assert visit_status(f["visit"]) == "requested"  # 말로는 실행하지 않는다


def test_free_cancel_with_several_targets_shows_chips_then_the_chip_picks_one(api):
    w = two_requests(api)
    ev = ok(ask(api, w["pid"], "실측 요청 취소해 줘"))
    assert not acts(ev)
    (pick,) = cards_of(ev, "options")
    options = {o["label"]: o for o in pick["data"]["options"]}
    # 고침 5차 R2(QA r5 D 3): 무료 모드도 LLM 길처럼 '둘 다 취소' 칩이 있어요
    assert set(options) == {"결도배에 보낸 실측 요청", "마루와벽에 보낸 실측 요청", "둘 다 취소"}
    assert options["마루와벽에 보낸 실측 요청"]["sub"] == "업체 답 기다림"
    assert said(ev) == "무엇을 취소할까요? 아래에서 골라 주세요."
    ev = ok(ask(api, w["pid"], options["마루와벽에 보낸 실측 요청"]["say"]))  # 칩을 누름
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert (a["kind"], a["target_id"]) == ("visit_cancel", w["visits"]["마루와벽"])
    # 업체 이름을 말하면 바로 그 요청
    ev = ok(ask(api, w["pid"], "결도배 요청 취소할래요"))
    (b,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert b["target_id"] == w["visits"]["결도배"]


def test_free_cancel_questions_and_nothing_to_cancel(api):
    f = requested(api)
    ev = ok(ask(api, f["pid"], "실측 요청 취소하면 위약금 있어요?"))
    assert not acts(ev) and not cards_of(ev, "options")
    _, pid = home(api, "empty@mitjip.test")
    ev = ok(ask(api, pid, "취소해 줘"))
    assert not acts(ev)
    assert said(ev).startswith("지금 거둘 승인 카드나 취소할 실측 요청이 없어요.")


# ---- D2에서 넘어온 것 ----


def test_close_handled_sees_every_open_card_past_one_page(api, script, monkeypatch):
    """화면 처리 정리가 새것 한 쪽(200개)만 보던 것: 쪽을 2로 줄여도 열린 카드 셋을 모두 본다."""
    quiet(monkeypatch)
    monkeypatch.setattr(actions, "HANDLED_BATCH", 2)
    made = []
    for i in range(3):
        email = f"h{i}@mitjip.test"
        _, pid = home(api, email)
        made.append((email, pid, propose_home(api, script, pid, {"rooms": 2})))
    for email, pid, _a in made:
        login(api, email)
        assert api.patch(f"/projects/{pid}", json={**HOME, "occupied": True}).status_code == 200
    assert run(api, assistant_service.sweep, now_utc())["handled"] == 3
    assert {action_row(a["action_id"])["status"] for _, _, a in made} == {"expired"}


def test_close_handled_resumes_where_the_time_budget_stopped(api, script, monkeypatch):
    quiet(monkeypatch)
    monkeypatch.setattr(actions, "_resume", None)
    made = []
    for i in range(3):
        email = f"r{i}@mitjip.test"
        _, pid = home(api, email)
        made.append(propose_home(api, script, pid, {"rooms": 2}))
        assert api.patch(f"/projects/{pid}", json={**HOME, "occupied": True}).status_code == 200
    # 한 쪽 1개 · 시간 예산 0: 차례마다 한 줄씩, 멈춘 자리부터 이어 빠짐없이 닫는다
    closed = [run(api, actions.close_handled, 1, 0) for _ in range(3)]
    assert closed == [1, 1, 1]
    assert {action_row(a["action_id"])["status"] for a in made} == {"expired"}


def test_asking_extra_in_chat_keeps_the_extra_line_waiting(api, monkeypatch):
    """승인 카드로 '채팅으로 묻기'를 실행해도 추가 금액 줄은 화면 길처럼 답 기다림으로 남는다."""
    quiet(monkeypatch)
    token, pid, did = scheduled(api)
    query("delete from notifications")
    post_extra(api, did, 150_000)
    use(api, token)
    tick(api)
    (n,) = nudges(trigger="extra_added")
    card = card_of(n)
    choice = {"card_id": card["card_id"], "choice": f"extra_answer:{card['data']['ref']},ask"}
    ev = ok(ask(api, pid, "추가 금액을 업체에 물어볼래요", context=choice))
    (a,) = [x for x in acts(ev) if x["kind"] == "extra_answer" and x["status"] == "proposed"]
    assert a["target_id"] == card["data"]["extra_id"]
    r = approve(api, a["action_id"])
    assert r.json()["status"] == "executed", r.text
    assert query("select ack from extra_charges")[0]["ack"] == "asked"
    assert line(n["id"]) == ("sent", None)
    run(api, assistant_service.sweep, now_utc())
    assert line(n["id"]) == ("sent", None)


def test_shown_nudge_lines_have_a_due_at_index():
    (row,) = query(
        "select indexdef from pg_indexes where indexname = 'ix_assistant_nudges_shown_due'"
    )
    assert (
        "(due_at, id)" in row["indexdef"]
        and "sent" in row["indexdef"]
        and "opened" in row["indexdef"]
    )


# ---- QA 2차에서 넘어온 것: 받은 견적서가 없으면 비교 카드를 내지 않아요(c5 턴 11 · 12) ----


def booked_quote(api, f: dict, name: str, email: str, amount: int, day: int) -> str:
    """two_requests의 한 곳: 업체가 기간을 답함 → 고객이 반나절을 골라 실측 확정 → 견적서를 보냄(고객으로 끝남)."""
    v = f["visits"][name]
    login(api, email)
    assert answer(api, v).status_code == 200
    use(api, f["token"])
    r = choose(api, f["pid"], v, n=day)
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text
    login(api, email)
    quote(api, v, amount)
    use(api, f["token"])
    return v


def test_compare_quotes_without_quotes_gives_the_waiting_count_not_an_empty_card(api, script):
    """QA r2 c5 턴 11 · 12: 실측 요청만 보낸 집(답 기다림 2곳)에서 견적 비교를 부르면 빈 비교 카드(cols: []) 대신
    도구 값으로 '아직 받은 견적서가 없어요 · 기다리는 업체 2곳'. 카드 다시 보여 주기도 같아요."""
    f = two_requests(api)
    say = "왜 이렇게 비싸요 장난해요?"
    ev, log = call(script, api, f["pid"], say, ("compare_quotes", {"trade": "dobae"}))
    assert cards_of(ev, "quote_compare") == []
    (got,) = results(log)
    assert got["note"] == "아직 받은 견적서가 없어요 · 기다리는 업체 2곳"
    assert (got["count"], got["waiting"], got["cols"]) == (0, 2, [])
    ev, log = call(
        script, api, f["pid"], "견적 비교 다시 보여 줘", ("show_card", {"kind": "quote_compare"})
    )
    assert cards_of(ev, "quote_compare") == []
    (got,) = results(log)
    assert "error" not in got and got["note"] == "아직 받은 견적서가 없어요 · 기다리는 업체 2곳"
    # 실측 요청도 없으면 기다리는 업체도 없다고
    _, pid = home(api, "empty@mitjip.test")
    _ev, log = call(script, api, pid, "견적서 비교해 줘", ("compare_quotes", {"trade": "dobae"}))
    (got,) = results(log)
    assert (got["count"], got["waiting"]) == (0, 0)
    assert got["note"] == "아직 받은 견적서가 없어요 · 실측 요청을 보낸 업체가 없어요"


def test_compare_quotes_with_one_quote_is_that_quote_card(api, script):
    """견적서가 한 곳만 왔으면 비교가 아니라 그 견적서 카드(열 하나 · single). 답 기다리는 곳은 도구 값의 수로만.
    두 곳째가 오면 다시 비교 카드예요."""
    f = two_requests(api)
    booked_quote(api, f, "마루와벽", "maru@mitjip.test", 3_080_000, 6)
    ev, log = call(script, api, f["pid"], "견적서 보여 줘", ("compare_quotes", {"trade": "dobae"}))
    (card,) = cards_of(ev, "quote_compare")
    d = card["data"]
    assert d["single"] is True and [c["vendor_name"] for c in d["cols"]] == ["마루와벽"]
    assert d["cols"][0]["state"] == "quoted" and d["gap_won"] is None
    (got,) = results(log)
    assert (got["count"], got["waiting"]) == (1, 1)
    assert got["note"] == "받은 견적서는 한 곳이에요 · 기다리는 업체 1곳"
    assert [c["vendor_name"] for c in got["cols"]] == ["마루와벽"]
    booked_quote(api, f, "결도배", "gyeol@mitjip.test", 3_300_000, 7)
    ev, log = call(
        script, api, f["pid"], "견적서 비교해 줘", ("compare_quotes", {"trade": "dobae"})
    )
    (card,) = cards_of(ev, "quote_compare")
    assert card["data"]["single"] is False and len(card["data"]["cols"]) == 2
    assert card["data"]["gap_won"] is not None
    (got,) = results(log)
    assert (got["count"], got["waiting"]) == (2, 0) and "note" not in got


def test_free_quote_step_card_without_quotes_falls_back_to_the_standard(api):
    """무료 모드 견적 질문의 단계 카드(입구 관문 quote_explanation): 받은 견적서가 없으면 비교 카드가 없어서(None)
    표준견적서 카드로 가요(오류 · 빈 카드 없이)."""
    f = two_requests(api)
    uid = user_id("home@mitjip.test")

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, uid)
        tc = SimpleNamespace(
            surface="customer",
            visit_id=None,
            project_id=uuid.UUID(f["pid"]),
            user=user,
            today=today_seoul(),
            now=now_utc(),
            refs=None,
        )
        return await cards.step_card(tc, "quote_explanation")

    card = asyncio.run(go())
    assert card is not None and card.kind == "standard_quote"


# ---- QA 2차에서 넘어온 것: 앞당기기 카드에 지금보다 늦은 후보가 섞이지 않아요(f1x 19) ----


def change_script(script, **wish) -> list[dict]:
    """공사 날짜를 읽고(d1) 날짜 바꾸기 요청 승인 카드를 만드는 Claude 대본."""
    change = {"deal_ref": "d1", "reason": "other", **wish}
    return script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {"tool_calls": [{"id": "c", "name": "propose_date_change", "input": change}]},
            {"text": "카드를 확인해 주세요."},
        ]
    )


def made(ev) -> list[dict]:
    return [x for x in acts(ev) if x["status"] == "proposed"]


def wishes(a: dict) -> list[str]:
    return json.loads(action_row(a["action_id"])["payload"])["wish_dates"]


def reject(api, a: dict) -> None:
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"


def test_pull_forward_change_offers_only_days_before_the_start(api, script):
    """QA r2 f1x 19: 12.14~12.16 공사에 '12월 10일부터로 당겨 주세요' 하면 후보 3이 12.15~12.17로 늦었어요. 앞당기기면
    지금 시작일 전 후보만, 미루기면 뒤 후보만 내요. 방향은 도구 인자(earlier · later)이고, 없으면 말한 날짜와 지금
    시작일을 견줘 정해요(모델 · 무료 모드 둘 다). 앞당길 날이 없으면 도구 오류."""
    token, pid, _did = scheduled(api)
    use(api, token)
    start = query("select start_date from deals")[0]["start_date"]
    today = today_seoul()
    off = days_off(today, today + timedelta(days=90))
    before = [x for x in workdays(today + timedelta(days=1), 40, off) if x < start]
    assert len(before) >= 3
    # 지금 시작일 바로 앞 일하는 날: 예전에는 지금 시작일을 건너뛴 늦은 후보 둘이 뒤에 붙었어요
    prev = before[-1]
    # 모델: 방향 없이 이날부터 → 지금 시작일보다 앞이라 앞당기기
    change_script(script, wish_from=prev.isoformat())
    (a,) = made(ok(ask(api, pid, f"{prev.month}월 {prev.day}일부터로 당겨 주세요")))
    assert wishes(a) == [prev.isoformat()]
    reject(api, a)
    # 무료 모드('M월 D일'만 넘겨요)도 같은 함수라 지금 시작일 전 후보만
    llm.clear_stubs()
    two = before[-2]
    (b,) = made(ok(ask(api, pid, f"{two.month}월 {two.day}일부터로 당겨 주세요")))
    assert wishes(b) == [two.isoformat(), prev.isoformat()]
    reject(api, b)
    # 방향 인자: 며칠 앞당기기(delay_days + earlier)
    change_script(script, delay_days=(start - before[-3]).days, direction="earlier")
    (c,) = made(ok(ask(api, pid, "사흘쯤 당겨 주세요")))
    assert wishes(c) == [x.isoformat() for x in before[-3:]]
    reject(api, c)
    # 앞당길 날이 없으면(지금 시작일부터) 도구 오류, 카드 없음
    log = change_script(script, wish_from=start.isoformat(), direction="earlier")
    assert made(ok(ask(api, pid, "더 당겨 주세요"))) == []
    err = log[2]["messages"][-1]["content"][0]
    assert err["is_error"] and "no_earlier" in err["content"]
    # 미루기(later)면 앞선 날을 말해도 지금 시작일 뒤 후보만
    change_script(script, wish_from=prev.isoformat(), direction="later")
    (d,) = made(ok(ask(api, pid, "미뤄 주세요")))
    assert wishes(d) and all(x > start.isoformat() for x in wishes(d))

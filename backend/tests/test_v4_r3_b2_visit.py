"""고침 3차 B2(QA r3 s1 · s4 · s6 · c1 · c4 #37 · v1 M6 · r2 c6): 지역 바꾸기 · 잠금 풀기 · 다른 구 업체 읽기 · 맡긴
고르기(점수 1위) · 취소 대상 고르기 · 닫힌 요청 · 취소 뒤 단계 · 작업 줄 · 새 소식 · 바뀐 카드 줄 · 반나절 뒤 일 · 다른
시간 후보 · 다른 날 제안 · 잠긴 뒤 칸 단추. 유료 호출 0회(Claude 대본 · LLM 꺼짐)."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import customer as customer_tools
from app.assistant.tools import propose
from app.calc.schedule import wish_open, wishes_blocked, workdays
from app.visit import service as visit_service
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import OFF, TODAY
from tests.test_extras import scheduled
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import add, booked, offered, quiet, vendor, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v3_visit_kit import status as visit_status
from tests.test_v4_assistant_actions import acts, approve, propose_home
from tests.test_v4_assistant_aftercare import action, tick
from tests.test_v4_assistant_new_tools import call, cards_of, results, said, two_requests
from tests.test_v4_assistant_nudges import nudges
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login
from tests.test_visit_vendors import priced


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


def home_requested(api, email: str = "home@mitjip.test") -> tuple[str, str, str, str]:
    """집 정보(v3, 노원구 상계동)가 있는 공사에 마루와벽 실측 요청까지(고객으로 로그인한 채). (토큰, 공사, 업체, 요청)"""
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    token, pid = home(api, email)
    assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [vid]).status_code == 201
    return token, pid, vid, visit_of(pid, vid)


def cancel(api, pid: str, visit: str):
    r = api.post(f"/projects/{pid}/visits/{visit}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text


def locked(api, pid: str) -> bool:
    return api.get(f"/projects/{pid}").json()["locked"]


def payload(aid: str) -> dict:
    return action(aid)["payload"]


# ---- 결정 1 · 2: 지역 바꾸기 · 잠금 풀기 ----


def test_home_region_changes_by_approval_and_is_refused_while_a_request_is_live(api, script):
    _, pid = home(api)  # 노원구 상계동
    ev, log = call(
        script,
        api,
        pid,
        "관악구로 잘못 넣었어요. 노원구 말고 관악구로 바꿔 주세요",
        ("propose_home_info", {"fields": {"sgg": "관악구"}}),
    )
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    row = {"label": "지역", "value": "서울 관악구", "sub": "지금 서울 노원구"}
    assert a["summary"]["rows"] == [row]
    assert "업체 추천도 바뀐 지역 업체로" in a["summary"]["note"]
    got = results(log)[0]
    assert got["state"] == "new" and got["summary"]["rows"] == [row]
    assert payload(a["action_id"])["fields"] == {"sido": "seoul", "sgg": "관악구", "emd": None}
    (card,) = cards_of(ev, "home_info")
    assert card["data"]["changes"] == [
        {"label": "지역", "before": "서울 노원구", "after": "서울 관악구"}
    ]
    assert api.get(f"/projects/{pid}").json()["sgg"] == "노원구"  # 승인 전에는 그대로
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.json()["status"] == "executed", r.text
    p = api.get(f"/projects/{pid}").json()
    assert (p["sgg"], p["home"]["sgg"], p["home"]["emd"], p["rev"]) == ("관악구", "관악구", None, 2)
    # 같은 지역이면 바뀐 칸이 없어요 · 모르는 지역은 다시 물어요
    ev, log = call(script, api, pid, "관악구요", ("propose_home_info", {"fields": {"sgg": "관악"}}))
    assert results(log)[0]["error"] == "no_change" and not acts(ev)
    ev, log = call(script, api, pid, "상계동", ("propose_home_info", {"fields": {"sgg": "상계동"}}))
    assert results(log)[0]["error"] == "bad_region"


def test_live_request_locks_region_then_cancelling_every_request_unlocks_it(api, script):
    _, pid, _vid, visit = home_requested(api)
    assert locked(api, pid) is True
    ev, log = call(
        script, api, pid, "관악구로 바꿔 줘", ("propose_home_info", {"fields": {"sgg": "관악구"}})
    )
    got = results(log)[0]
    assert (got["error"], got["message"]) == ("locked", propose.LOCKED_LIVE)
    assert "propose_visit_cancel" in got["hint"] and not acts(ev)
    # 요청을 모두 취소하면(견적서 전) 잠금이 풀리고 집 정보를 고칠 수 있어요(QA r3 s1 B3)
    cancel(api, pid, visit)
    assert locked(api, pid) is False
    ev, log = call(
        script, api, pid, "관악구로 바꿔 줘", ("propose_home_info", {"fields": {"sgg": "관악구"}})
    )
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert approve(api, a["action_id"], seen=a["target_ver"]).json()["status"] == "executed"
    assert api.get(f"/projects/{pid}").json()["sgg"] == "관악구"


def test_a_sent_quote_keeps_home_locked_after_every_request_is_closed(api):
    f = booked(api)  # 실측 잡힘 → 견적서 옴 → 다시 고르기로 모두 닫힘
    login(api, f["email"])
    quote(api, f["visit"], 3_080_000)
    use(api, f["token"])
    r = api.post(f"/projects/{f['pid']}/visits/reselect", json={"trade": "dobae"})
    assert r.status_code == 200, r.text
    assert visit_status(f["visit"]) == "closed"
    assert locked(api, f["pid"]) is True  # 견적서가 온 뒤에는 풀리지 않아요
    # 견적서 없이 다시 고르기로 닫으면 풀려요
    g = booked(api, email="gyeol@mitjip.test", name="결도배", customer_email="b@mitjip.test")
    r = api.post(f"/projects/{g['pid']}/visits/reselect", json={"trade": "dobae"})
    assert r.status_code == 200, r.text
    assert locked(api, g["pid"]) is False


# ---- 결정 3 · 4: 다른 구 업체 읽기 · 맡기면 점수 1위 ----


def test_recommend_other_district_only_reads_and_gives_no_refs(api, script):
    vendor(api, "maru@mitjip.test", "마루와벽")  # 노원구
    priced(api, "gwanak@mitjip.test", "관악도배", areas=[{"sido": "seoul", "sgg": "관악구"}])
    _, pid = home(api)
    ev, log = call(
        script,
        api,
        pid,
        "관악구 업체도 볼 수 있어요?",
        ("recommend_vendors", {"trade": "dobae", "sgg": "관악구"}),
    )
    got = results(log)[0]
    assert (got["area"], got["region"], got["state"]) == ("관악구", "서울 관악구", "보기만 해요")
    assert [x["name"] for x in got["picks"]] == ["관악도배"]
    assert all("ref" not in x for x in got["picks"])  # 이름표가 없어 요청 카드를 만들 수 없어요
    assert "집 지역(서울 노원구)이 아닌 서울 관악구 업체를 읽기만 했어요" in got["note"]
    (card,) = cards_of(ev, "vendor_picks")
    assert card["card_id"] == "picks-dobae@관악구"  # '@' 카드는 화면이 보기만으로 그려요
    assert card["data"]["area_name"] == "관악구" and "보기만" in card["say"]
    assert api.get(f"/projects/{pid}").json()["sgg"] == "노원구"  # 집 정보는 그대로
    # 집 지역과 같은 구면 늘 추천(이름표 있음)
    ev, log = call(
        script, api, pid, "노원구 업체", ("recommend_vendors", {"trade": "dobae", "sgg": "노원구"})
    )
    assert [x["name"] for x in results(log)[0]["picks"]] == ["마루와벽"]
    assert results(log)[0]["picks"][0]["ref"].startswith("v")


def test_left_to_us_puts_the_score_top_vendor_on_the_server(api, script):
    maru = vendor(api, "maru@mitjip.test", "마루와벽")  # 가견적이 더 낮아 점수 1위
    priced(api, "gyeol@mitjip.test", "결도배", wall=7000)
    _, pid = home(api)
    ev, log = call(
        script,
        api,
        pid,
        "제일 괜찮은 데로 알아서 보내 줘",
        ("recommend_vendors", {"trade": "dobae"}),
        ("propose_visit_request", {"trade": "dobae", "vendor_refs": [], "pick": "top"}),
    )
    rec = results(log, 1)[0]
    assert [x["name"] for x in rec["picks"]] == ["마루와벽", "결도배"]
    assert "고객이 골라 달라고 맡기면: 마루와벽(믿집 점수 1위" in rec["note"]
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_request"]
    assert payload(a["action_id"])["vendor_ids"] == [maru]
    assert a["summary"]["title"] == "마루와벽에 실측 요청 보내기"
    rows = {r["label"]: r["value"] for r in a["summary"]["rows"]}
    assert rows["지역"] == "서울 노원구"  # 어느 집 지역으로 가는 요청인지(QA r3 s1)
    got = results(log, 2)[0]
    assert got["vendor"] == "마루와벽" and got["why"][0] == propose.TOP_WHY
    assert {"label": "지역", "value": "서울 노원구"} in got["summary"]["rows"]
    assert {"label": "마루와벽", "won": a["summary"]["amounts"][0]["won"]} in got["summary"]["rows"]
    # 이름표도 맡기기도 없으면 입력 오류
    ev, log = call(
        script, api, pid, "요청", ("propose_visit_request", {"trade": "dobae", "vendor_refs": []})
    )
    assert results(log)[0]["error"] == "bad_input"


# ---- 취소: 대상이 여럿이면 고르기 · 닫힌 요청은 카드 없음 ----


def test_cancel_without_target_asks_with_chips_and_a_closed_request_gets_no_card(api, script):
    w = two_requests(api)
    pid = w["pid"]
    ev, log = call(script, api, pid, "취소해 줘", ("propose_visit_cancel", {"code": "other"}))
    got = results(log)[0]
    assert got["state"] == "choose" and not acts(ev)
    assert {x["vendor_name"] for x in got["requests"]} == {"결도배", "마루와벽"}
    (pick,) = cards_of(ev, "options")
    assert pick["card_id"] == "cancel-pick"
    options = {o["label"]: o for o in pick["data"]["options"]}
    assert set(options) == {"결도배에 보낸 실측 요청", "마루와벽에 보낸 실측 요청"}
    assert options["마루와벽에 보낸 실측 요청"]["say"] == "마루와벽에 보낸 실측 요청 취소해 줘"
    maru = next(x["ref"] for x in got["requests"] if x["vendor_name"] == "마루와벽")
    cancel(api, pid, w["visits"]["마루와벽"])
    # 남은 요청이 하나면 대상 없이 불러도 그 요청 카드
    ev, log = call(script, api, pid, "요청 취소해 줘", ("propose_visit_cancel", {"code": "other"}))
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_cancel"]
    assert a["target_id"] == w["visits"]["결도배"]
    # 이미 취소한 요청: 카드 없이 까닭(QA r3 c4 #37)
    ev, log = call(
        script,
        api,
        pid,
        "마루와벽 취소해 줘",
        ("propose_visit_cancel", {"visit_ref": maru, "code": "other"}),
    )
    got = results(log)[0]
    assert (got["state"], got["vendor_name"]) == ("closed", "마루와벽")
    assert got["note"] == "이미 취소한 요청이에요. 카드를 만들지 않았어요."
    assert not [x for x in acts(ev) if x["status"] == "proposed"]


def test_ended_why_names_the_reason_of_each_closed_request():
    def v(status, **kw):
        return SimpleNamespace(
            **{"close_reason": None, "expired_reason": None, **kw}, status=status
        )

    assert visit_service.ended_why(v("requested")) is None
    assert visit_service.ended_why(v("closed", close_reason="other_chosen")) == (
        "다른 업체를 확정해서 닫힌 요청이에요"
    )
    assert visit_service.ended_why(v("expired", expired_reason="reply")).startswith(
        "업체가 48시간 안에"
    )
    assert visit_service.ended_why(v("quoted")).startswith("견적서가 온 요청이라")


# ---- 취소 뒤: 단계 · 작업 줄 수 · 새 소식 ----


def test_after_cancelling_every_request_the_stage_task_and_news_move_on(api, script):
    f = booked(api)  # 바로 확정: 고객 알림 '실측이 … 정해졌어요'
    pid = f["pid"]
    news = api.get("/assistant/today", params={"project_id": pid}).json()["news"]
    assert any("정해졌어요" in x["title"] for x in news)
    cancel(api, pid, f["visit"])
    today = api.get("/assistant/today", params={"project_id": pid}).json()
    assert not any("정해졌어요" in x["title"] for x in today["news"])  # 끝난 일의 소식은 빼요
    assert today["todo"]  # 빈 카드가 아니라 다음 걸음(업체 고르기)
    (t,) = api.get(f"/projects/{pid}/overview").json()["trades"]
    assert (t["current"], t["todo"]["code"]) == (3, "pick")  # 취소한 요청은 세지 않아요
    assert locked(api, pid) is False
    script(
        [
            {"tool_calls": [{"id": "t", "name": "today_tasks", "input": {}}]},
            {"text": "업체를 다시 골라 볼까요?"},
        ]
    )
    ev = ok(ask(api, pid, "다 취소했는데 이제 뭐 해요?"))
    task = next(d["task"] for e, d, _ in ev if e == "status" and d.get("task"))
    assert task["title"] == "끝난 실측 요청 1곳" and task["state"] == "done"


# ---- 바뀐 카드 줄 · 반나절 뒤 일 · 다른 시간 ----


def test_new_card_of_the_same_kind_says_the_old_open_card_was_closed(api, script):
    _, pid = home(api)
    old = propose_home(api, script, pid, {"rooms": 3})
    ev, log = call(
        script, api, pid, "아니 방은 두 개예요", ("propose_home_info", {"fields": {"rooms": 2}})
    )
    got = results(log)[0]
    assert got["replaced"] == ["집 정보 저장"]
    assert "앞에 열려 있던 '집 정보 저장' 카드는 닫고 이 카드로 바꿨어요" in got["note"]
    assert got["summary"]["rows"] == [{"label": "방 개수", "value": "2", "sub": "지금 없음"}]
    (closed,) = [x for x in acts(ev) if x["action_id"] == old["action_id"]]
    assert closed["status"] == "expired" and closed["error_code"] == "replaced"


def test_slot_card_result_says_it_is_set_only_after_the_vendor_accepts(api, script):
    f = offered(api, instant=False)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "실측 시간 골라 줘",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "any"}),
        ("propose_visit_slot", {"slot_ref": "s1"}),
    )
    got = results(log, 3)[0]
    assert got["state"] == "new" and propose.SLOT_ACCEPT in got["note"]
    assert {"label": "그 뒤 일", "value": "업체가 수락하면 확정돼요"} in got["summary"]["rows"]


def test_more_slots_skip_shown_halves_and_reach_afternoons(api, script):
    f = offered(api)  # 업체 기간 오늘 + 5 ~ 12일, 빈 반나절 많음
    _ev, log = call(
        script,
        api,
        f["pid"],
        "실측 시간 보여 줘",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "any"}),
    )
    first = results(log, 2)[0]["candidates"]
    assert first and {c["half"] for c in first} == {"오전"}  # 처음 후보는 날마다 오전
    _ev, log = call(
        script,
        api,
        f["pid"],
        "다른 시간도 볼래요",
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "any", "more": True}),
    )
    got = results(log)[0]
    seen = {(c["day"], c["half"]) for c in first}
    assert got["candidates"] and not seen & {(c["day"], c["half"]) for c in got["candidates"]}
    assert any(c["half"] == "오후" for c in got["candidates"])  # QA r3 c1 6턴: 오후 자리
    assert got["note"] == customer_tools.MORE_NOTE
    # 같은 말 · 같은 선호여도 more 없이 부르면 처음 후보 그대로(기존 동작)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "시간 다시",
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "any"}),
    )
    assert {(c["day"], c["half"]) for c in results(log)[0]["candidates"]} == seen


# ---- 결정 5: 다른 날 제안(r2 c6) ----


def test_wish_judgment_sees_the_whole_block_not_only_the_start_day():
    d = workdays(TODAY + timedelta(days=35), 5, OFF)
    busy = [d[1], d[3]]  # 바란 시작일(d0 · d2) 자체는 비었지만 이어지는 날이 다른 공사
    assert wish_open(d[0], 1, busy, OFF) is True
    assert wish_open(d[0], 3, busy, OFF) is False
    assert wishes_blocked([d[0], d[2]], 3, TODAY, busy, OFF) is True
    assert wishes_blocked([d[0], d[2]], 1, TODAY, busy, OFF) is False
    assert wishes_blocked([TODAY], 3, TODAY) is True  # 지난 날은 막힌 것
    sat = next(x for x in (TODAY + timedelta(days=i) for i in range(30, 40)) if x.weekday() == 5)
    assert wish_open(sat, 2) is False  # 일하는 날이 아닌 시작일


def test_vendor_alt_dates_pass_when_every_wish_block_hits_another_job(api, monkeypatch):
    """r2 c6: 비서 후보는 2일 묶음으로, 실행은 시작일 하루만 봐서 비서가 낸 다른 날 제안이 409였어요."""
    quiet(monkeypatch)
    from app.schedule import service as schedule_service

    customer_token, pid, did = scheduled(api)
    use(api, customer_token)
    d = workdays(TODAY + timedelta(days=35), 5, OFF)
    body = {"wish_dates": [d[0].isoformat(), d[2].isoformat()], "reason": "이사 날짜가 바뀌었어요."}
    assert api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body).status_code == 201
    busy = [d[1], d[3]]

    async def taken(_s, _d, _today):  # 같은 업체의 다른 공사로 찬 날(시험이 정한다)
        return busy

    monkeypatch.setattr(schedule_service, "_busy", taken)
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'dates_requested'")
    tick(api)
    (n,) = nudges(trigger="dates_requested")
    a = action(n["action_id"])
    start = date.fromisoformat(a["payload"]["days"][0])
    assert a["summary"]["title"].startswith("다른 날 제안") and start not in (d[0], d[2])
    login(api, "maru@mitjip.test")
    r = approve(api, str(n["action_id"]), prefix="/vendor/assistant")
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (p,) = query("select start_date, kind from date_proposals where status = 'pending'")
    assert (p["start_date"], p["kind"]) == (start, "change")


# ---- 잠긴 뒤 옛 카드 칸 단추(v1 M6) ----


def test_locked_home_field_button_ends_with_a_set_line_without_llm(api, script):
    _, pid, _vid, _visit = home_requested(api)
    log = script([{"text": "불리면 안 되는 대본이에요."}])
    ev = ok(ask(api, pid, "합지로 바꿀래요", context={"choice": "grade:economy"}))
    assert log == []  # LLM을 부르지 않아요
    assert said(ev) == propose.LOCKED_LIVE and not acts(ev)
    done = ev[-1][1]
    assert done["mode"] == "free"
    (row,) = query("select trace from assistant_turns order by created_at desc limit 1")
    assert json.loads(row["trace"])["reason"] == "locked"

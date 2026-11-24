"""QA 9차 F2(실측 흐름 도구 · 카드). 유료 호출 0회(Claude 대본 · LLM 꺼짐). 업체 지시문(M5)은
test_v4_r3_a1_prompt.

- H1: 업체가 다른 날을 낸 뒤(proposed) 처음 실측 가능 기간에서 다시 고르는 후보 · 승인 카드(repick + pick 한 번에).
- M1: 같은 업체 두 번째 요청의 취소 카드 · 이어 하기 안내가 다시 요청할 수 없다고 미리 말하고, 막힌 업체는 추천 ·
  요청에서 까닭을 남겨요.
- 낮음: 실측 말(실측 가능 기간 · 이 날짜로 고르기 · 고른 실측 날짜 · 칩) · 콕 집은 요일 먼저 · 요청 뒤 요일 바꾸기 길 ·
  취소 메모 상태별 · 실측 확정 할 일 줄 · 오늘 정할 일 한 줄.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free, runtime
from app.assistant.tools import cards, propose
from app.calc import slots
from app.calc.progress import TradeFacts, progress
from app.shared.clock import SEOUL
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import use
from tests.test_v3_visit_kit import (
    add,
    booked,
    customer,
    d,
    day,
    notes,
    offered,
    picked,
    requested,
    run,
    user_id,
    vendor,
    visit_of,
    with_user,
)
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v3_visit_kit import status as visit_status
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_new_tools import call, cards_of, results
from tests.test_v4_r3_b2_visit import cancel, home_requested
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


SLOTS = {"prefer": "any", "days": "any"}


def proposed(api) -> dict:
    """바로 확정 끔 → 고객이 오늘 + 6일 오전을 고름 → 업체가 오늘 + 7일 오후 · 8일 오전을 냄(고객으로 로그인한 채)."""
    f = picked(api)
    login(api, f["email"])
    body = {
        "reason_code": "other_site",
        "note": "오전은 다른 현장이에요",
        "slots": [{"day": d(7), "half": "pm"}, {"day": d(8), "half": "am"}],
    }
    r = api.post(f"/vendor/visits/{f['visit']}/propose", json=body)
    assert r.status_code == 200, r.text
    use(api, f["token"])
    return f


def second_try(api) -> dict:
    """마루와벽 요청 → 취소 → 한 번 더 요청(시도 2). visit은 두 번째 요청(고객으로 로그인한 채)."""
    f = requested(api)
    cancel(api, f["pid"], f["visit"])
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/again")
    assert r.status_code == 201 and r.json()["attempt"] == 2, r.text
    return {**f, "first": f["visit"], "visit": r.json()["visit_id"]}


def rows_of(got: dict) -> dict[str, str]:
    return {r["label"]: r["value"] for r in got["summary"]["rows"] if "value" in r}


# ---- H1: 업체가 낸 날 대신 처음 실측 가능 기간에서 다시 고르기 ----


def test_proposal_card_tells_the_way_back_to_the_vendor_window(api, script):
    f = proposed(api)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "업체가 다른 날을 냈대요. 어떻게 해요?",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS}),
    )
    got = results(log, 2)[0]
    assert got["status"] == "proposed"
    assert {(c["day"], c["half"]) for c in got["candidates"]} == {(d(7), "오후"), (d(8), "오전")}
    # 업체가 낸 날이 안 맞으면 more=true로 처음 기간 후보를 받고, 화면은 [업체 기간에서 고르기](QA r9 c1 T6~T8)
    assert "more=true" in got["note"] and "[업체 기간에서 고르기]" in got["note"]


def test_more_on_a_proposal_gives_window_days_and_the_card_picks_again(api, script):
    f = proposed(api)
    ev, log = call(
        script,
        api,
        f["pid"],
        "26일, 27일 오전은 안 돼요. 처음 보낸 기간에서 다시 고를 수 없어요?",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS, "more": True}),
    )
    got = results(log, 2)[0]
    halves = {(c["day"], c["half"]) for c in got["candidates"]}
    assert halves and not halves & {(d(7), "오후"), (d(8), "오전")}  # 업체가 낸 날은 빼요
    assert all(d(5) <= c["day"] <= d(12) for c in got["candidates"])  # 처음 실측 가능 기간 안
    assert "업체가 낸 날은 닫혀요" in got["note"]
    (card,) = cards_of(ev, "visit_slots")
    assert card["data"]["instant"] is False and len(card["data"]["candidates"]) == len(halves)
    first = got["candidates"][0]
    ev, log = call(
        script, api, f["pid"], "그 날로 할래요", ("propose_visit_slot", {"slot_ref": first["ref"]})
    )
    out = results(log)[0]
    assert out["state"] == "new" and out["summary"]["approve_label"] == "이 날짜로 다시 고르기"
    assert rows_of(out)["그 뒤 일"] == "업체가 낸 날은 닫히고 업체가 수락하면 확정돼요"
    assert propose.REPICK_THEN in out["note"]
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert r.json()["result"]["text"] == "고른 실측 날짜를 보냈어요. 업체가 수락하면 확정돼요"
    assert visit_status(f["visit"]) == "picked"
    assert query("select status from visit_proposals")[0]["status"] == "repicked"
    (h,) = query("select day, half from visit_holds where status = 'active'")
    assert (h["day"].isoformat(), {"am": "오전", "pm": "오후"}[h["half"]]) == (
        first["day"],
        first["half"],
    )
    kinds = [n["kind"] for n in notes(f["email"])]
    assert "visit_repicked" in kinds and kinds.count("visit_picked") == 2


def test_old_window_day_after_a_proposal_becomes_a_pick_again_card(api, script):
    """업체가 다른 날을 낸 뒤 앞 카드(처음 기간)의 날을 고르면 '고를 수 있는 때가 아니에요' 대신 다시 고르기 카드."""
    f = offered(api, instant=False)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "실측 날짜 보여 줘",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS}),
    )
    old = results(log, 2)[0]["candidates"][0]
    assert (
        api.post(
            f"/projects/{f['pid']}/visits/{f['visit']}/pick",
            json={"day": old["day"], "half": "am" if old["half"] == "오전" else "pm"},
        ).json()["status"]
        == "picked"
    )
    login(api, f["email"])
    other = [x for x in range(5, 13) if d(x) != old["day"]][:1]
    body = {"reason_code": "no_crew", "slots": [{"day": d(other[0]), "half": "pm"}]}
    assert api.post(f"/vendor/visits/{f['visit']}/propose", json=body).status_code == 200
    use(api, f["token"])
    _ev, log = call(
        script,
        api,
        f["pid"],
        "처음 고른 날로 할래요",
        ("propose_visit_slot", {"slot_ref": old["ref"]}),
    )
    out = results(log)[0]
    assert out.get("error") is None and out["summary"]["approve_label"] == "이 날짜로 다시 고르기"


def test_repick_pick_keeps_the_proposal_when_the_pick_fails(api):
    from app.visit import flow
    from app.visit.schemas import SlotIn

    f = proposed(api)

    def go(s, user):
        data = SlotIn(day=day(20), half="am")  # 처음 기간(5 ~ 12일) 밖
        return flow.repick_pick(
            s, user, uuid.UUID(f["pid"]), uuid.UUID(f["visit"]), data, datetime.now(UTC)
        )

    with pytest.raises(AppError) as e:
        run(with_user(user_id("home@mitjip.test"), go))
    assert e.value.code == "invalid"
    assert visit_status(f["visit"]) == "proposed"  # 다시 고르기도 같이 되돌려요
    assert query("select status from visit_proposals")[0]["status"] == "open"


# ---- M1: 같은 업체 두 번째 요청 ----


def test_cancel_card_of_a_second_request_says_it_cannot_be_asked_again(api, script):
    f = second_try(api)
    _ev, log = call(
        script, api, f["pid"], "요청 취소해 줘", ("propose_visit_cancel", {"code": "other"})
    )
    got = results(log)[0]
    assert rows_of(got)["다시 요청"] == "이 업체엔 다시 요청할 수 없어요"
    assert "다시 요청할 수 없어요" in got["note"]


def test_cancel_card_of_a_first_request_has_no_last_try_row(api, script):
    f = requested(api)
    _ev, log = call(
        script, api, f["pid"], "요청 취소해 줘", ("propose_visit_cancel", {"code": "other"})
    )
    got = results(log)[0]
    assert "다시 요청" not in rows_of(got) and "다시 요청할 수 없어요" not in got["note"]


def test_need_cancel_warns_before_cancelling_a_second_request(api, script):
    _, pid, _vid, visit = home_requested(api)
    cancel(api, pid, visit)
    assert api.post(f"/projects/{pid}/visits/{visit}/again").status_code == 201
    _ev, log = call(
        script,
        api,
        pid,
        "집 면적이 전용 84㎡예요, 고쳐 줘",
        ("propose_home_info", {"fields": {"area_m2": 84, "area_basis": "exclusive"}}),
    )
    got = results(log)[0]
    assert got["step"] == propose.NEED_CANCEL
    assert "마루와벽" in got["note"] and "다시 요청할 수 없어요" in got["note"]


def test_blocked_vendor_reason_in_picks_and_request(api, script):
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    _token, pid = customer(api)
    _ev, log = call(script, api, pid, "업체 추천해 줘", ("recommend_vendors", {"trade": "dobae"}))
    assert results(log)[0]["picks"][0]["name"] == "마루와벽"  # v1
    assert add(api, pid, vid).status_code == 201 and ask_visits(api, pid, [vid]).status_code == 201
    first = visit_of(pid, vid)
    cancel(api, pid, first)
    r = api.post(f"/projects/{pid}/visits/{first}/again")
    assert r.status_code == 201, r.text
    cancel(api, pid, r.json()["visit_id"])  # 두 번째 요청도 취소: 이 공사에는 다시 요청할 수 없어요
    _ev, log = call(
        script,
        api,
        pid,
        "마루와벽에 다시 실측 요청해 주세요",
        ("recommend_vendors", {"trade": "dobae"}),
        ("propose_visit_request", {"trade": "dobae", "vendor_refs": ["v1"]}),
    )
    picks, req = results(log, 1)[0], results(log, 2)[0]
    (why,) = picks["why"]  # 지역에 업체가 없다고 하지 않고 막힌 까닭 하나(note에 겹쳐 쓰지 않아요)
    assert "마루와벽" in why and "두 번" in why and "다시 요청할 수 없어" in why
    assert why not in picks.get("note", "")
    assert req["error"] == "blocked_retry" and "마루와벽" in req["message"]
    assert "다시 요청할 수 없어요" in req["message"]


def test_blocked_vendor_reason_rides_along_with_other_picks(api, script):
    """c3 T9 · T10: 다른 업체 추천은 나오는데 바란 업체가 까닭 없이 빠졌어요."""
    maru = vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    _token, pid = customer(api)
    assert (
        add(api, pid, maru).status_code == 201 and ask_visits(api, pid, [maru]).status_code == 201
    )
    first = visit_of(pid, maru)
    cancel(api, pid, first)
    r = api.post(f"/projects/{pid}/visits/{first}/again")
    assert r.status_code == 201, r.text
    cancel(api, pid, r.json()["visit_id"])
    _ev, log = call(script, api, pid, "업체 추천해 줘", ("recommend_vendors", {"trade": "dobae"}))
    got = results(log)[0]
    assert [x["name"] for x in got["picks"]] == ["결도배"]
    assert "마루와벽에는 이 공사에서 이미 두 번 요청해서" in got["note"]


# ---- 낮음: 실측 말 ----


def test_slot_card_words_follow_the_visit_words():
    w = SimpleNamespace(
        start=date(2026, 12, 14),
        end=date(2026, 12, 18),
        pick_due_at=datetime(2026, 12, 13, 9, tzinfo=SEOUL),
        instant=False,
    )
    v = SimpleNamespace(
        status="offered", window=w, proposal=None, vendor_name="마루와벽", visit_id=uuid.uuid4()
    )
    got = propose.slot_offer(v, {"via": "pick", "day": "2026-12-15", "half": "am"})["summary"]
    assert got.version == "실측 가능 기간 12.14(월)~12.18(금)"
    assert got.approve_label == "이 날짜로 고르기"
    assert runtime.CHIPS["visit_slots"][0][0] == "다른 날짜도 볼래요"
    assert free.SLOTS_OTHER.search("다른 날짜도 볼래요")
    for text in ("시간", "반나절"):
        assert text not in f"{got.version}{got.approve_label}{got.note}"


# ---- 낮음: 콕 집은 요일 먼저 ----


def test_named_weekday_comes_before_the_other_weekend_day():
    sat = date(2026, 12, 12)  # 토요일
    sun = sat + timedelta(days=1)
    days = [slots.DayOpen(sat, 2, 2), slots.DayOpen(sun, 2, 2)]
    work = sun + timedelta(days=22)  # 희망일 − 20일 = 일요일 다음 날: 일요일이 더 가까워요
    old = slots.candidates(days, work, sat - timedelta(days=5), day_prefer="weekend", n=1)
    assert old[0].day == sun  # 주말로만 보면 일요일이 먼저
    got = slots.candidates(
        days, work, sat - timedelta(days=5), day_prefer="weekend", n=1, named=frozenset({5})
    )
    assert got[0].day == sat and "prefer_day" in got[0].why
    # 요일을 말하지 않고(any) 토요일만 콕 집어도 토요일 먼저
    got = slots.candidates(days, work, sat - timedelta(days=5), n=1, named=frozenset({5}))
    assert got[0].day == sat


def test_said_saturday_comes_first_on_the_slot_card(api, script):
    f = offered(api)  # 업체 기간 오늘 + 5 ~ 12일(주말이 한 번은 다 들어 있어요)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "평일엔 회사라 토요일이 좋아요",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "weekend"}),
    )
    first = results(log, 2)[0]["candidates"][0]
    assert date.fromisoformat(first["day"]).weekday() == 5


# ---- 낮음: 요청 뒤 요일 바꾸기 길 ----


def test_requested_visit_tells_the_ways_to_get_the_named_day(api, script):
    f = requested(api)  # 희망 기간 오늘 + 2 ~ 16일(토요일이 들어 있어요)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "실측 날짜를 토요일로 바꿀 수 있어요? 평일엔 회사라서요",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", "prefer": "any", "days": "weekend"}),
    )
    got = results(log, 2)[0]
    assert "요청은 그대로 두면" in got["note"]
    sats = [x for x in range(2, 17) if day(x).weekday() == 5]
    assert got["days"] and all("(토)" in x for x in got["days"])
    assert len(got["days"]) == min(len(sats), 4)


# ---- 낮음: 취소 메모는 상태마다 ----


def test_cancel_note_follows_the_request_state(api, script):
    f = booked(api)  # 오늘 + 6일 오전 실측 확정
    _ev, log = call(
        script, api, f["pid"], "요청 취소해 줘", ("propose_visit_cancel", {"code": "other"})
    )
    note = results(log)[0]["summary"]["note"]
    assert f"정해진 실측 날짜 {cards.md_long(day(6))} 오전" in note and "취소돼요" in note


def test_cancel_note_without_a_date_does_not_talk_about_dates(api, script):
    f = requested(api)
    _ev, log = call(
        script, api, f["pid"], "요청 취소해 줘", ("propose_visit_cancel", {"code": "other"})
    )
    assert "실측 날짜" not in results(log)[0]["summary"]["note"]


# ---- 낮음: 실측 확정 할 일 줄 ----


def test_progress_says_the_visit_date_is_set():
    base = TradeFacts(
        trade="dobae",
        created_on=date(2026, 11, 2),
        standard_on=date(2026, 11, 2),
        asked=2,
        asked_on=date(2026, 11, 2),
        quotes=0,
        waiting=0,
        quoted_on=None,
    )
    now = datetime(2026, 11, 8, 3, tzinfo=UTC)
    assert progress(base, date(2026, 11, 8), now).todo == "visit_requested"
    one = TradeFacts(**{**base.__dict__, "booked": 1})
    assert progress(one, date(2026, 11, 8), now).todo == "visit_requested"  # 한 곳은 아직 맞추는 중
    both = TradeFacts(**{**base.__dict__, "booked": 2})
    assert progress(both, date(2026, 11, 8), now).todo == "visit_booked"


def test_overview_todo_after_the_visit_is_booked(api):
    f = booked(api)
    t = api.get(f"/projects/{f['pid']}/overview").json()["trades"][0]["todo"]
    assert t["code"] == "visit_booked" and t["text"].startswith("실측 날짜가 정해졌어요")


# ---- 낮음: 오늘 정할 일은 같은 일을 한 줄로 ----


def test_today_shows_one_line_for_a_slot_card_and_its_pick_turn(api, script):
    f = offered(api, instant=False)
    ev, log = call(
        script,
        api,
        f["pid"],
        "실측 날짜 골라 줘",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS}),
        ("propose_visit_slot", {"slot_ref": "s1"}),
    )
    # 알림 '기간을 보냈어요. 실측 날짜를 골라 주세요'는 종 알림(카드 칸)에 그대로 있고, 모델 값 새 소식에서는 같은 일인
    # 고객 줄(날짜 고를 차례)이 맡아요
    (first,) = cards_of(ev, "today")
    assert any("기간을 보냈어요" in x["title"] for x in first["data"]["news"])
    assert not any("기간을 보냈어요" in x["title"] for x in results(log, 1)[0].get("news", []))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    ev, log = call(script, api, f["pid"], "오늘 뭐 해요?", ("today_tasks", {}))
    (card,) = cards_of(ev, "today")
    ids = [r["id"] for r in card["data"]["todo"]]
    assert f"a-{a['action_id']}" in ids and f"v-{f['visit']}" not in ids
    got = results(log)[0]
    item = next(x for x in got["todo"] if x.get("kind") == "visit_slot")
    assert item["ref"] == "m1" and item["next"] == "날짜 고를 차례"
    assert not any("기간을 보냈어요" in x["title"] for x in got.get("news", []))  # 같은 일은 한 줄

"""v3 실측 일정 J5 길 (dev-04): 업체 기간 → 고객 반나절(바로 확정 · 수락 기다림) → 수락 · 다른 날 제안 ·
다시 고르기 → 확정(채팅 · 기한 일 · 알림) · 취소 · 못 받아요 · 실측 뒤(받았어요 · 안 왔어요 · 견적서) ·
다시 받기 · 캘린더 파일 · 업체 일정 · 업체 화면에 고객 이름 · 연락처 · 동 · 호 없음."""

import uuid
from datetime import UTC

from app.calc import deadline
from app.calc.visit_view import half_span
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v3_visit_kit import (
    CUSTOMER_NAME,
    PHONE,
    answer,
    booked,
    choose,
    d,
    day,
    notes,
    offered,
    pending_jobs,
    picked,
    requested,
    status,
)
from tests.test_vendor_quote import FULL, doc
from tests.test_visit_inbox import login


def code(r) -> tuple[int, str]:
    return r.status_code, r.json().get("error", {}).get("code", "")


def view(api, f: dict) -> dict:
    r = api.get(f"/projects/{f['pid']}/visits/{f['visit']}")
    assert r.status_code == 200, r.text
    return r.json()


def row(api, f: dict) -> dict:
    got = api.get(f"/projects/{f['pid']}/visits", params={"trade": "dobae"}).json()
    return next(r for r in got["board"] if r["visit_id"] == f["visit"])


def test_window_then_instant_pick_books_and_opens_thread(api):
    f = requested(api)
    login(api, f["email"])
    r = answer(api, f["visit"], start=5, end=12, excluded=(7,), instant=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (
        out["status"] == "offered" and out["open_halves"] == 7 * 2 * 2
    )  # 7일 × 반나절 2 × 칸 2(L03)
    (w,) = query("select * from visit_windows")
    assert w["pick_due_at"] == deadline.pick_due(w["answered_at"])  # 답 + 7일 (D09)
    assert [str(x) for x in w["excluded"]] == [d(7)] and w["instant"] is True
    assert pending_jobs(f["visit"], "visit_reply_due") == []
    assert [j["run_at"] for j in pending_jobs(f["visit"], "visit_pick_due")] == [w["pick_due_at"]]
    assert code(answer(api, f["visit"])) == (409, "stale")  # 두 번 답하기
    (n,) = notes("home@mitjip.test", "visit_offered")
    assert n["link"] == f"/projects/{f['pid']}/visits/{f['visit']}"

    use(api, f["token"])
    v = view(api, f)
    assert (v["status"], v["instant"], v["overlap"], v["ways"]) == ("offered", True, True, [])
    days = {x["day"]: x for x in v["days"]}
    assert days[d(7)] == {"day": d(7), "am": False, "pm": False, "am_left": 0, "pm_left": 0}
    assert days[d(5)]["am_left"] == 2 and v["full"] == []
    assert v["recommend"] == {  # 공사 시작(오늘 + 30일) − 20일에 가장 가까운 칸
        "day": d(10),
        "half": "am",
        "target": d(10),
        "basis": "start_minus_20",
    }
    assert v["next"]["kind"] == "pick" and v["next"]["who"] == "customer"
    assert code(choose(api, f["pid"], f["visit"], n=7)) == (422, "invalid")  # 빼는 날
    assert code(choose(api, f["pid"], f["visit"], n=13)) == (422, "invalid")  # 기간 밖

    r = choose(api, f["pid"], f["visit"], n=6, half="am")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "booked" and got["thread_id"]
    assert got["booked"] == {"day": d(6), "half": "am", "kind": "booked", "hold_until": None}
    (h,) = query("select seat, kind, status, until from visit_holds")
    assert (h["seat"], h["kind"], h["status"], h["until"]) == (1, "booked", "active", None)
    (vr,) = query("select booked_day, booked_half, quote_due_at, status from visits")
    assert (str(vr["booked_day"]), vr["booked_half"], vr["status"]) == (d(6), "am", "booked")
    assert vr["quote_due_at"] == deadline.quote_due(day(6))  # 실측일 + 3일 18:00
    (t,) = query("select id, status, customer_label, area_label from threads")
    assert str(t["id"]) == got["thread_id"] and t["status"] == "open"
    assert t["customer_label"] == "노원구 고객" and CUSTOMER_NAME not in t["customer_label"]
    msgs = query("select system_code from thread_messages")
    assert [m["system_code"] for m in msgs] == ["visit_booked"]
    assert pending_jobs(f["visit"], "visit_pick_due") == []
    assert [j["run_at"] for j in pending_jobs(f["visit"], "visit_reminder")] == [
        deadline.reminder_at(day(6))
    ]
    assert [j["run_at"] for j in pending_jobs(f["visit"], "visit_quote_due")] == [
        vr["quote_due_at"]
    ]
    assert len(notes("home@mitjip.test", "visit_booked")) == 1
    (vn,) = notes(f["email"], "visit_booked")
    assert vn["link"] == f"/vendor/requests/{f['visit']}" and CUSTOMER_NAME not in vn["body"]
    assert code(choose(api, f["pid"], f["visit"], n=8)) == (409, "stale")  # 이미 확정

    b = row(api, f)
    assert (b["status"], b["thread_id"], b["next"]["kind"]) == ("booked", got["thread_id"], "visit")
    assert b["can"]["change"] is True and b["can"]["visited"] is False and b["can"]["cancel"]
    ics = api.get(f"/projects/{f['pid']}/visits/{f['visit']}/ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    start, end = half_span(day(6), "am")  # 오전 09:00 ~ 13:00 (서울)
    assert f"DTSTART:{start.astimezone(UTC):%Y%m%dT%H%M%SZ}" in ics.text
    assert f"DTEND:{end.astimezone(UTC):%Y%m%dT%H%M%SZ}" in ics.text
    assert "LOCATION" not in ics.text and "BEGIN:VEVENT" in ics.text
    assert all(len(x.encode()) <= 75 for x in ics.text.split("\r\n"))  # 줄 접기 (RFC 5545)

    login(api, f["email"])
    sched = api.get("/vendor/schedule", params={"from": d(1), "to": d(30)})
    assert sched.status_code == 200, sched.text
    (item,) = sched.json()["items"]
    assert (item["day"], item["half"], item["kind"], item["seat"]) == (d(6), "am", "booked", 1)
    assert item["area_label"].startswith("노원구") and sched.json()["capacity"] == 2
    assert code(api.get("/vendor/schedule", params={"from": d(1), "to": d(70)})) == (422, "invalid")


def test_pick_holds_then_vendor_accepts(api):
    f = picked(api)
    (h,) = query("select kind, until, created_at from visit_holds where status = 'active'")
    assert h["kind"] == "hold" and h["until"] == deadline.accept_due(h["created_at"])  # + 48시간
    assert status(f["visit"]) == "picked"
    assert [j["run_at"] for j in pending_jobs(f["visit"], "visit_accept_due")] == [h["until"]]
    b = row(api, f)
    assert b["next"]["kind"] == "accept" and b["booked"]["kind"] == "hold"
    (n,) = notes(f["email"], "visit_picked")
    assert n["link"] == f"/vendor/requests/{f['visit']}"

    login(api, f["email"])
    r = api.post(f"/vendor/visits/{f['visit']}/accept")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "booked" and got["thread_id"] and got["booked"]["kind"] == "booked"
    (h,) = query("select kind, until from visit_holds where status = 'active'")
    assert (h["kind"], h["until"]) == ("booked", None)
    assert pending_jobs(f["visit"], "visit_accept_due") == []
    assert code(api.post(f"/vendor/visits/{f['visit']}/accept")) == (409, "stale")


def test_propose_then_pick_proposal(api):
    f = picked(api)
    login(api, f["email"])
    url = f"/vendor/visits/{f['visit']}/propose"
    outside = {"reason_code": "other_site", "slots": [{"day": d(20), "half": "am"}]}
    assert code(api.post(url, json=outside)) == (422, "invalid")  # 고객 희망 기간(2 ~ 16일) 밖
    body = {
        "reason_code": "other_site",
        "note": "오전은 다른 현장이에요",
        "slots": [{"day": d(7), "half": "pm"}, {"day": d(8), "half": "am"}],
    }
    r = api.post(url, json=body)
    assert r.status_code == 200 and r.json()["status"] == "proposed", r.text
    assert query("select count(*) n from visit_holds where status = 'active'")[0]["n"] == 0
    (p,) = query("select id, status, reason_code, note, due_at, created_at from visit_proposals")
    assert (p["status"], p["reason_code"]) == ("open", "other_site")
    assert p["due_at"] == deadline.proposal_due(p["created_at"])
    assert [j["kind"] for j in pending_jobs(p["id"])] == ["visit_proposal_due"]
    assert pending_jobs(f["visit"], "visit_accept_due") == []
    assert len(notes("home@mitjip.test", "visit_proposed")) == 1

    use(api, f["token"])
    v = view(api, f)
    assert v["proposal"]["slots"] == body["slots"] and v["status"] == "proposed"
    assert row(api, f)["can"]["pick"] is True and row(api, f)["next"]["kind"] == "proposal"
    url = f"/projects/{f['pid']}/visits/{f['visit']}/proposal/pick"
    assert code(api.post(url, json={"day": d(9), "half": "am"})) == (422, "invalid")  # 제안 밖
    r = api.post(url, json={"day": d(8), "half": "am"})
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text
    assert query("select status from visit_proposals")[0]["status"] == "picked"
    assert pending_jobs(p["id"]) == []
    ev = query(
        "select code from visit_events where visit_id = $1 order by at", uuid.UUID(f["visit"])
    )
    assert [e["code"] for e in ev] == ["asked", "answered", "picked", "proposed", "proposal_picked"]


def test_repick_goes_back_to_offered(api):
    f = picked(api)
    login(api, f["email"])
    body = {"reason_code": "no_crew", "slots": [{"day": d(9), "half": "pm"}]}
    assert api.post(f"/vendor/visits/{f['visit']}/propose", json=body).status_code == 200
    use(api, f["token"])
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/repick")
    assert r.status_code == 200 and r.json()["status"] == "offered", r.text
    assert r.json()["next"]["kind"] == "pick"
    assert query("select status from visit_proposals")[0]["status"] == "repicked"
    again = choose(api, f["pid"], f["visit"], n=6, half="pm")
    assert again.status_code == 200 and again.json()["status"] == "picked"  # 바로 확정 끔


def test_cancel_after_booked_cleans_up(api):
    f = booked(api)
    tid = str(query("select id from threads")[0]["id"])
    url = f"/projects/{f['pid']}/visits/{f['visit']}/cancel"
    r = api.post(url, json={"code": "other", "note": "이사 날짜가 바뀌었어요"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["contact"] is None
    (vr,) = query("select status, cancel_code, cancel_note from visits")
    assert (vr["cancel_code"], vr["cancel_note"]) == ("other", "이사 날짜가 바뀌었어요")
    assert query("select status from visit_holds")[0]["status"] == "released"
    (sl,) = query("select status, removed_code from shortlists")
    assert (sl["status"], sl["removed_code"]) == ("removed", "cancelled")  # 칸이 빈다
    (t,) = query("select status, ro_reason from threads")
    assert (t["status"], t["ro_reason"]) == ("read_only", "cancelled")
    codes = [
        m["system_code"] for m in query("select system_code from thread_messages order by seq")
    ]
    assert codes == ["visit_booked", "visit_cancelled"]
    assert pending_jobs(f["visit"]) == []
    assert [n["kind"] for n in notes(f["email"])][-1] == "visit_cancelled"
    assert code(api.post(url, json={"code": "other"})) == (409, "stale")
    ev = query("select from_status, code from visit_events where to_status = 'cancelled'")
    assert [(e["from_status"], e["code"]) for e in ev] == [("booked", "cancelled")]
    login(api, f["email"])
    assert api.get("/vendor/schedule", params={"from": d(1), "to": d(30)}).json()["items"] == []
    assert tid


def test_decline_with_note(api):
    f = requested(api)
    login(api, f["email"])
    r = api.post(
        f"/vendor/visits/{f['visit']}/decline", json={"code": "other", "note": "그날 바빠요"}
    )
    assert r.status_code == 200 and r.json()["status"] == "declined", r.text
    (vr,) = query("select decline_code, decline_note from visits")
    assert (vr["decline_code"], vr["decline_note"]) == ("other", "그날 바빠요")
    assert query("select removed_code from shortlists")[0]["removed_code"] == "declined"
    assert pending_jobs(f["visit"]) == []
    assert code(answer(api, f["visit"])) == (409, "stale")
    assert len(notes("home@mitjip.test", "visit_declined")) == 1


def test_visited_after_the_half_then_quote(api):
    f = booked(api)
    url = f"/projects/{f['pid']}/visits/{f['visit']}/visited"
    assert code(api.post(url, json={"result": "visited"})) == (409, "stale")  # 실측 시각 전
    query("update visits set booked_day = current_date - 1")
    r = api.post(url, json={"result": "visited"})
    assert r.status_code == 200 and r.json()["status"] == "visited", r.text
    assert r.json()["next"]["kind"] == "quote"
    assert query("select visited_at from visits")[0]["visited_at"] is not None
    assert code(api.post(url, json={"result": "visited"})) == (409, "stale")

    login(api, f["email"])
    qurl = f"/vendor/visits/{f['visit']}/quote"
    assert api.put(qurl, json={"file_ids": [doc(api)], **FULL}).status_code == 200
    sent = api.post(f"{qurl}/send")
    assert sent.status_code == 200, sent.text
    assert status(f["visit"]) == "quoted"
    assert pending_jobs(f["visit"], "visit_quote_due") == []
    codes = [
        m["system_code"] for m in query("select system_code from thread_messages order by seq")
    ]
    assert codes == ["visit_booked", "quote_sent"]
    ev = query("select from_status, code from visit_events where to_status = 'quoted'")
    assert [(e["from_status"], e["code"]) for e in ev] == [("visited", "quote_sent")]


def test_no_show_frees_the_slot(api):
    f = booked(api)
    query("update visits set booked_day = current_date - 1")
    url = f"/projects/{f['pid']}/visits/{f['visit']}/visited"
    r = api.post(url, json={"result": "no_show"})
    assert r.status_code == 200 and r.json()["status"] == "no_show", r.text
    assert query("select removed_code from shortlists")[0]["removed_code"] == "no_show"
    assert query("select status from visit_holds")[0]["status"] == "released"
    assert len(notes(f["email"], "visit_no_show")) == 1
    assert pending_jobs(f["visit"]) == []


def test_quote_needs_a_booked_visit_and_requote(api):
    f = offered(api)
    login(api, f["email"])
    qurl = f"/vendor/visits/{f['visit']}/quote"
    assert api.put(qurl, json={"file_ids": [doc(api)], **FULL}).status_code == 409  # 실측 전
    use(api, f["token"])
    assert choose(api, f["pid"], f["visit"]).status_code == 200
    login(api, f["email"])
    assert api.put(qurl, json={"file_ids": [doc(api)], **FULL}).status_code == 200
    assert code(api.post(f"{qurl}/send")) == (409, "before_visit")  # 실측 날 전(QA r6 화면 M1)
    query("update visits set booked_day = current_date where id = $1", uuid.UUID(f["visit"]))
    assert api.post(f"{qurl}/send").status_code == 200  # 실측 날부터는 확정 상태에서 바로 보내기
    use(api, f["token"])
    rq = f"/projects/{f['pid']}/visits/{f['visit']}/requote"
    assert code(api.post(rq)) == (409, "stale")  # 아직 유효기간 안
    query("update vendor_quotes set valid_until = current_date - 1")
    assert row(api, f)["can"]["requote"] is True
    r = api.post(rq)
    assert r.status_code == 200 and r.json()["status"] == "quoted", r.text
    assert query("select requote_at from visits")[0]["requote_at"] is not None
    assert code(api.post(rq)) == (409, "already")
    (n,) = notes(f["email"], "requote_requested")
    assert n["link"] == f"/vendor/requests/{f['visit']}/quote"
    assert row(api, f)["can"]["requote"] is False


def test_vendor_detail_has_calendar_and_no_customer_privates(api):
    f = booked(api)
    query(
        "update projects set apt_name = '믿집시험아파트', dong = '쿠동', ho = '퀘호',"
        " emd = '상계동', budget_won = 3000000"
    )
    g = requested(api, customer_email="two@mitjip.test", vid=f["vendor"])
    login(api, f["email"])
    for path in (
        f"/vendor/visits/{f['visit']}",
        f"/vendor/visits/{g['visit']}",
        f"/vendor/schedule?from={d(1)}&to={d(30)}",
    ):
        r = api.get(path)
        assert r.status_code == 200, (path, r.text)
        for secret in (CUSTOMER_NAME, PHONE, "믿집시험아파트", "쿠동", "퀘호"):
            assert secret not in r.text, (path, secret)
    det = api.get(f"/vendor/visits/{g['visit']}").json()
    assert "customer" not in det and det["share_contact"] is False  # B3
    assert (det["wish_start"], det["wish_end"], det["attempt"]) == (d(2), d(16), 1)
    assert det["home"] == "아파트 · 도배 전체 · 빈 집" and det["area_label"].startswith("노원구")
    assert det["state"] == {"icon": "todo", "label": "새 실측 요청"}
    assert det["next"]["label"] == "기간 답하기" and det["reply_due_at"]
    assert det["capacity"] == 2 and det["instant_default"] is False
    assert det["window"] is None and det["thread_id"] is None
    assert det["open_count"] == 15 * 2 * 2 - 1  # 희망 2 ~ 16일 × 반나절 2 × 칸 2, 6일 오전 1칸 잡힘
    assert [(x["day"], x["half"], x["kind"]) for x in det["taken"]] == [(d(6), "am", "booked")]
    assert det["when_text"].count("~") == 1
    mine = api.get(f"/vendor/visits/{f['visit']}").json()
    assert mine["area_label"] == "노원구 상계동 · 공급 105.8㎡" and mine["budget_won"] == 3_000_000
    assert mine["state"]["label"] == "실측 확정" and mine["booked"]["day"] == d(6)
    assert mine["thread_id"] and mine["window"]["start"] == d(5)
    signup(api, "x@mitjip.test")
    assert api.get(f"/vendor/visits/{f['visit']}").status_code == 403

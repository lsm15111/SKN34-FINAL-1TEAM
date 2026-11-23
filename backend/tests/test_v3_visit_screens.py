"""v3 화면 묶음 칸 (B2a · B2b · B3): 고른 벽지로 담기 · 요청 · 한 번 더(C11) · 업체 자세히 벽지 · 차이 뜻 ·
답 시간 · 별점(I4) · 다른 날 제안 고를 거리 · 기간 미리 세기(V04 · V07) · 날짜 고르기 몇 번째 · 겹치는 날 없음
까닭(C22) · 견적 비교 차이 · 알림 시각(C33) · 업체 멈춤 때 닫기(D26) · 새 알림 kind · 시스템 카드 줄기."""

import uuid
from datetime import timedelta

from app.calc import deadline
from app.db import SessionLocal
from app.shared.clock import now_utc, today_seoul
from app.visit import service
from tests.conftest import query
from tests.helpers import use
from tests.test_deal import confirm, setup
from tests.test_v3_shortlist_api import fake_v3
from tests.test_v3_visit_kit import (
    add,
    answer,
    ask,
    booked,
    choose,
    customer,
    d,
    day,
    handle,
    notes,
    picked,
    requested,
    run,
    status,
    user_id,
    vendor,
    visit_of,
)
from tests.test_v3_visit_photos import photo
from tests.test_v3_visit_request import stream
from tests.test_vendor_quote import FULL, doc, url
from tests.test_visit_inbox import login

WORK = "노원구 도배"  # 업체 알림 끝 공사 이름 (B2b, 시험 집은 동이 없다)
MIN = timedelta(minutes=1)


def code(r) -> tuple[int, str]:
    return r.status_code, r.json().get("error", {}).get("code", "")


def shortlist(api, pid: str, vid: str, grade: str | None = None, trade: str = "dobae"):
    body = {"trade": trade, "vendor_id": vid} | ({"grade": grade} if grade else {})
    return api.post(f"/projects/{pid}/shortlist", json=body)


def send_quote(api, visit: str, total: int) -> None:
    """업체로 로그인한 채: 실측 견적서 임시 저장 → 보내기 (부가세 포함 금액)"""
    body = {**FULL, "entered_amount": total, "vat_mode": "included", "file_ids": [doc(api)]}
    assert api.put(url(visit), json=body).status_code == 200
    r = api.post(f"{url(visit)}/send")
    assert r.status_code == 200, r.text


def msgs(who) -> list[int]:
    return [x["seq"] for e, x in stream(who) if e == "msg"]


def test_grade_on_shortlist_request_and_again(api, monkeypatch):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    fake_v3(monkeypatch, {a: {"basic": 3_186_150, "economy": 2_874_300}, b: {"basic": 3_300_000}})
    _, pid = customer(api)  # 공사 벽지: 실크(basic)
    assert code(shortlist(api, pid, a, "economy", trade="mokgong"))[0] == 422  # 벽지는 도배만
    r = shortlist(api, pid, a, "economy")
    assert r.status_code == 201, r.text
    (item,) = r.json()["items"]
    assert (item["grade"], item["estimate_total"]) == ("economy", 2_874_300)
    assert shortlist(api, pid, b).json()["items"][1]["grade"] is None  # 비면 공사 벽지
    draft = api.get(f"/projects/{pid}/visits/draft", params={"trade": "dobae"}).json()
    assert [(x["grade"], x["estimate_total"]) for x in draft["vendors"]] == [
        ("economy", 2_874_300),
        ("basic", 3_300_000),
    ]
    p1 = photo(api)
    r = ask(api, pid, [a, b], photos=[{"file_id": p1, "label": "거실"}])
    assert r.status_code == 201, r.text
    rows = {
        str(x["vendor_id"]): (x["grade"], x["estimate_total"])
        for x in query("select vendor_id, grade, estimate_total from visits")
    }
    assert rows == {a: ("economy", 2_874_300), b: ("basic", 3_300_000)}  # 사본도 그 벽지 값

    va = visit_of(pid, a)
    due = query("select reply_due_at from visits where id = $1", uuid.UUID(va))[0]["reply_due_at"]
    handle("visit_reply_due", va, due + MIN)
    again = api.post(f"/projects/{pid}/visits/{va}/again")
    assert again.status_code == 201, again.text
    new = query("select id, grade, estimate_total from visits where attempt = 2")[0]
    assert (new["grade"], new["estimate_total"]) == ("economy", 2_874_300)
    kept = query("select file_id, label from visit_photos where visit_id = $1", new["id"])
    assert [(str(x["file_id"]), x["label"]) for x in kept] == [(p1, "거실")]  # 사진도 그대로
    pick = api.get(f"/projects/{pid}/visits/{again.json()['visit_id']}").json()
    assert pick["attempt"] == 2  # D16 '한 번 더 요청'


def test_vendor_detail_grade_diff_and_reply_hours(api, monkeypatch):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    fake_v3(monkeypatch, {a: {"basic": 3_186_150, "economy": 2_874_300}})
    token, pid = customer(api)
    page = f"/projects/{pid}/vendors/{a}"
    got = api.get(page, params={"trade": "dobae"}).json()
    assert (got["grade"], got["estimate_v3"]["total"]) == ("basic", 3_186_150)
    assert got["grade_diff"] == -311_850  # 다른 벽지(합지) − 보여 준 벽지(실크)
    assert got["reply_hours"] is None and got["rating"]["count"] == 0
    got = api.get(page, params={"trade": "dobae", "grade": "economy"}).json()
    assert (got["grade"], got["estimate_v3"]["total"]) == ("economy", 2_874_300)
    assert got["grade_diff"] == 311_850  # 다른 벽지(실크) − 보여 준 벽지(합지)

    assert add(api, pid, a).status_code == 201 and ask(api, pid, [a]).status_code == 201
    login(api, "maru@mitjip.test")
    assert answer(api, visit_of(pid, a)).status_code == 200
    query(
        "update visits t set created_at = w.answered_at - interval '30 hours'"
        " from visit_windows w where w.visit_id = t.id"
    )
    use(api, token)
    assert api.get(page, params={"trade": "dobae"}).json()["reply_hours"] == 30  # 가운데 값(시간)


def test_ratings_on_cards_detail_and_compare(api):
    _, pid, va, vb, _ = setup(api)  # 마루와벽 · 결도배 견적서 옴 (v2 길)
    maru = str(query("select vendor_id from visits where id = $1", uuid.UUID(va))[0]["vendor_id"])
    assert confirm(api, pid, va).status_code == 200
    query(
        "update deals set status = 'done', start_date = current_date - 5,"
        " end_date = current_date - 3, work_done_on = current_date - 3"
    )
    review = (
        "insert into reviews (id, vendor_id, rating, tags, context_label, status, hidden_code)"
        " values (gen_random_uuid(), $1, $2, $3, '노원구 아파트 · 실크', $4, $5)"
    )
    vid = uuid.UUID(maru)
    query(review, vid, 5, ["seam", "kind"], "shown", None)
    query(review, vid, 4, ["kind"], "shown", None)
    query(review, vid, 1, [], "hidden", "abuse")  # 숨긴 리뷰는 별점에서 빠진다
    cards = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()["local"]
    card = next(c for c in cards if c["vendor_id"] == maru)
    assert (card["rating"], card["review_count"], card["done_count"]) == ("4.5", 2, 1)
    other = next(c for c in cards if c["vendor_id"] != maru)
    assert (other["rating"], other["review_count"], other["done_count"]) == (None, 0, 0)
    detail = api.get(f"/projects/{pid}/vendors/{maru}", params={"trade": "dobae"}).json()
    assert detail["rating"] == {
        "avg": "4.5",
        "count": 2,
        "done_count": 1,
        "tags": {"seam": 1, "on_time": 0, "kind": 2, "tidy": 0},
    }
    rows = api.get(f"/projects/{pid}/quotes", params={"trade": "dobae"}).json()["vendors"]
    stars = {r["visit_id"]: r["rating"]["count"] for r in rows}
    assert stars == {va: 2} and vb not in stars  # 확정한 뒤 다른 요청은 닫혀 비교에서 빠진다


def test_propose_options_and_window_preview(api):
    f = picked(api)  # 고객이 오늘 + 6일 오전을 골라 수락 기다림 (업체 기간 5 ~ 12일)
    login(api, f["email"])
    det = api.get(f"/vendor/visits/{f['visit']}").json()
    options = [(x["day"], x["half"]) for x in det["propose_options"]]
    assert len(options) == 15 * 2 - 1 and options[0] == (
        d(2),
        "am",
    )  # 희망 2 ~ 16일, 고른 반나절 빼고
    assert (d(6), "am") not in options

    g = requested(api, customer_email="two@mitjip.test", vid=f["vendor"])
    login(api, f["email"])
    base = f"/vendor/visits/{g['visit']}"
    assert api.get(base).json()["open_count"] == 15 * 2 * 2 - 1  # 희망 기간, f가 잡은 6일 오전 1칸
    assert api.get(base).json()["propose_options"] == []  # 수락 기다릴 때만
    got = api.get(base, params={"start": d(5), "end": d(7), "excluded": [d(6)]}).json()
    assert got["open_count"] == 2 * 2 * 2  # 5 · 7일 × 반나절 2 × 칸 2 (보내기 전 미리 세기)
    bad = (
        {"start": d(5)},
        {"start": d(7), "end": d(5)},
        {"start": d(5), "end": d(7), "excluded": [d(9)]},
        {"start": d(5), "end": d(80)},
    )
    for params in bad:
        assert code(api.get(base, params=params)) == (422, "invalid"), params
    assert status(g["visit"]) == "requested"  # 미리 세기는 아무것도 바꾸지 않는다


def test_pick_view_no_overlap_reason(api):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = customer(api)  # 희망 기간 오늘 + 2 ~ 16일 · 공사 시작 희망일 오늘 + 30일
    assert add(api, pid, a).status_code == 201 and add(api, pid, b).status_code == 201
    assert ask(api, pid, [a, b]).status_code == 201
    va, vb = visit_of(pid, a), visit_of(pid, b)
    login(api, "maru@mitjip.test")
    assert answer(api, va, start=20, end=25).status_code == 200  # 희망 기간보다 늦음
    login(api, "gyeol@mitjip.test")
    assert answer(api, vb, start=31, end=35).status_code == 200  # 공사 시작보다도 늦음 (C22 예)
    use(api, token)
    one = api.get(f"/projects/{pid}/visits/{va}").json()
    assert (one["overlap"], one["no_overlap_reason"], one["attempt"]) == (False, "after_wish", 1)
    assert one["ways"] == ["ask_other", "other_vendor", "change_wish"]
    two = api.get(f"/projects/{pid}/visits/{vb}").json()
    assert two["no_overlap_reason"] == "after_work_start"


def test_compare_gap_and_v3_fields(api):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = customer(api)
    assert add(api, pid, a).status_code == 201 and add(api, pid, b).status_code == 201
    assert ask(api, pid, [a, b]).status_code == 201
    va, vb = visit_of(pid, a), visit_of(pid, b)
    for email, v, n in (("maru@mitjip.test", va, 6), ("gyeol@mitjip.test", vb, 7)):
        login(api, email)
        assert answer(api, v).status_code == 200
        use(api, token)
        assert choose(api, pid, v, n=n).json()["status"] == "booked"
    use(api, token)
    rows = api.get(f"/projects/{pid}/quotes", params={"trade": "dobae"}).json()["vendors"]
    assert {r["visit_id"]: r["status"] for r in rows} == {
        va: "booked",
        vb: "booked",
    }  # 견적서 기다림
    # 실측 날 전엔 견적서를 못 보내요(QA r6 화면 M1)
    query("update visits set booked_day = current_date")
    login(api, "maru@mitjip.test")
    send_quote(api, va, 3_080_000)
    login(api, "gyeol@mitjip.test")
    send_quote(api, vb, 3_487_000)
    for v, n in ((va, 6), (vb, 7)):  # 실측 날을 되돌려 비교 칸(visit_day)을 봐요
        query("update visits set booked_day = $1 where id = $2", day(n), uuid.UUID(v))
    use(api, token)
    got = api.get(f"/projects/{pid}/quotes", params={"trade": "dobae"}).json()
    assert got["gap_total"] == 407_000  # '두 곳이 40만 7,000원 차이 나요'
    est = {
        str(x["id"]): x["estimate_total"] for x in query("select id, estimate_total from visits")
    }
    until = today_seoul() + timedelta(days=14)
    for r in got["vendors"]:
        total = r["latest"]["total"]
        assert r["diff_vs_estimate"] == total - est[r["visit_id"]]
        assert r["visit_day"] == (d(6) if r["visit_id"] == va else d(7))
        assert r["valid_soon"] is False and r["requote_at"] is None
        assert r["valid_soon_at"] == [
            at.isoformat().replace("+00:00", "Z") for at in deadline.valid_soon_at(until)
        ]
        assert r["rating"]["count"] == 0


def test_close_for_vendor_closes_live_requests(api):
    f = requested(api)
    g = booked(api, customer_email="two@mitjip.test", vid=f["vendor"])
    _, third = customer(api, "three@mitjip.test")
    assert add(api, third, f["vendor"]).status_code == 201  # 담기만 한 집

    async def go() -> int:
        async with SessionLocal() as s:
            n = await service.close_for_vendor(s, uuid.UUID(f["vendor"]), now_utc())
            await s.commit()
            return n

    assert run(go()) == 2
    for v in (f["visit"], g["visit"]):
        row = query("select status, close_reason from visits where id = $1", uuid.UUID(v))[0]
        # 0035: 업체 멈춤 전용 값(전에는 reselected를 빌려 씀)
        assert (row["status"], row["close_reason"]) == ("closed", "vendor_stopped")
    assert query("select status from visit_holds")[0]["status"] == "released"
    left = query("select status, removed_code from shortlists")
    assert {(x["status"], x["removed_code"]) for x in left} == {("removed", "closed")}
    assert len(left) == 3  # 담기만 한 칸도 비운다
    live = query("select kind from jobs where status = 'pending'")
    assert live == []
    for email in ("home@mitjip.test", "two@mitjip.test"):
        (n,) = notes(email, "visit_vendor_stopped")  # 0035: 고객용 전용 kind
        assert "지금 믿집에서 일할 수 없는 업체라" in n["body"]
    assert run(go()) == 0  # 두 번째는 닫을 것이 없다


def test_new_notices_and_cards_reach_both_chats(api):
    f = booked(api)  # 대화 1번 글: 실측 확정 카드
    owner, ven = user_id("home@mitjip.test"), f["vendor"]
    base = f"/projects/{f['pid']}/visits/{f['visit']}"
    c = api.post(f"{base}/changes", json={"day": d(8), "half": "pm"}).json()
    (n,) = notes(f["email"], "visit_change_requested")
    assert n["body"].endswith(WORK)
    assert api.post(f"{base}/changes/{c['id']}/withdraw").status_code == 200
    (n,) = notes(f["email"], "visit_change_withdrawn")
    assert (n["body"], n["link"]) == (
        f"고객이 실측 일정 바꾸기 요청을 거뒀어요 · {WORK}",
        f"/vendor/requests/{f['visit']}",
    )
    c = api.post(f"{base}/changes", json={"day": d(9), "half": "am"}).json()
    login(api, f["email"])
    counter = {"slots": [{"day": d(10), "half": "pm"}]}
    r = api.post(f"/vendor/visits/{f['visit']}/changes/{c['id']}/propose", json=counter)
    assert r.status_code == 200, r.text
    use(api, f["token"])
    r = api.post(f"{base}/changes/{c['id']}/pick", json={"day": d(10), "half": "pm"})
    assert r.status_code == 200, r.text
    query("update visits set booked_day = current_date - 1")  # 실측 반나절이 끝났다
    assert api.post(f"{base}/visited", json={"result": "visited"}).status_code == 200
    (n,) = notes(f["email"], "visit_visited")
    assert n["body"].endswith(WORK) and n["link"] == f"/vendor/requests/{f['visit']}"
    login(api, f["email"])
    send_quote(api, f["visit"], 3_080_000)
    codes = [
        m["system_code"] for m in query("select system_code from thread_messages order by seq")
    ]
    assert codes == [
        "visit_booked",
        "change_requested",
        "change_requested",
        "change_countered",
        "change_done",
        "quote_sent",
    ]
    assert msgs(owner) == msgs(ven) == [1, 2, 3, 4, 5, 6]  # 카드마다 commit 뒤 두 사람 줄기에


def test_repick_notice_and_cancel_card(api):
    f = picked(api)
    login(api, f["email"])
    body = {"reason_code": "no_crew", "slots": [{"day": d(8), "half": "am"}]}
    assert api.post(f"/vendor/visits/{f['visit']}/propose", json=body).status_code == 200
    use(api, f["token"])
    assert api.post(f"/projects/{f['pid']}/visits/{f['visit']}/repick").status_code == 200
    (n,) = notes(f["email"], "visit_repicked")
    assert n["body"].endswith(WORK) and n["link"] == f"/vendor/requests/{f['visit']}"

    g = booked(api, customer_email="two@mitjip.test", vid=f["vendor"])
    r = api.post(f"/projects/{g['pid']}/visits/{g['visit']}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text
    (n,) = notes(f["email"], "visit_cancelled")
    assert n["body"] == f"고객이 실측 요청을 취소했어요 · {WORK}"
    assert msgs(user_id("two@mitjip.test")) == msgs(f["vendor"]) == [1, 2]  # 확정 · 취소 카드


def test_vendor_side_cards_reach_both_chats(api):
    f = picked(api)  # 업체 수락 → 실측 확정 카드
    login(api, f["email"])
    assert api.post(f"/vendor/visits/{f['visit']}/accept").status_code == 200
    use(api, f["token"])
    base = f"/projects/{f['pid']}/visits/{f['visit']}"
    c = api.post(f"{base}/changes", json={"day": d(8), "half": "pm"}).json()
    login(api, f["email"])
    assert api.post(f"/vendor/visits/{f['visit']}/changes/{c['id']}/accept").status_code == 200
    owner = user_id("home@mitjip.test")
    assert msgs(owner) == msgs(f["vendor"]) == [1, 2, 3]  # 확정 · 바꾸기 요청 · 바꿈

    g = picked(api, customer_email="two@mitjip.test", vid=f["vendor"])
    login(api, f["email"])
    body = {"reason_code": "other_site", "slots": [{"day": d(9), "half": "am"}]}
    assert api.post(f"/vendor/visits/{g['visit']}/propose", json=body).status_code == 200
    use(api, g["token"])
    url_ = f"/projects/{g['pid']}/visits/{g['visit']}/proposal/pick"
    assert api.post(url_, json={"day": d(9), "half": "am"}).status_code == 200  # 제안한 날 고름
    assert msgs(user_id("two@mitjip.test")) == [1]
    assert msgs(f["vendor"]) == [1, 2, 3, 1]  # 두 번째 대화의 1번 글

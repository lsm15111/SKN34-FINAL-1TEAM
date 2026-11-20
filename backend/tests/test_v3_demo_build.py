"""v3 시연 데이터 (app/demo.py build_v3, B6): 단계마다 고객 한 명 · 공사 하나, 9판 업체 6곳의 금액 · 별점,
다시 돌리면 건너뜀, 로컬 · 테스트에서만 만든다."""

import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest

from app import demo
from tests.conftest import query

# 단계별 고객 → (실측 요청 상태(업체 이름 순: 결도배 · 마루와벽), 업체 확정 상태)
STAGES = {
    "v3-c01@mitjip.test": (None, None),
    "v3-c02@mitjip.test": (None, None),
    "v3-c03@mitjip.test": (["requested", "requested"], None),
    "v3-c04@mitjip.test": (["requested", "offered"], None),
    "v3-c05@mitjip.test": (["picked", "booked"], None),
    "v3-c06@mitjip.test": (["booked", "visited"], None),
    "v3-c07@mitjip.test": (["quoted", "quoted"], None),
    "v3-c08@mitjip.test": (["closed", "chosen"], "confirmed"),
    "v3-c09@mitjip.test": (["chosen"], "scheduled"),
    "v3-c10@mitjip.test": (["chosen"], "checking"),
    "v3-c11@mitjip.test": (["chosen"], "done"),
}
STATE_SQL = """
select u.email,
       (select array_agg(v.status order by v.vendor_name) from visits v
         join projects p on p.id = v.project_id where p.owner_id = u.id) visits,
       (select max(d.status) from deals d join projects p on p.id = d.project_id
         where p.owner_id = u.id) deal
from users u where u.email like 'v3-c%' order by u.email
"""

SAME_SQL = """
select (select count(*) from users) u, (select count(*) from projects) p,
       (select count(*) from notifications where read_at is null) unread,
       (select count(*) from jobs where status = 'pending') pending
"""


def _build():
    return asyncio.run(demo.build_v3(demo.demo_password()))


def _login(api, email: str) -> None:
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": email, "password": demo.demo_password()})
    assert r.status_code == 200, r.text


def test_v3_demo_builds_every_stage_with_9th_draft_numbers(api):
    rows = _build()
    assert [r.role for r in rows].count("고객") == 11 and all(r.made for r in rows)
    assert len({r.email for r in rows}) == len(rows) == 18
    vendors = {r["biz_name"]: r["status"] for r in query("select biz_name, status from vendors")}
    assert vendors == {
        "마루와벽": "approved", "결도배": "approved", "한결인테리어": "approved",
        "다온도배": "pending", "바른벽": "needs_info", "늘봄벽지": "rejected",
    }  # fmt: skip
    # 시연 업체 6곳 모두 서울 25개 구를 다녀요(노원 밖 공사에서도 업체가 보이게)
    areas = query(
        "select v.biz_name, count(*) n from vendor_areas a join vendors v on v.user_id = a.vendor_id"
        " where a.sido = 'seoul' group by v.biz_name"
    )
    assert {r["biz_name"]: r["n"] for r in areas} == dict.fromkeys(vendors, 25)
    got = {r["email"]: (r["visits"], r["deal"]) for r in query(STATE_SQL)}
    assert got == STAGES
    # 실측 요청 보냄: 답 기한은 지금 + 48시간(9판 V03)
    left = query(
        "select extract(epoch from v.reply_due_at - now()) / 3600 h from visits v"
        " join projects p on p.id = v.project_id join users u on u.id = p.owner_id"
        " where u.email = 'v3-c03@mitjip.test'"
    )
    assert all(47 < r["h"] <= 48 for r in left)
    # 기한이 이미 지난 일은 build가 다 거뒀다(worker를 켜도 상태가 바뀌지 않는다)
    assert (
        query("select count(*) n from jobs where status = 'pending' and run_at < now()")[0]["n"]
        == 0
    )
    # 날짜 확정 단계: 바로 확정으로 열린 대화에 업체 · 고객 글
    assert query("select count(*) n from thread_messages where kind = 'text'")[0]["n"] == 2
    # 지난 공사 리뷰 7개 · 한리뷰 리뷰는 넣은 때가 아니라 이야기의 그날에 찍힌다(옮긴 시계)
    days = query(
        "select (created_at at time zone 'Asia/Seoul')::date d, created_at < now() - interval"
        " '1 day' old from reviews"
    )
    assert len(days) == 8 and len({r["d"] for r in days}) == 8 and all(r["old"] for r in days)

    # 9판 C10: 가견적 · 별점 · 끝낸 공사 · 바로 확정 · 단가 준비 중
    c02 = next(r for r in rows if r.email == "v3-c02@mitjip.test")
    pid = re.search(r"/projects/([^/]+)/", c02.urls["고객"]).group(1)
    _login(api, c02.email)
    r = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    cards = {c["name"]: c for c in r.json()["local"]}
    assert (cards["마루와벽"]["estimate_total"], cards["결도배"]["estimate_total"]) == (
        2_920_005,  # 판 2026H2-rooms 수량(69.4㎡ · 방 2개). 2.5배 판 9판 C10은 3,186,150 · 2,774,200
        2_535_610,
    )
    assert (
        cards["마루와벽"]["rating"],
        cards["마루와벽"]["review_count"],
        cards["마루와벽"]["done_count"],
    ) == ("4.8", 5, 5)
    assert (
        cards["결도배"]["rating"],
        cards["결도배"]["review_count"],
        cards["결도배"]["done_count"],
    ) == ("4.7", 3, 3)
    assert cards["마루와벽"]["instant_badge"] and not cards["결도배"]["instant_badge"]
    assert (
        cards["한결인테리어"]["estimate_total"] is None
        and cards["한결인테리어"]["state"] == "no_estimate"
    )
    assert all(c["shortlisted"] for k, c in cards.items() if k != "한결인테리어")

    # 업체 작업함 탭 숫자: 마루와벽 · 결도배 모두 새 요청이 있고, 마루와벽은 확정 공사가 3건
    _login(api, demo._mail("maru"))
    summary = api.get("/vendor/visits/summary").json()
    assert summary["todo"] >= 1 and summary["jobs"] == 3 and summary["sched"] == 1
    unread = query(
        "select count(*) n from notifications n join users u on u.id = n.user_id"
        " where u.email = $1 and n.read_at is null",
        demo._mail("maru"),
    )
    assert unread[0]["n"] == 1  # 새 실측 요청 하나만 안 읽음

    # 공사 중 · 끝 · 리뷰: 요청 → 실측 → 견적서 보냄 → 확정 → 날짜 → 끝냄 → 확인이 이야기 순서로,
    # 모두 넣기 전 시각(서비스는 그대로, 넣는 동안만 앱 시계를 그 단계로 옮김)
    story = ["asked", "visited", "quote_sent", "confirmed", "dates_sent", "dates_accepted",
             "done_posted", "checked"]  # fmt: skip
    today = demo.svc_today(datetime.now(UTC)).isoformat()
    for email, end in (
        ("v3-c09@mitjip.test", "dates_accepted"),
        ("v3-c10@mitjip.test", "done_posted"),
        ("v3-c11@mitjip.test", "checked"),
    ):
        url = next(r for r in rows if r.email == email).urls["고객"]
        pid = re.search(r"/projects/([^/]+)/", url).group(1)
        _login(api, email)
        log = api.get(f"/projects/{pid}/log").json()
        want = story[: story.index(end) + 1]
        assert [x["code"] for x in log if x["code"] in want] == want, email
        last = max(datetime.fromisoformat(x["at"]) for x in log)
        assert last < datetime.now(UTC) - timedelta(hours=1), email
        steps = {
            st["key"]: st["on"]
            for st in api.get(f"/projects/{pid}/overview").json()["trades"][0]["steps"]
        }
        assert all(steps[k] < today for k in ("visit", "deal", "dates")), (email, steps)

    # 다시 돌리면 이미 있는 계정은 건너뛰고 아무것도 바꾸지 않는다(종 숫자 · 기한 일도 그대로).
    # 업체는 다니는 지역만 맞춘다: 노원구 하나로 좁혀 둔 마루와벽이 서울 25개 구로 돌아와요
    maru = demo._mail("maru")
    query(
        "delete from vendor_areas a using users u"
        " where u.id = a.vendor_id and u.email = $1 and a.sgg <> '노원구'",
        maru,
    )
    before = query(SAME_SQL)[0]
    again = _build()
    assert not any(r.made for r in again)
    assert query(SAME_SQL)[0] == before
    left = query(
        "select count(*) n from vendor_areas a join users u on u.id = a.vendor_id where u.email = $1",
        maru,
    )
    assert left[0]["n"] == 25


@pytest.mark.parametrize("env", ["staging", "production"])
def test_v3_demo_refuses_outside_local_and_test(monkeypatch, env):
    monkeypatch.setattr(demo.settings, "app_env", env)
    with pytest.raises(SystemExit):
        demo.demo_password()
    with pytest.raises(SystemExit):
        asyncio.run(demo.build_v3("not-used-password"))
    with pytest.raises(SystemExit):
        demo.main([])
    assert query("select count(*) n from users")[0]["n"] == 0

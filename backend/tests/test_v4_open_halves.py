"""v4 비서 업체 빈 반나절(visit.service.open_halves_for, ADR 0001): 실측 칸 · 공사 날 · 남의 데이터 · 막힌 업체."""

import asyncio
import uuid
from datetime import date, timedelta

import pytest

from app.calc import slots
from app.calc.schedule import workdays
from app.db import SessionLocal
from app.refprice.holidays import days_off
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from app.visit import service
from tests import test_v3_visit_kit as kit
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import SEEN0, ready
from tests.test_v3_work_deal import post_days, vendor_of

TODAY = today_seoul()
BOTH = ["am", "pm"]


def halves(vendor_id, start: date, end: date) -> dict[date, list[str]]:
    async def go():
        async with SessionLocal() as s:
            return await service.open_halves_for(s, uuid.UUID(str(vendor_id)), start, end)

    return asyncio.run(go())


def capacity(vendor_id, n: int) -> None:
    query("update vendors set visit_capacity = $1 where user_id = $2", n, uuid.UUID(str(vendor_id)))


def test_work_days_in_uses_day_lists_and_old_ranges():
    d = date(2027, 1, 4)
    spans = [
        (d, d + timedelta(days=3), [d, d + timedelta(days=1), d + timedelta(days=3)]),  # 날 목록
        (d + timedelta(days=9), d + timedelta(days=12), None),  # 옛 길: 시작 ~ 끝 모두
    ]
    got = slots.work_days_in(spans, d + timedelta(days=1), d + timedelta(days=10))
    assert got == {d + timedelta(days=n) for n in (1, 3, 9, 10)}  # 기간 밖 · 고르지 않은 날은 빼요
    assert slots.work_days_in([], d, d) == set()


def test_open_halves_count_holds_by_capacity_and_skip_other_vendors(api):
    maru = kit.booked(api)  # 마루와벽: 오늘 + 6일 오전 확정
    gyeol = kit.offered(
        api,
        instant=False,
        email="gyeol@mitjip.test",
        name="결도배",
        customer_email="c2@mitjip.test",
    )
    # 결도배: 오늘 + 7일 오후 잡아 둠(바로 확정 끔)
    r = kit.choose(api, gyeol["pid"], gyeol["visit"], n=7, half="pm")
    assert r.status_code == 200 and r.json()["status"] == "picked", r.text
    start, end = kit.day(-1), kit.day(20)

    # 칸 2개 중 1개만 찼어요. 어제 · 오늘은 없고, 주말 · 공휴일은 그대로예요
    got = halves(maru["vendor"], start, end)
    assert got == {kit.day(n): BOTH for n in range(1, 21)}
    assert list(got) == sorted(got)

    capacity(maru["vendor"], 1)
    capacity(gyeol["vendor"], 1)
    got = halves(maru["vendor"], start, end)
    assert got[kit.day(6)] == ["pm"]  # 내 확정 칸만 막혀요
    assert got[kit.day(7)] == BOTH  # 다른 업체 잡기는 섞이지 않아요
    assert {d: h for d, h in got.items() if d != kit.day(6)} == {
        kit.day(n): BOTH for n in range(1, 21) if n != 6
    }
    other = halves(gyeol["vendor"], start, end)
    assert other[kit.day(7)] == ["am"] and other[kit.day(6)] == BOTH  # 잡아 둠(hold)도 칸에 세요
    # 날 · 반나절만: 고객 이름 · 연락처 · 집 정보는 없어요
    assert all(isinstance(d, date) and set(h) <= set(BOTH) and h for d, h in got.items())
    assert kit.CUSTOMER_NAME not in repr(got) and kit.PHONE not in repr(got)


def test_open_halves_empty_for_stopped_or_unknown_vendor_and_422_on_bad_range(api):
    f = kit.requested(api)
    start, end = kit.day(1), kit.day(10)
    assert len(halves(f["vendor"], start, end)) == 10
    assert halves(uuid.uuid4(), start, end) == {}
    query(
        "update vendors set suspended_at = now(), suspend_scope = 'new' where user_id = $1",
        uuid.UUID(f["vendor"]),
    )
    assert halves(f["vendor"], start, end) == {}
    for a, b in ((end, start), (start, start + timedelta(days=slots.SPAN_MAX + 1))):
        with pytest.raises(AppError) as e:
            halves(f["vendor"], a, b)
        assert (e.value.status, e.value.code) == (422, "invalid")


def test_open_halves_block_work_days_pending_then_accepted(api):
    # 마루와벽과 도배 확정(공사 날짜 전). 업체로 로그인해 있어요
    customer, pid, did, va = ready(api)
    maru = vendor_of(va)
    gyeol = query("select id from users where email = 'gyeol@mitjip.test'")[0]["id"]
    got = workdays(TODAY + timedelta(days=14), 4, days_off(TODAY, TODAY + timedelta(days=400)))
    first, second, gap, last = got
    start, end = TODAY + timedelta(days=1), last + timedelta(days=2)
    free = {TODAY + timedelta(days=n): BOTH for n in range(1, (end - TODAY).days + 1)}

    r = post_days(api, did, [first, second, last])  # 고객 답을 기다리는 공사 날짜 제안
    assert r.status_code == 200, r.text
    work = {first, second, last}
    expect = {d: h for d, h in free.items() if d not in work}
    assert halves(maru, start, end) == expect  # 사이에 고르지 않은 날(gap)은 비어 있어요
    assert gap in expect

    use(api, customer)
    x = r.json()["proposal"]["id"]
    assert api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0).status_code == 200
    (deal,) = query("select status from deals where id = $1", uuid.UUID(did))
    assert deal["status"] == "scheduled"
    assert halves(maru, start, end) == expect  # 수락한 공사 날도 막혀요
    assert halves(gyeol, start, end) == free  # 다른 업체 공사가 아니에요

    query("update deals set work_days = null where id = $1", uuid.UUID(did))  # 옛 길(시작 ~ 끝)
    assert halves(maru, start, end) == {d: h for d, h in free.items() if not first <= d <= last}

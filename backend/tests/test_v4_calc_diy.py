"""계산 엔진 calc.diy: 반셀프 직접 할 일 '언제부터 · 언제까지'(판 diy_v2). DB 없음.

- 도배만 맡긴 빈 집(S19): 페인트는 칠하고 사흘을 비우게 도배 나흘 전까지(diy_v2, v1은 사흘 전이라 빈 날 이틀),
  콘센트는 도배 전 덮개 떼기 → 도배 뒤 새 커버.
- 목공 뒤 · 도배 전 페인트, 사이가 모자라면 빠듯함(short). 빠듯한 일의 공정표 날은 할 수 있는 첫날(diy_v2).
- 주말만 할 수 있는 고객 · 공휴일(성탄절) · 할 수 있는 날이 없음(no_free_day).
- 공사 날짜가 없을 때(순서만) · 마감 지남(late) · 7일 안 마감 · 도배 없는 공사의 콘센트.
"""

from datetime import date

import pytest

from app.calc import diy
from app.calc.schedule import DRY_DAYS

D = date.fromisoformat
TODAY = D("2026-12-01")  # 화
DOBAE = {"dobae": (D("2026-12-07"), D("2026-12-09"))}  # 월 ~ 수
DRY = (D("2026-12-10"), D("2026-12-11"))
CLEAN = (D("2026-12-12"), D("2026-12-12"))


def by(tasks, key: str, step: str = "") -> diy.DiyTask:
    (t,) = [t for t in tasks if (t.key, t.step) == (key, step)]
    return t


def span(t: diy.DiyTask) -> tuple[str | None, str | None, str | None]:
    iso = lambda d: d.isoformat() if d else None
    return iso(t.start), iso(t.end), iso(t.day)


def test_rule_constants_are_versioned():
    assert diy.RULE_VER == "diy_v2" and diy.RULES is diy.RULES_V2
    assert diy.PAINT_DRY_DAYS == 3 and diy.COVER_OFF_DAYS == 3
    assert DRY_DAYS == 2  # 공정표 자연 건조(도배 다음 날부터 이틀) 뒤 입주 청소
    assert {r.key for r in diy.RULES_V2} == {r.key for r in diy.RULES_V1} == set(diy.KEYS)
    # 옛 판 diy_v1은 기록으로 남아 같은 값을 다시 셀 수 있어요(페인트 도배 − 3일, 빠듯하면 마감 날)
    (v1,) = diy.plan(["paint"], DOBAE, TODAY, rules=diy.RULES_V1)
    assert (v1.end, v1.rule_ver) == (D("2026-12-04"), "diy_v1")


def test_dobae_only_paint_and_outlet_vacant_home():
    got = diy.plan(["outlet", "paint"], DOBAE, TODAY, dry=DRY, clean=CLEAN)
    assert [(t.key, t.step) for t in got] == [("paint", ""), ("outlet", "off"), ("outlet", "on")]
    paint = by(got, "paint")
    # 목공이 없으면 오늘부터, 도배 시작(12.7 월) − 4일 = 12.3(목)까지(금 · 토 · 일 사흘 비움). 공정표에는 마감 날
    assert span(paint) == ("2026-12-01", "2026-12-03", "2026-12-03")
    assert (paint.fit, paint.late, paint.why, paint.kind) == (True, False, "", "before")
    # 덮개 떼기: 도배 사흘 전 ~ 전날(12.4 ~ 12.6), 새 커버: 도배 다음 날 ~ 입주 청소 날(12.10 ~ 12.12)
    assert span(by(got, "outlet", "off")) == ("2026-12-04", "2026-12-06", "2026-12-06")
    assert span(by(got, "outlet", "on")) == ("2026-12-10", "2026-12-12", "2026-12-10")
    assert all(t.rule_ver == "diy_v2" for t in got)


def test_after_dobae_tasks_light_silicone_handle_clean():
    got = diy.plan(diy.KEYS, DOBAE, TODAY, dry=DRY, clean=CLEAN, move_in=D("2026-12-20"))
    assert span(by(got, "light")) == ("2026-12-10", "2026-12-12", "2026-12-10")
    # 실리콘은 굳을 날을 두고 입주 청소 전날까지
    assert span(by(got, "silicone")) == ("2026-12-10", "2026-12-11", "2026-12-10")
    assert span(by(got, "handle")) == ("2026-12-10", "2026-12-12", "2026-12-10")
    # 입주 청소: 공정표의 입주 청소 날부터 입주 전날까지
    assert span(by(got, "clean")) == ("2026-12-12", "2026-12-19", "2026-12-12")
    # 공정표에 둘 날 순서: 페인트 · 덮개 떼기(도배 전) → 도배 뒤 일 → 입주 청소
    assert [t.key for t in got][:2] == ["paint", "outlet"] and got[-1].key == "clean"


def test_paint_after_mokgong_before_dobae_and_short_gap():
    work = {"mokgong": (D("2026-12-01"), D("2026-12-02")), **DOBAE}
    paint = by(diy.plan(["paint"], work, TODAY, dry=DRY, clean=CLEAN), "paint")
    assert span(paint) == ("2026-12-03", "2026-12-03", "2026-12-03")
    # 목공이 금요일에 끝나고 도배가 월요일이면 칠하고 마를 날이 모자라요. 공정표 날은 목공 다음 날(마감은 그대로)
    tight = {"mokgong": (D("2026-12-03"), D("2026-12-04")), **DOBAE}
    paint = by(diy.plan(["paint"], tight, TODAY, dry=DRY, clean=CLEAN), "paint")
    assert (paint.fit, paint.why) == (False, "short")
    assert span(paint) == ("2026-12-05", "2026-12-03", "2026-12-05")


def test_weekend_only_customer_picks_weekend_days():
    work = {"dobae": (D("2026-12-09"), D("2026-12-11"))}  # 수 ~ 금
    dry, clean = (D("2026-12-12"), D("2026-12-13")), (D("2026-12-14"), D("2026-12-14"))
    keys = ["paint", "outlet", "light", "silicone"]
    got = diy.plan(keys, work, TODAY, dry=dry, clean=clean, free="weekend")
    # 페인트: 12.1 ~ 12.5(토, 도배 − 4일) 중 주말 → 12.5(토)
    assert span(by(got, "paint")) == ("2026-12-05", "2026-12-05", "2026-12-05")
    # 덮개 떼기: 12.6 ~ 12.8 중 주말은 12.6(일)뿐
    assert span(by(got, "outlet", "off")) == ("2026-12-06", "2026-12-06", "2026-12-06")
    # 도배 뒤: 12.12(토) ~ 12.14(월) 중 주말 → 12.12 ~ 12.13, 실리콘은 청소 전날(12.13)까지
    assert span(by(got, "light")) == ("2026-12-12", "2026-12-13", "2026-12-12")
    assert span(by(got, "silicone")) == ("2026-12-12", "2026-12-13", "2026-12-12")
    assert all(t.fit for t in got)
    # 아무 날이나 되면 창 그대로
    anyday = diy.plan(["paint"], work, TODAY, dry=dry, clean=clean)
    assert span(anyday[0]) == ("2026-12-01", "2026-12-05", "2026-12-05")


def test_weekend_only_holiday_counts_and_no_free_day():
    today = D("2026-12-21")  # 월
    work = {"dobae": (D("2026-12-29"), D("2026-12-30"))}  # 화 ~ 수 (diy_v2: 마감이 도배 − 4일)
    off = frozenset({D("2026-12-25")})  # 성탄절(금)
    paint = by(diy.plan(["paint"], work, today, free="weekend", days_off=off), "paint")
    # 12.21 ~ 12.25(도배 − 4일) 중 주말 · 공휴일은 성탄절뿐
    assert span(paint) == ("2026-12-25", "2026-12-25", "2026-12-25") and paint.fit
    # 공휴일을 모르면 할 수 있는 날이 없어요: 창 그대로 두고 빠듯함
    paint = by(diy.plan(["paint"], work, today, free="weekend"), "paint")
    assert (paint.fit, paint.why) == (False, "no_free_day")
    assert span(paint) == ("2026-12-21", "2026-12-25", "2026-12-25")
    # 공휴일은 아무 날이나 되는 고객에게도 그냥 하루예요(빼지 않아요)
    paint = by(diy.plan(["paint"], work, today, days_off=off), "paint")
    assert span(paint) == ("2026-12-21", "2026-12-25", "2026-12-25")


def test_no_work_dates_gives_order_only():
    got = diy.plan(["light", "paint", "outlet"], {}, TODAY)
    assert [(t.key, t.step) for t in got] == [
        ("paint", ""), ("outlet", "off"), ("outlet", "on"), ("light", ""),
    ]  # fmt: skip
    assert all(
        (t.start, t.end, t.day, t.fit, t.late) == (None, None, None, True, False) for t in got
    )
    assert diy.due_soon(got, TODAY) == []


def test_today_clamps_start_late_and_due_soon():
    got = diy.plan(["paint", "outlet"], DOBAE, D("2026-12-05"), dry=DRY, clean=CLEAN)
    paint = by(got, "paint")
    assert (paint.late, paint.fit, paint.why) == (True, False, "late")
    assert paint.end == D("2026-12-03")
    off = by(got, "outlet", "off")
    assert span(off) == ("2026-12-05", "2026-12-06", "2026-12-06")  # 시작을 오늘로 당겨요
    # 7일 안 마감: 오늘(12.1) 기준 페인트(12.4) · 덮개 떼기(12.6)만, 새 커버(12.12)는 아직
    soon = diy.due_soon(diy.plan(["paint", "outlet"], DOBAE, TODAY, dry=DRY, clean=CLEAN), TODAY)
    assert [(t.key, t.step) for t in soon] == [("paint", ""), ("outlet", "off")]
    # 지난 마감(페인트)은 빼고, 12.12 새 커버는 7일 안이에요
    assert diy.due_soon(got, D("2026-12-05")) == [off, by(got, "outlet", "on")]


def test_without_dobae_outlet_has_only_new_cover_after_work():
    work = {"mokgong": (D("2026-12-07"), D("2026-12-08"))}
    clean = (D("2026-12-09"), D("2026-12-09"))
    got = diy.plan(["outlet", "silicone", "paint"], work, TODAY, clean=clean)
    assert [(t.key, t.step) for t in got] == [("paint", ""), ("outlet", "on"), ("silicone", "")]
    assert span(by(got, "outlet", "on")) == ("2026-12-09", "2026-12-09", "2026-12-09")
    # 실리콘은 청소 전날까지라 목공 다음 날 청소면 굳을 날이 없어요
    assert by(got, "silicone").why == "short"
    # 도배가 없으면 페인트는 목공 뒤 ~ 입주 청소 전날. 목공 다음 날 청소면 빠듯해서 공정표 날은 목공 다음 날
    assert span(by(got, "paint")) == ("2026-12-09", "2026-12-08", "2026-12-09")


def test_bad_inputs():
    with pytest.raises(ValueError):
        diy.plan(["floor"], DOBAE, TODAY)
    with pytest.raises(ValueError):
        diy.plan(["paint"], DOBAE, TODAY, free="weekday")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        diy.plan(["paint"], {"dobae": (D("2026-12-09"), D("2026-12-07"))}, TODAY)

"""계산 엔진 calc.diy: 반셀프 직접 할 일 '언제부터 · 언제까지'(판 diy_v4, 페인트 말고는 diy_v3와 같은 값). DB 없음.

- 도배만 맡긴 빈 집(S19): 페인트는 칠하고 사흘을 비우게 도배 나흘 전까지(diy_v2, v1은 사흘 전이라 빈 날 이틀),
  콘센트는 도배 전 덮개 떼기 → 도배 뒤 새 커버.
- 공정표에 목공 날짜가 없으면 페인트 시작은 날짜 없이 '목공이 끝난 뒤'(diy_v4, QA r6 c2). diy_v3까지는 오늘부터.
- 목공 뒤 · 도배 전 페인트, 사이가 모자라면 빠듯함(short). 빠듯한 일의 공정표 날은 할 수 있는 첫날(diy_v2).
- 주말만 할 수 있는 고객 · 공휴일(성탄절) · 할 수 있는 날이 없음(no_free_day).
- 공사 날짜가 없을 때(순서만) · 마감 지남(late) · 7일 안 마감 · 도배 없는 공사의 콘센트.
- 사는 집(diy_v3, QA r2 c3): 입주 청소가 마감이 아니라 뒤에 할 일 마감이 공사 뒤 첫 주말(일요일)까지예요.
"""

from dataclasses import replace
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


def by_rule(rules, key: str) -> diy.Rule:
    (r,) = [r for r in rules if r.key == key]
    return r


def span(t: diy.DiyTask) -> tuple[str | None, str | None, str | None]:
    iso = lambda d: d.isoformat() if d else None
    return iso(t.start), iso(t.end), iso(t.day)


def test_rule_constants_are_versioned():
    # diy_v4(QA r6 c2): 페인트만 다른 판이라 판 이름을 옮겼어요(목공 날짜가 없으면 시작이 '목공이 끝난 뒤')
    assert diy.RULE_VER == "diy_v4" and diy.RULES is diy.RULES_V4
    assert {r.key for r in diy.RULES_V4 if r.wait} == {"paint"}
    assert by_rule(diy.RULES_V4, "paint").wait == "mokgong"
    assert not any(r.wait for r in (*diy.RULES_V3, *diy.RULES_V2, *diy.RULES_V1))
    # 그 밖의 칸(기준 · 사는 집 늘리기)은 diy_v3와 같아요
    assert [replace(r, ver="diy_v3", wait=None) for r in diy.RULES_V4] == list(diy.RULES_V3)
    assert diy.PAINT_DRY_DAYS == 3 and diy.COVER_OFF_DAYS == 3
    assert DRY_DAYS == 2  # 공정표 자연 건조(도배 다음 날부터 이틀) 뒤 입주 청소
    keys = set(diy.KEYS)
    assert {r.key for r in diy.RULES_V4} == {r.key for r in diy.RULES_V3} == keys
    assert {r.key for r in diy.RULES_V3} == {r.key for r in diy.RULES_V2} == keys
    assert {r.key for r in diy.RULES_V1} == keys
    # 사는 집에서 늘리는 규칙: 뒤에 할 일 중 입주 청소 빼고(입주 청소 자체는 그대로)
    assert {r.key for r in diy.RULES_V3 if r.lived} == {"outlet", "light", "silicone", "handle"}
    assert not any(r.lived for r in (*diy.RULES_V2, *diy.RULES_V1))
    assert all(r.kind == "after" for r in diy.RULES_V3 if r.lived)
    # 옛 판 diy_v1은 기록으로 남아 같은 값을 다시 셀 수 있어요(페인트 도배 − 3일, 빠듯하면 마감 날)
    (v1,) = diy.plan(["paint"], DOBAE, TODAY, rules=diy.RULES_V1)
    assert (v1.end, v1.rule_ver) == (D("2026-12-04"), "diy_v1")


def test_dobae_only_paint_and_outlet_vacant_home():
    got = diy.plan(["outlet", "paint"], DOBAE, TODAY, dry=DRY, clean=CLEAN)
    assert [(t.key, t.step) for t in got] == [("paint", ""), ("outlet", "off"), ("outlet", "on")]
    paint = by(got, "paint")
    # 공정표에 목공 날짜가 없으면 시작은 날짜 없이 '목공이 끝난 뒤'(diy_v4, 새 몰딩을 달기 전에 칠하라는 꼴이 되지 않게),
    # 마감은 도배 시작(12.7 월) − 4일 = 12.3(목)(금 · 토 · 일 사흘 비움). 공정표에는 마감 날
    assert span(paint) == (None, "2026-12-03", "2026-12-03") and paint.after == "mokgong"
    assert (paint.fit, paint.late, paint.why, paint.kind) == (True, False, "", "before")
    # 덮개 떼기: 도배 사흘 전 ~ 전날(12.4 ~ 12.6), 새 커버: 도배 다음 날 ~ 입주 청소 날(12.10 ~ 12.12)
    assert span(by(got, "outlet", "off")) == ("2026-12-04", "2026-12-06", "2026-12-06")
    assert span(by(got, "outlet", "on")) == ("2026-12-10", "2026-12-12", "2026-12-10")
    assert all(t.rule_ver == "diy_v4" for t in got)
    assert by(got, "outlet", "off").after is None  # 페인트 말고는 그대로예요
    # 옛 판 diy_v3은 목공이 없으면 오늘부터였어요(기록으로 남아 같은 값을 다시 셀 수 있어요)
    v3 = diy.plan(["outlet", "paint"], DOBAE, TODAY, dry=DRY, clean=CLEAN, rules=diy.RULES_V3)
    assert span(by(v3, "paint")) == ("2026-12-01", "2026-12-03", "2026-12-03")
    assert by(v3, "paint").after is None
    assert [span(t) for t in v3 if t.key == "outlet"] == [span(t) for t in got if t.key == "outlet"]
    # 빈 집은 diy_v2와 v3가 같은 값이에요(판 이름만 달라요)
    v2 = diy.plan(["outlet", "paint"], DOBAE, TODAY, dry=DRY, clean=CLEAN, rules=diy.RULES_V2)
    assert [span(t) for t in v2] == [span(t) for t in v3]
    assert all(t.rule_ver == "diy_v2" for t in v2)


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
    # 목공 날짜가 있으면 목공 다음 날부터 → 칠 → 도배 순서예요(날짜 없는 '목공 뒤'가 아니에요)
    assert span(paint) == ("2026-12-03", "2026-12-03", "2026-12-03") and paint.after is None
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
    # 페인트: 시작은 '목공이 끝난 뒤'(날짜 없음), 오늘 ~ 12.5(토, 도배 − 4일) 중 마지막 주말 → 12.5(토)
    assert span(by(got, "paint")) == (None, "2026-12-05", "2026-12-05")
    # 옛 판(diy_v3)은 오늘부터 찾은 첫 주말이 시작이었어요
    v3 = diy.plan(["paint"], work, TODAY, dry=dry, clean=clean, free="weekend", rules=diy.RULES_V3)
    assert span(v3[0]) == ("2026-12-05", "2026-12-05", "2026-12-05")
    # 덮개 떼기: 12.6 ~ 12.8 중 주말은 12.6(일)뿐
    assert span(by(got, "outlet", "off")) == ("2026-12-06", "2026-12-06", "2026-12-06")
    # 도배 뒤: 12.12(토) ~ 12.14(월) 중 주말 → 12.12 ~ 12.13, 실리콘은 청소 전날(12.13)까지
    assert span(by(got, "light")) == ("2026-12-12", "2026-12-13", "2026-12-12")
    assert span(by(got, "silicone")) == ("2026-12-12", "2026-12-13", "2026-12-12")
    assert all(t.fit for t in got)
    # 아무 날이나 되면 마감 그대로(시작은 '목공이 끝난 뒤')
    anyday = diy.plan(["paint"], work, TODAY, dry=dry, clean=clean)
    assert span(anyday[0]) == (None, "2026-12-05", "2026-12-05")


def test_occupied_home_after_tasks_run_to_first_weekend_after_work():
    """QA r2 c3: 살면서 공사(월 ~ 수 도배, 목 · 금 자연 건조, 토 입주 청소 줄)인데 주말만 되는 고객에게 실리콘을
    입주 청소 전날(금)까지로 몰아 평일 하루를 비우라고 했어요. 사는 집은 공사 뒤 첫 주말(일요일)까지 해도 돼요."""
    work = {"dobae": (D("2026-12-14"), D("2026-12-16"))}  # 월 ~ 수
    dry, clean = (D("2026-12-17"), D("2026-12-18")), (D("2026-12-19"), D("2026-12-19"))
    keys = ["outlet", "light", "silicone", "handle", "clean"]
    today = D("2026-12-01")
    # 빈 집(v2와 같아요): 실리콘은 입주 청소 전날(12.18 금)까지라 주말만 되면 날이 없어요
    vacant = diy.plan(keys, work, today, dry=dry, clean=clean, free="weekend")
    sil = by(vacant, "silicone")
    assert (sil.fit, sil.why, sil.end) == (False, "no_free_day", D("2026-12-18"))
    # 사는 집: 실리콘 · 조명 · 새 커버 · 손잡이는 공사 뒤 첫 주말(12.19 토 ~ 12.20 일)도 돼요
    lived = diy.plan(keys, work, today, dry=dry, clean=clean, free="weekend", occupied=True)
    for k, step in (("silicone", ""), ("light", ""), ("outlet", "on"), ("handle", "")):
        assert span(by(lived, k, step)) == ("2026-12-19", "2026-12-20", "2026-12-19"), k
        assert by(lived, k, step).fit
    # 덮개 떼기(도배 전) · 입주 청소는 그대로예요
    assert span(by(lived, "outlet", "off")) == span(by(vacant, "outlet", "off"))
    assert span(by(lived, "clean")) == span(by(vacant, "clean"))
    # 아무 날이나 되면 공정표 날은 그대로 공사 다음 날(12.17 목)이고 마감만 일요일까지 늘어요
    anyday = by(diy.plan(keys, work, today, dry=dry, clean=clean, occupied=True), "silicone")
    assert span(anyday) == ("2026-12-17", "2026-12-20", "2026-12-17")
    # 입주 청소 날이 첫 주말보다 늦으면 원래 마감(더 늦은 날)을 그대로 써요
    late_clean = (D("2026-12-22"), D("2026-12-22"))
    light = by(diy.plan(["light"], work, today, dry=dry, clean=late_clean, occupied=True), "light")
    assert light.end == D("2026-12-22")
    assert diy.first_sunday(D("2026-12-17")) == D("2026-12-20")
    assert diy.first_sunday(D("2026-12-20")) == D("2026-12-20")


def test_weekend_only_holiday_counts_and_no_free_day():
    today = D("2026-12-21")  # 월
    work = {"dobae": (D("2026-12-29"), D("2026-12-30"))}  # 화 ~ 수 (diy_v2: 마감이 도배 − 4일)
    off = frozenset({D("2026-12-25")})  # 성탄절(금)
    paint = by(diy.plan(["paint"], work, today, free="weekend", days_off=off), "paint")
    # 오늘 ~ 12.25(도배 − 4일) 중 주말 · 공휴일은 성탄절뿐(시작은 '목공이 끝난 뒤', diy_v4)
    assert span(paint) == (None, "2026-12-25", "2026-12-25") and paint.fit
    # 공휴일을 모르면 할 수 있는 날이 없어요: 마감 그대로 두고 빠듯함
    paint = by(diy.plan(["paint"], work, today, free="weekend"), "paint")
    assert (paint.fit, paint.why) == (False, "no_free_day")
    assert span(paint) == (None, "2026-12-25", "2026-12-25")
    old = by(diy.plan(["paint"], work, today, free="weekend", rules=diy.RULES_V3), "paint")
    assert (old.why, span(old)) == ("no_free_day", ("2026-12-21", "2026-12-25", "2026-12-25"))
    # 공휴일은 아무 날이나 되는 고객에게도 그냥 하루예요(빼지 않아요)
    paint = by(diy.plan(["paint"], work, today, days_off=off), "paint")
    assert span(paint) == (None, "2026-12-25", "2026-12-25")


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

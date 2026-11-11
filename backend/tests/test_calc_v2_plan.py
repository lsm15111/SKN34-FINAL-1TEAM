"""v2 예상 공정표(v10 fixPlan · defaultStart · buildPlan). 순수 함수만 본다. 기대값은 손으로 센 날짜다."""

from app.calc.v2_plan import Opts, build_plan, default_start, fix_plan, next_work, trial, weeks

NO_HOLIDAY = Opts(False, frozenset(), {})
MOK = {
    "trade": "mokgong",
    "ko": "목공",
    "crew": 2,
    "steps": [
        {"key": "remove", "name": "철거", "half_days": 1},
        {"key": "trim", "name": "몰딩", "half_days": 3},
        {"key": "finish", "name": "정리", "half_days": 1},
    ],
    "need": 2.5,
}
DOB = {
    "trade": "dobae",
    "ko": "도배",
    "crew": 4,
    "steps": [
        {"key": "paper", "name": "벽지", "half_days": 2},
        {"key": "finish", "name": "마감", "half_days": 1},
    ],
    "need": 1.5,
}


def test_fix_plan_lays_trades_dry_and_clean():
    p = fix_plan([MOK, DOB], "2026-11-16", NO_HOLIDAY)  # 월요일
    assert [(b["trade"], b["start"], b["end"], b["days"]) for b in p["blocks"]] == [
        ("mokgong", "2026-11-16", "2026-11-18", 3),  # 반나절 5개 → 3일
        ("dobae", "2026-11-19", "2026-11-20", 2),
        ("dry", "2026-11-21", "2026-11-22", 2),  # 달력 날짜(주말도)
        ("clean", "2026-11-23", "2026-11-23", 1),
    ]
    assert p["work_days"] == 5 and p["end"] == "2026-11-23" and len(p["days"]) == 8
    todo = {d["date"]: [i["todo"] for i in d["items"]] for d in p["days"]}
    # 반나절 [철거, 몰딩, 몰딩, 몰딩, 정리]를 3일에: h × 3 ÷ 5
    assert todo["2026-11-16"] == [["철거", "몰딩"]]
    assert todo["2026-11-17"] == [["몰딩"]] and todo["2026-11-18"] == [["정리"]]
    assert todo["2026-11-21"] == [["창문을 닫고 자연 건조"]]
    sat = next(d for d in p["days"] if d["date"] == "2026-11-21")
    assert sat["off"] is True and sat["holiday"] is None


def test_fixed_start_and_holidays():
    o = Opts(False, frozenset({"2026-11-19"}), {"2026-11-17": "쉬는 날"})
    p = fix_plan(
        [MOK, {**DOB, "fixed": {"start": "2026-11-30"}, "state": "confirmed"}], "2026-11-16", o
    )
    mok, dob = p["blocks"][:2]
    assert (mok["start"], mok["end"]) == ("2026-11-16", "2026-11-20")  # 17 공휴일 · 19 피하는 날
    assert (dob["start"], dob["end"], dob["state"]) == ("2026-11-30", "2026-12-01", "confirmed")
    assert (
        next_work("2026-12-25", Opts(False, frozenset(), {"2026-12-25": "성탄절"})) == "2026-12-28"
    )
    assert next_work("2026-11-21", Opts(True, frozenset(), {})) == "2026-11-21"  # 주말 공사


def test_default_start():
    t = "2026-11-11"  # 수요일
    assert default_start([MOK, DOB], NO_HOLIDAY, t, "", "", "") == "2026-11-25"  # 2주 뒤
    assert default_start([MOK, DOB], NO_HOLIDAY, t, "", "2026-11-10", "") == "2026-11-12"
    # 끝낼 날 11-30: 11-30에 시작하면 12-07에 끝나 7일 앞당겨 11-23
    assert default_start([MOK, DOB], NO_HOLIDAY, t, "2026-11-30", "", "") == "2026-11-23"
    # 입주 2026-12이면 11-30이 목표
    assert default_start([MOK, DOB], NO_HOLIDAY, t, "", "", "2026-12") == "2026-11-23"


def test_build_plan_warns_late_and_weeks():
    p = build_plan([MOK, DOB], NO_HOLIDAY, "2026-11-11", "2026-11-20", "", "")
    assert p["start"] == "2026-11-12" and p["end"] == "2026-11-21"  # 내일보다 앞당기지 않음
    assert p["warn"] == [
        "목표(2026-11-20)보다 1일 늦어요. 공정을 줄이거나 주말 공사를 고려해 보세요."
    ]
    w = weeks(p["blocks"])
    assert [(x["n"], x["start"], x["end"], [b["trade"] for b in x["blocks"]]) for x in w] == [
        (1, "2026-11-09", "2026-11-15", ["mokgong"]),
        (2, "2026-11-16", "2026-11-22", ["dobae", "dry", "clean"]),
    ]


def test_trial_moves_later_trades_and_checks_dates():
    p = build_plan([MOK, DOB], NO_HOLIDAY, "2026-11-11", "", "", "")  # 11-25 시작
    t = trial(p, "mokgong", "2026-11-30", "2026-12-02", NO_HOLIDAY, "2026-11-11", {})
    assert [m["trade"] for m in t["moved"]] == ["dobae", "dry", "clean"]
    assert t["error"] is None and t["work_days"] == 3 and t["short"] is False
    acc = {"dobae": {"start": "2026-12-01", "end": "2026-12-02"}}
    assert trial(p, "mokgong", "2026-11-30", "2026-12-01", NO_HOLIDAY, "2026-11-11", acc)["clash"]
    bad = trial(p, "mokgong", "2026-11-11", "2026-11-12", NO_HOLIDAY, "2026-11-11", {})
    assert bad["error"] == "시작일은 내일부터 1년 안으로 골라 주세요."
    sat = trial(p, "mokgong", "2026-11-21", "2026-11-23", NO_HOLIDAY, "2026-11-11", {})
    assert sat["error"].startswith("시작일과 끝나는 날은 일하는 날로")
    short = trial(p, "mokgong", "2026-11-30", "2026-11-30", NO_HOLIDAY, "2026-11-11", {})
    assert short["work_days"] == 1 and short["short"] is True

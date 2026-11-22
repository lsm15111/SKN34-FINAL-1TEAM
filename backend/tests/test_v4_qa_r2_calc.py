"""QA 2차 고침 G(계산 · 공정표 · 실측): 리뷰(r1-domain D*) · 예외 상황(edge P*) 재현. 파일(sec)은 test_v4_qa_r2_files.

- D1 '다른 줄에 포함'은 대상 줄이 이 줄이 나오는 모든 집에 같이 나올 때만(모든 집 줄 → 벽지별 줄은 안 돼요).
  계산 엔진은 포함 대상이 이 집 가견적에 단가로 없으면 그 줄을 missing에 남기고, 고객 가견적은 '없음'이에요.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.calc import diy as calc_diy
from app.calc import dobae, slots
from app.calc.common import Step
from app.calc.estimate import V3_BY_KEY, PriceV3, estimate_v3, same_home
from app.calc.schedule import TradePlan, lay_out, workdays
from app.calc.space_share import SPACE_SHARE_2026_11
from app.refprice.book import DOBAE_2026H2
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market
from app.shared.clock import now_utc
from tests import test_extras as extras
from tests import test_v3_visit_kit as kit
from tests import test_v3_work_deal as work_deal
from tests import test_vendor_quote as vendor_quote
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_dates import OFF, SEEN0, propose, ready, sched
from tests.test_project import body as project_body
from tests.test_v3_vendor_prices import MARU, _estimate, _project, confirm, vendor, with_line
from tests.test_v3_visit_kit import add
from tests.test_v4_assistant_diy import block, chips, dobae_in, plan
from tests.test_visit_inbox import login

D = Decimal
MARU_V3 = {  # 계산 엔진 시험용 마루와벽 단가(9판 C11, 합지 부자재 따로)
    "putty": PriceV3("price", 20_000),
    "paper_hapji": PriceV3("price", 5_000),
    "paper_silk": PriceV3("price", 9_500),
    "material": PriceV3("price", 13_000),
    "material_hapji": PriceV3("price", 6_500),
    "labor": PriceV3("price", 300_000),
    "meal": PriceV3("price", 11_000),
    "truck": PriceV3("price", 50_000),
}


def _qty(grade: str) -> dobae.QtyV3:
    h = dobae.HomeV3(D("69.4"), "supply", grade, False)
    return dobae.standard_v3(
        h, DOBAE_2026H2, paper_market(grade), SPACE_SHARE_2026_11, HOUSE_2026H2
    ).qty


# ---- D1 모든 집 줄 → 벽지별 줄 '포함' ----


def test_d1_all_home_row_cannot_be_included_in_a_paper_row():
    rows = V3_BY_KEY
    assert not same_home(rows["labor"], rows["paper_silk"])  # 인건비는 합지 집에도 나와요
    assert not same_home(rows["meal"], rows["material"])  # 1209 뒤 1205는 실크 집 줄
    assert not same_home(rows["truck"], rows["paper_hapji"])
    assert same_home(rows["paper_silk"], rows["labor"])  # 벽지별 줄 → 모든 집 줄은 괜찮아요
    assert same_home(rows["material_hapji"], rows["paper_hapji"])
    assert same_home(rows["meal"], rows["labor"])


def test_d1_estimate_keeps_included_line_without_target_in_missing():
    bad = {**MARU_V3, "labor": PriceV3("included", included_in="paper_silk")}
    hapji = estimate_v3(bad, _qty("economy"), grade="economy")
    assert hapji.missing == ("labor",)  # 합지 집에는 실크 도배지 줄이 없어 인건비 금액을 몰라요
    silk = estimate_v3(bad, _qty("basic"), grade="basic")
    assert silk.missing == ()  # 실크 집은 실크 도배지 단가에 인건비가 들어 있어요
    assert estimate_v3(MARU_V3, _qty("economy"), grade="economy").missing == ()
    # 대상이 '빼기' 줄이어도 금액을 몰라요
    out = {
        **MARU_V3,
        "meal": PriceV3("included", included_in="truck"),
        "truck": PriceV3("excluded"),
    }
    assert estimate_v3(out, _qty("basic"), grade="basic").missing == ("meal",)


def test_d1_old_set_without_1209_counts_1205_for_hapji_homes():
    """1209 줄이 없는 옛 묶음: 합지 집 부자재는 1205 단가를 대신 써서, 1205에 포함한 줄도 금액이 있어요."""
    old = {k: p for k, p in MARU_V3.items() if k != "material_hapji"}
    old["meal"] = PriceV3("included", included_in="material")
    e = estimate_v3(old, _qty("economy"), grade="economy")
    assert e.missing == ()
    mat = next(x for x in e.lines if x.row.key == "material_hapji")
    assert (mat.mode, mat.unit_price) == ("price", 13_000)


def test_d1_confirm_refuses_all_home_row_in_paper_row(api):
    vendor(api)
    r = confirm(api, with_line(MARU, "labor", mode="included", included_in="paper_silk"))
    assert r.status_code == 422, r.text
    (field,) = r.json()["error"]["fields"]
    assert field["loc"] == ["lines", "labor"]
    assert field["msg"] == "모든 집에 쓰는 줄은 벽지별 줄(도배지 · 부자재)에 포함할 수 없어요."
    assert query("select count(*) n from vendor_price_sets")[0]["n"] == 0
    # 같은 벽지 줄 · 모든 집 줄에 포함은 그대로 돼요
    ok = with_line(MARU, "meal", mode="included", included_in="labor")
    assert confirm(api, ok).status_code == 200


def test_d1_old_bad_set_gives_no_estimate_for_other_paper(api):
    maru = vendor(api, "maru@mitjip.test")
    assert confirm(api, MARU).status_code == 200
    # 고치기 전에 확인한 묶음: 인건비를 실크 도배지에 포함
    query(
        "update vendor_price_lines set mode = 'included', unit_price = null,"
        " included_in = 'paper_silk' where key = 'labor'"
    )
    pid = _project(api, grade="economy")
    assert (
        _estimate(maru, pid) is None
    )  # 합지 집: 인건비 금액을 몰라 가견적 없음(0원으로 빼지 않아요)
    silk = _estimate(maru, pid, grade="basic")
    labor = next(x for x in silk.lines if x.key == "labor")
    assert (labor.mode, labor.included_in, labor.amount) == ("included", "paper_silk", 0)
    r = add(api, str(pid), str(maru))  # 담기도 가견적 없음으로 막혀요
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_estimate", r.text


# ---- D4 한 번 더 요청이 '업체에 알릴 것' 사본을 옮김 ----


def test_d4_again_keeps_the_diy_copy(api):
    a = kit.vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = kit.customer(api)
    assert kit.add(api, pid, a).status_code == 201 and kit.ask(api, pid, [a]).status_code == 201
    first = kit.visit_of(pid, a)
    query("update visits set diy = '{paint,outlet}' where id = $1", uuid.UUID(first))
    r = api.post(f"/projects/{pid}/visits/{first}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text
    r = api.post(f"/projects/{pid}/visits/{first}/again")
    assert r.status_code == 201, r.text
    (row,) = query("select diy from visits where id = $1", uuid.UUID(r.json()["visit_id"]))
    assert row["diy"] == ["paint", "outlet"]  # 고객이 승인 카드에서 본 목록 그대로


# ---- D7 '주방 가구'는 자리 낱말이 아니라 주방 공종 ----


def test_d7_kitchen_furniture_is_kitchen_work():
    from app.knowledge import other_trades

    assert other_trades.codes_of("주방 가구 바꾸고 타일도 붙이려면요?") == ["tile", "kitchen"]
    assert other_trades.codes_of("싱크대 바꾸고 타일도 붙이려면요?") == ["tile", "kitchen"]
    assert "kitchen" in other_trades.codes_of("주방가구 바꾸면서 주방 타일도 하려면요?")
    # 자리 낱말뿐이면 그대로 빼요(주방은 타일 붙일 자리)
    assert other_trades.codes_of("주방 타일 붙이려면요?") == ["tile"]
    k = other_trades.notes_for("주방 가구 바꾸고 타일도 붙이려면요?")
    assert k is not None and k.names == ("타일", "주방")


# ---- D8 하나씩 고른 공사 날(사이 빈 날)은 그 날 수로 센다 ----


def test_d8_picked_days_with_a_gap_keep_their_own_count(api):
    customer, pid, did, _ = ready(api)
    picked = work_deal.picked()  # 일하는 날 4개 중 셋째를 뺀 3일
    r = work_deal.post_days(api, did, picked)
    assert r.status_code == 200, r.text
    use(api, customer)
    t = sched(api, pid)
    assert t["proposal"]["workdays"] == 3 and t["start_options"]
    for o in t["start_options"]:  # 요청 후보도 3일(범위로 세면 4일)
        assert o["end"] == workdays(date.fromisoformat(o["start"]), 3, OFF)[-1].isoformat(), o
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{t['proposal']['id']}/accept", json=SEEN0)
    assert r.status_code == 200, r.text
    wish = workdays(picked[-1] + timedelta(days=14), 1, OFF)[0]
    r = api.post(
        f"/projects/{pid}/deals/{did}/date-requests",
        json={"wish_dates": [wish.isoformat()], "reason": "이사 날이 바뀌었어요."},
    )
    assert r.status_code == 201, r.text
    login(api, "maru@mitjip.test")
    job = api.get(f"/vendor/jobs/{did}").json()
    end = workdays(wish, 3, OFF)[-1]
    assert job["request_options"] == [{"start": wish.isoformat(), "end": end.isoformat()}]
    # 고객이 고른 시작일 · 같은 날 수(3일)로 범위를 내면 받아요
    assert propose(api, did, wish.isoformat(), end.isoformat(), kind="change").status_code == 200


# ---- D10 페인트 비울 날 3일 · D5 빠듯함 · 지난 마감 (calc.diy 판 diy_v2, diy_v3도 빈 집은 같은 값) ----

DOBAE = {"dobae": (date(2026, 12, 7), date(2026, 12, 9))}  # 월 ~ 수


def test_d10_paint_leaves_three_empty_days_before_dobae():
    # 판은 diy_v3(QA r2 c3 사는 집)로 옮겼어요. 페인트 규칙은 diy_v2와 같아요
    assert calc_diy.RULE_VER == "diy_v3" and calc_diy.RULES is calc_diy.RULES_V3
    (paint,) = calc_diy.plan(["paint"], DOBAE, date(2026, 12, 1))
    assert (paint.start, paint.end, paint.day) == (
        date(2026, 12, 1),
        date(2026, 12, 3),
        date(2026, 12, 3),
    )
    # 목요일까지 칠하면 금 · 토 · 일 사흘(72시간 넘게)을 비우고 월요일에 도배해요
    empty = (DOBAE["dobae"][0] - paint.end).days - 1
    assert empty == calc_diy.PAINT_DRY_DAYS == 3 and paint.rule_ver == "diy_v3"


def test_d5_tight_paint_is_placed_after_mokgong():
    """목공 바로 뒤 도배(공정표 lay_out): 칠하고 말릴 날이 없어 빠듯해요. 공정표 날은 목공이 끝난 다음 날이에요
    (마감 날로 두면 목공 시작 전이라 문틀 · 몰딩을 갈기 전에 칠하라는 말이 돼요)."""
    mok, dob = [Step("frame", "목공", 4)], [Step("paper", "도배", 4)]
    laid = lay_out([TradePlan("mokgong", mok, 2), TradePlan("dobae", dob, 2)], date(2026, 12, 7))
    work = {b.trade: (b.start, b.end) for b in laid.blocks if b.kind == "work"}
    assert work == {
        "mokgong": (date(2026, 12, 7), date(2026, 12, 8)),
        "dobae": (date(2026, 12, 9), date(2026, 12, 10)),
    }
    (paint,) = calc_diy.plan(["paint"], work, date(2026, 11, 22))
    assert (paint.fit, paint.why, paint.late) == (False, "short", False)
    assert paint.end == date(2026, 12, 5)  # 마감(도배 − 4일)은 그대로 알려요
    assert paint.day == date(2026, 12, 9) > work["mokgong"][1]


def test_d5_plan_marks_tight_paint_and_keeps_it_off_the_day_cells(api):
    signup(api, "home@mitjip.test")
    r = api.post("/projects", json=project_body())  # 도배 + 목공
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    chips(api, pid, ["paint", "outlet"])
    p = plan(api, pid)
    mok = block(p, "work", "mokgong")
    rows = {b["label"]: b for b in p["blocks"] if b["kind"] == "diy"}
    paint = rows["페인트(문틀 · 몰딩) 칠하기 · 날이 빠듯해요"]
    assert paint["start"] == paint["end"] > mok["end"]  # 목공이 끝난 뒤
    names = [n for d in p["days"] for n in d["names"]]
    assert not any(n.startswith("페인트") for n in names)  # 그날 할 일로 두지 않아요
    off = rows["콘센트 · 스위치 덮개 떼기"]  # 맞는 일은 그대로(표시 없음 · 날 칸 있음)
    assert f"콘센트 · 스위치 덮개 떼기 · {calc_diy.SELF}" in names and off["start"] <= off["end"]


def test_d5_plan_marks_a_late_task(api):
    _, pid, _ = dobae_in(api, 2)  # 이틀 뒤 도배: 페인트 마감(도배 − 4일)이 지났어요
    chips(api, pid, ["paint", "outlet"])
    p = plan(api, pid)
    assert p["kind"] == "final"
    labels = [b["label"] for b in p["blocks"] if b["kind"] == "diy"]
    assert "페인트(문틀 · 몰딩) 칠하기 · 마감이 지났어요" in labels
    assert "콘센트 · 스위치 덮개 떼기" in labels  # 아직 할 수 있는 일은 그대로
    names = [n for d in p["days"] for n in d["names"]]
    assert not any(n.startswith("페인트") for n in names)


# ---- P7 · P11 실측 견적서 · 추가 금액 0원 ----


MIN_CHECK = "ck_vendor_quotes_entered_amount_min"


def old_zero_quote() -> None:
    """1원 CHECK(0052, NOT VALID) 전에 0원으로 임시 저장한 견적서 행을 만든다."""
    query(f"alter table vendor_quotes drop constraint {MIN_CHECK}")
    try:
        query("update vendor_quotes set entered_amount = 0, supply = 0, vat = 0, total = 0")
    finally:
        query(
            f"alter table vendor_quotes add constraint {MIN_CHECK}"
            " check (entered_amount >= 1) not valid"
        )


def test_p7_vendor_quote_needs_one_won(api):
    _customer, _p, v = vendor_quote.ready(api)
    f = vendor_quote.doc(api)
    url = vendor_quote.url(v)
    r = api.put(url, json={"file_ids": [f], **vendor_quote.FULL, "entered_amount": 0})
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["loc"] == ["entered_amount"]
    assert api.put(url, json={"file_ids": [f], **vendor_quote.FULL}).status_code == 200
    # 고치기 전에 0원으로 저장한 임시 견적서도 보내지 않아요(보내기 검사). 그런 옛 행은 1원 CHECK(0052) 앞에
    # 저장된 것이라, CHECK를 잠깐 빼고 만든 뒤 운영과 같은 꼴(NOT VALID: 옛 행은 그대로)로 되돌려요
    old_zero_quote()
    r = api.post(f"{url}/send")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["fields"] == [
        {"loc": ["entered_amount"], "msg": "낼 금액은 1원 이상으로 넣어 주세요."}
    ]
    assert query("select status from visits")[0]["status"] == "requested"


def test_p11_extra_needs_one_won(api):
    _customer, _pid, did = extras.scheduled(api)
    r = extras.extra(api, did, 0)
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["loc"] == ["entered_amount"]
    assert query("select count(*) n from extra_charges")[0]["n"] == 0
    assert extras.extra(api, did, 1).status_code == 201


# ---- P8 같은 집 두 업체 실측이 같은 반나절 ----


def test_p8_candidates_skip_halves_taken_at_home():
    today = date(2026, 12, 1)
    days = [slots.DayOpen(date(2026, 12, 7), 2, 2), slots.DayOpen(date(2026, 12, 8), 2, 2)]
    first = slots.candidates(days, None, today)[0]
    assert (first.day, first.half) == (date(2026, 12, 7), "am")
    taken = {(date(2026, 12, 7), "am")}
    got = slots.candidates(days, None, today, taken=taken)
    assert (date(2026, 12, 7), "am") not in {(c.day, c.half) for c in got} and got
    assert not slots.free_at_home(date(2026, 12, 7), "am", taken)
    assert slots.free_at_home(date(2026, 12, 7), "pm", taken)


def test_p8_two_vendors_cannot_take_the_same_half_day_at_home(api):
    a = kit.vendor(api, "maru@mitjip.test", "마루와벽")
    b = kit.vendor(api, "gyeol@mitjip.test", "결도배", wall=7000)
    token, pid = kit.customer(api)
    assert kit.add(api, pid, a).status_code == 201 and kit.add(api, pid, b).status_code == 201
    assert kit.ask(api, pid, [a, b]).status_code == 201
    va, vb = kit.visit_of(pid, a), kit.visit_of(pid, b)
    login(api, "maru@mitjip.test")
    assert kit.answer(api, va).status_code == 200
    login(api, "gyeol@mitjip.test")
    assert kit.answer(api, vb).status_code == 200
    use(api, token)
    owner = kit.user_id("home@mitjip.test")

    async def first_slot(s, user):
        from app.assistant.runtime import RefTable
        from app.assistant.tools import cards

        _card, model = await cards.visit_slots(
            s, user, uuid.UUID(pid), uuid.UUID(vb), now_utc(), RefTable(uuid.uuid4()),
            prefer="any", days="any",
        )  # fmt: skip
        return [(c["day"], c["half"]) for c in model["candidates"]]

    best = kit.run(kit.with_user(owner, first_slot))[0]
    day, half = best[0], {"오전": "am", "오후": "pm"}.get(best[1], best[1])
    r = api.post(f"/projects/{pid}/visits/{va}/pick", json={"day": day.isoformat(), "half": half})
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text
    # 같은 집 다른 업체 후보에서 빠져요
    assert (day, best[1]) not in kit.run(kit.with_user(owner, first_slot))
    r = api.post(f"/projects/{pid}/visits/{vb}/pick", json={"day": day.isoformat(), "half": half})
    assert r.status_code == 409 and r.json()["error"]["code"] == "slot_clash", r.text
    assert (
        r.json()["error"]["message"]
        == "같은 반나절에 다른 업체 실측이 잡혀 있어요. 다른 반나절을 골라 주세요."
    )
    assert kit.status(vb) == "offered"
    other = "pm" if half == "am" else "am"
    r = api.post(f"/projects/{pid}/visits/{vb}/pick", json={"day": day.isoformat(), "half": other})
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text

"""업체 단가표 v3(dobae_v3, 1201~1208, D02 · dev-06): 몸통 있는 '확인하고 저장' 한 번, 본 판이 아니면 409 stale
(동시 두 번이면 늦은 쪽), 10배 경고는 저장, 옛 확인 길은 그대로. 고객 가견적 v3(estimate_v3_for):
업체 단가 × 계산 엔진 수량, 표준에 없는 줄은 비교 %에서 빼기, 간이 부가세 0, 다른 벽지 미리 보기."""

import asyncio
import uuid
from decimal import Decimal

from app.auth.models import User
from app.db import SessionLocal
from app.project import service as project_service
from app.shared.errors import AppError
from app.vendor import service
from tests.conftest import query
from tests.helpers import no_surprises, signup
from tests.test_v3_project_home import HOME
from tests.test_vendor_profile import URL as PROFILE
from tests.test_vendor_profile import approved_vendor, vendor_id
from tests.test_vendor_profile import body as profile_body

PRICES = "/vendor/prices"
CONFIRM = "/vendor/prices/dobae/confirm"
D02 = [  # 9판 D02 결도배 (운송비는 넣음)
    {"key": "putty", "mode": "price", "unit_price": 15_000},
    {"key": "paper_hapji", "mode": "excluded"},
    {"key": "paper_silk", "mode": "price", "unit_price": 9_000},
    {"key": "material", "mode": "price", "unit_price": 12_000},
    {"key": "labor", "mode": "price", "unit_price": 2_800_000},  # 10배 넘음 → 경고(저장은 돼요)
    {"key": "meal", "mode": "included", "included_in": "labor"},
    {"key": "truck", "mode": "price", "unit_price": 50_000},
]
MARU = [  # 9판 C11 마루와벽
    {"key": "putty", "mode": "price", "unit_price": 20_000},
    {"key": "paper_hapji", "mode": "price", "unit_price": 5_000},
    {"key": "paper_silk", "mode": "price", "unit_price": 9_500},
    {"key": "material", "mode": "price", "unit_price": 13_000},
    {"key": "labor", "mode": "price", "unit_price": 300_000},
    {"key": "meal", "mode": "price", "unit_price": 11_000},
    {"key": "truck", "mode": "price", "unit_price": 50_000},
]


def vendor(api, email: str = "gyeol@mitjip.test", **profile) -> uuid.UUID:
    """승인 · 업체 정보까지 저장한 도배 업체 (노원 · 도봉). 끝나면 그 업체로 로그인해 있다."""
    approved_vendor(api, email)
    assert api.put(PROFILE, json=profile_body(**profile)).status_code == 200
    return vendor_id(email)


def confirm(api, lines: list[dict], base: int = 0):
    return api.post(CONFIRM, json={"base_version": base, "lines": lines})


def _run(fn):
    async def go():
        async with SessionLocal() as s:
            return await fn(s)

    return asyncio.run(go())


def test_v3_table_starts_empty_with_example_quantities(api):
    vendor(api)
    r = api.get(PRICES, params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    v3 = r.json()["v3"]
    assert (v3["rows_ver"], v3["version"], v3["needs_setup"], v3["example"]) == (
        "dobae_v3",
        0,
        True,
        None,
    )
    got = [
        (x["code"], x["unit"], x["mode"], x["example_qty"], x["example_amount"])
        for x in v3["lines"]
    ]
    assert got == [
        ("1201", "공급 평", None, "21.0", 0),
        # 도배만 하는 공사 기준(판 2026.11-market): 69.4㎡ · 방 2개, 실크 소요량 × 1.04 (옛 판 53.9)
        ("1203", "벽지 평", None, "56.0", 0),
        ("1204", "벽지 평", None, "56.0", 0),
        ("1205", "공급 평", None, "21.0", 0),
        ("1206", "품", None, "4.5", 0),
        ("1207", "품", None, "4.5", 0),
        ("1208", "대", None, "1", 0),
    ]
    mok = api.get(PRICES, params={"trade": "mokgong"})
    assert mok.status_code == 200 and mok.json()["v3"] is None  # v3 단가표는 도배만


def test_confirm_v3_saves_every_line_and_warns(api):
    vid = vendor(api)
    r = confirm(api, D02)
    assert r.status_code == 200, r.text
    out = r.json()
    v3 = out["v3"]
    assert (v3["version"], v3["needs_setup"]) == (1, False) and v3["confirmed_at"]
    lines = {x["key"]: x for x in v3["lines"]}
    assert lines["putty"]["example_amount"] == 315_000  # 9판 D02 '공급 69.4㎡ 집이면'
    assert lines["paper_silk"]["example_amount"] == 504_000  # 56.0평 × 9,000 (옛 판 485,100)
    assert lines["material"]["example_amount"] == 252_000
    assert (lines["labor"]["example_amount"], lines["labor"]["warn"]) == (
        12_600_000,
        "too_high",
    )  # 4.5품 × 2,800,000
    # 화면이 저장 전에 쓰는 경고 경계: B6 기준 270,000원 × 10 · ÷ 10 올림
    assert (lines["labor"]["warn_high"], lines["labor"]["warn_low"]) == (2_700_000, 27_000)
    assert (
        lines["meal"]["mode"],
        lines["meal"]["included_in"],
        lines["meal"]["example_amount"],
    ) == (
        "included",
        "labor",
        0,
    )
    assert (lines["paper_hapji"]["mode"], lines["paper_hapji"]["unit_price"]) == ("excluded", None)
    assert all(lines[k]["warn"] is None for k in ("putty", "paper_silk", "material", "truck"))
    ex = v3["example"]
    assert (ex["supply"], ex["vat"], ex["total"], ex["grade"], ex["paper_ok"]) == (
        13_721_000,  # 퍼티 315,000 + 실크 504,000 + 자재 252,000 + 인건비 12,600,000 + 운송 50,000
        1_372_100,
        15_093_100,
        "basic",
        True,
    )
    assert [x["key"] for x in ex["lines"] if not x["in_standard"]] == ["putty", "meal", "truck"]
    assert out["draft"] is None and out["confirmed"] is None  # 옛 칸에는 v3 묶음이 안 보인다
    (ps,) = query("select id, rows_ver, status, version from vendor_price_sets")
    assert (ps["rows_ver"], ps["status"], ps["version"]) == ("dobae_v3", "confirmed", 1)
    modes = query("select key, mode from vendor_price_lines order by key")
    assert {m["key"]: m["mode"] for m in modes}["paper_hapji"] == "excluded"
    # 옛 v2 가견적 길(confirmed_prices)은 v3 묶음을 쓰지 않는다
    assert _run(lambda s: service.confirmed_prices(s, [vid], "dobae")) == {}
    low = confirm(api, [*D02[:4], {**D02[4], "unit_price": 20_000}, *D02[5:]], base=1)
    assert next(x for x in low.json()["v3"]["lines"] if x["key"] == "labor")["warn"] == "too_low"


def test_confirm_needs_the_version_you_saw(api):
    vendor(api)
    assert confirm(api, D02).status_code == 200
    stale = confirm(api, MARU, base=0)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    ok = confirm(api, MARU, base=1)
    assert ok.status_code == 200 and ok.json()["v3"]["version"] == 2
    rows = query("select version, status from vendor_price_sets order by version")
    assert [(r["version"], r["status"]) for r in rows] == [(1, "retired"), (2, "confirmed")]
    assert confirm(api, MARU, base=9).status_code == 409


def test_two_confirms_at_the_same_time_one_is_stale(api):
    vid = vendor(api)
    from app.vendor.schemas import ConfirmPricesIn

    data = ConfirmPricesIn(base_version=0, lines=MARU)

    async def one():
        async with SessionLocal() as s:
            user = await s.get(User, vid)
            return await service.confirm_prices_v3(s, user, "dobae", data)

    async def both():
        return await asyncio.gather(one(), one(), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and (errors[0].status, errors[0].code) == (409, "stale")
    assert query("select count(*) n from vendor_price_sets where status = 'confirmed'")[0]["n"] == 1


def test_confirm_v3_input_is_checked(api):
    vendor(api)

    def locs(r) -> list:
        assert r.status_code == 422, r.text
        return [f["loc"] for f in r.json()["error"]["fields"]]

    assert locs(confirm(api, D02[:-1])) == [["lines", "truck"]]  # 빈 줄(받는 법 · 단가 없음)
    assert ["lines", "wall"] in locs(confirm(api, [*D02, {"key": "wall", "mode": "excluded"}]))
    bad_target = [
        *D02[:5],
        {"key": "meal", "mode": "included", "included_in": "paper_hapji"},
        D02[6],
    ]
    assert locs(confirm(api, bad_target)) == [["lines", "meal"]]  # 포함 대상이 '빼기' 줄
    nothing = [{"key": x["key"], "mode": "excluded"} for x in D02]
    assert locs(confirm(api, nothing)) == [["lines"]]
    no_price = [{"key": "putty", "mode": "price"}, *D02[1:]]
    assert confirm(api, no_price).status_code == 422
    minus = [{**D02[0], "unit_price": -1}, *D02[1:]]
    assert confirm(api, minus).status_code == 422
    mok = api.post("/vendor/prices/mokgong/confirm", json={"base_version": 0, "lines": MARU})
    assert locs(mok) == [["trade"]]
    assert query("select count(*) n from vendor_price_sets")[0]["n"] == 0


def test_old_confirm_without_body_is_unchanged(api):
    vendor(api)
    r = api.post(CONFIRM)  # 몸통 없는 옛 길: 고치는 중인 묶음이 없으면 409 invalid_state
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    signup(api, "home@mitjip.test")
    assert confirm(api, D02).status_code == 403  # 고객은 못 해요


def _project(api, **over) -> uuid.UUID:
    signup(api, "home@mitjip.test")
    r = api.post("/projects", json={**HOME, **over})
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


def _estimate(vid, pid, grade=None, trade="dobae"):
    async def go(s):
        p = await project_service.get_out(s, pid)
        return await service.estimate_v3_for(s, vendor_id=vid, project=p, trade=trade, grade=grade)

    return _run(go)


def test_customer_estimate_v3_for_c11(api):
    maru = vendor(api, "maru@mitjip.test")
    assert confirm(api, MARU).status_code == 200
    none = vendor(api, "hangyeol@mitjip.test")  # v3 단가를 아직 확인하지 않음
    pid = _project(api)

    e = _estimate(maru, pid)
    assert (e.supply, e.vat, e.total, e.tax_kind, e.grade) == (
        2_674_500,  # 판 2026.11-market 수량 (옛 판 2026H2-rooms 2,654,550)
        267_450,
        2_941_950,
        "general",
        "basic",
    )
    # 도배만 하는 공사 기준이라 퍼티 · 식대 · 운송비는 비교에서 뺌: 215.5만 × 1.1 ÷ 표준 1,944,721
    assert e.vs_standard_pct == Decimal("21.9") and e.paper_ok is True
    assert [(x.code, x.qty, x.amount) for x in e.lines][:2] == [
        ("1201", Decimal("21.0"), 420_000),
        ("1204", Decimal("56.0"), 532_000),
    ]
    assert e.set_id is not None and e.version == 1
    hapji = _estimate(maru, pid, grade="economy")  # ?grade= 미리 보기: 표준도 그 벽지로
    assert (
        hapji.grade == "economy" and hapji.total - e.total == -288_750
    )  # 합지 53.9평 · 실크 56.0평 (옛 판 −266,805)
    assert _estimate(none, pid) is None and _estimate(maru, pid, trade="mokgong") is None

    query("update vendors set tax_kind = 'simplified' where user_id = $1", maru)
    simple = _estimate(maru, pid)
    assert (simple.vat, simple.total, simple.tax_kind) == (0, 2_674_500, "simplified")  # L02
    query("update vendors set status = 'rejected', review_code = 'closed', approved_at = null"
          " where user_id = $1", maru)  # fmt: skip
    assert _estimate(maru, pid) is None  # 승인된 업체만


def test_paper_line_excluded_means_paper_unsupported(api):
    gyeol = vendor(api)
    assert confirm(api, D02).status_code == 200  # 합지 '빼기'
    pid = _project(api, grade="economy")
    e = _estimate(gyeol, pid)
    assert e.paper_ok is False and e.grade == "economy"
    hapji = next(x for x in e.lines if x.key == "paper_hapji")
    assert (hapji.mode, hapji.amount) == ("excluded", 0)
    assert _estimate(gyeol, pid, grade="basic").paper_ok is True
    many = _run(lambda s: _many(s, [gyeol, uuid.uuid4()], pid))
    assert list(many) == [gyeol]


async def _many(s, ids, pid):
    p = await project_service.get_out(s, pid)
    return await service.estimates_v3_for(s, vendor_ids=ids, project=p, trade="dobae")


def test_partial_project_estimate_uses_shared_quantities(api):
    maru = vendor(api, "maru@mitjip.test")
    assert confirm(api, MARU).status_code == 200
    pid = _project(api, scope="partial", spaces=["living", "kitchen"], faces=["wall"])
    e = _estimate(maru, pid)
    qty = {x.key: x.qty for x in e.lines}
    assert (qty["putty"], qty["paper_silk"], qty["labor"]) == (
        Decimal("6.5"),  # 2방 표 거실 0.20 + 주방 0.11 = 0.31 몫
        Decimal("11.3"),  # 벽 29.9㎡ × 1.248 = 37.3㎡
        Decimal("1.0"),
    )

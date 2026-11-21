"""v4 조건별 두 기준(ADR docs/v4/adr/0004)을 표준견적서 API로: 공사 조건으로 계산 엔진이 기준을 고르고,
판(price_ver)을 저장본에 고정한다. 모은 조건이 바뀌면 새 버전을 쌓고 앞 버전 줄은 그대로 둔다."""

from decimal import Decimal

from app.calc import dobae
from app.calc.common import COUNTED
from app.quote.service import standard_v3
from tests.conftest import query
from tests.helpers import signup
from tests.test_project import body as v2_body
from tests.test_v3_project_home import HOME, create


def _dobae(st: dict) -> dict:
    return next(t for t in st["trades"] if t["trade"] == "dobae")


def _keys(t: dict) -> dict[str, str]:
    return {ln["key"]: ln["state"] for ln in t["lines"]}


def _say(pid: str, key: str, value: str) -> None:
    """고객이 되묻기 단추로 고른 값(모은 조건). 대화 저장과 같은 표에 바로 넣는다"""
    query(
        "insert into project_conditions (id, project_id, trade, key, value)"
        " values (gen_random_uuid(), $1::uuid, 'mokgong', $2, $3)"
        " on conflict (project_id, key) do update set value = excluded.value",
        pid,
        key,
        value,
    )


def test_paper_only_project_gets_market_profile(api):
    signup(api)
    pid = create(api, HOME).json()["id"]
    st = api.get(f"/projects/{pid}/standard").json()
    t = _dobae(st)
    assert (st["price_ver"], t["profile"], t["profile_name"]) == (
        "2026.11b-market",
        "paper_only",
        "도배만 하는 공사 기준",
    )
    assert _keys(t) == {
        "wall": "included",
        "ceiling": "included",
        "paper": "included",
        "material": "included",
        "putty": "optional",
        "truck": "optional",
        "removal": "after_visit",
        "waste": "after_visit",
    }
    # 화면 숫자는 계산 엔진 그대로(같은 집 · 같은 판)
    h = dobae.HomeV3(Decimal("69.4"), "supply", "basic", False)
    q = standard_v3(h).quote
    assert (t["supply"], t["total"]) == (q.subtotal, q.total)
    counted = sum(ln["amount"] for ln in t["lines"] if ln["state"] in COUNTED)
    assert counted == t["supply"]
    assert t["notes"][0].startswith("도배만 하는 공사 기준으로 셌어요")


def test_condition_switches_profile_and_keeps_the_old_version(api):
    signup(api)
    pid = create(api, HOME).json()["id"]
    first = _dobae(api.get(f"/projects/{pid}/standard").json())
    _say(pid, "mokgong.doors", "문틀까지")
    second = _dobae(api.get(f"/projects/{pid}/standard").json())
    assert (second["version"], second["profile"]) == (first["version"] + 1, "remodel")
    assert {"meal", "putty", "truck"} <= {k for k, v in _keys(second).items() if v == "included"}
    assert second["total"] > first["total"]
    assert second["notes"][0].startswith("리모델링 기준으로 셌어요(근거: 문틀 교체)")
    # 앞 버전은 그 판 · 줄 그대로
    rows = query(
        "select q.version, q.price_ver, l.key, l.unit_price from standard_quotes q"
        " join standard_quote_lines l on l.quote_id = q.id"
        " where q.project_id = $1::uuid and q.trade = 'dobae' and l.key = 'material'"
        " order by q.version",
        pid,
    )
    assert [(r["version"], r["price_ver"], r["unit_price"]) for r in rows] == [
        (1, "2026.11b-market", 6_900),
        (2, "2026.11b-remodel", 16_000),
    ]
    # 같은 조건이면 저장본을 다시 써요
    assert _dobae(api.get(f"/projects/{pid}/standard").json())["version"] == 2
    # '문짝만'으로 바꾸면 다시 도배만 하는 공사 기준(새 버전)
    _say(pid, "mokgong.doors", "문짝만")
    third = _dobae(api.get(f"/projects/{pid}/standard").json())
    assert (third["version"], third["profile"], third["total"]) == (3, "paper_only", first["total"])


def test_v2_project_profile_follows_carpentry_items(api):
    """옛 v2 공사: 몰딩 · 걸레받이만이면 도배만 하는 공사 기준, 방문(문틀) 교체가 있으면 리모델링 기준.
    목공 표준견적서 줄에는 기준이 없어요."""
    signup(api)
    light = api.post("/projects", json=v2_body())  # 목공: 몰딩 · 걸레받이
    assert light.status_code == 201, light.text
    st = api.get(f"/projects/{light.json()['id']}/standard").json()
    by = {t["trade"]: t for t in st["trades"]}
    assert (by["dobae"]["profile"], by["mokgong"]["profile"]) == ("paper_only", None)
    trades = {
        "dobae": {"spaces": ["a", "b", "c"], "grade": "basic"},
        "mokgong": {"spaces": ["b", "c"], "items": ["molding", "door"]},
    }
    big = api.post("/projects", json=v2_body(trades=trades))
    assert big.status_code == 201, big.text
    st2 = api.get(f"/projects/{big.json()['id']}/standard").json()
    dobae = _dobae(st2)
    assert dobae["profile"] == "remodel"
    assert dobae["notes"][0].startswith("리모델링 기준으로 셌어요(근거: 문틀 교체)")
    prices = query("select trade, price_ver from standard_quotes order by trade, price_ver")
    assert [(x["trade"], x["price_ver"]) for x in prices] == [
        ("dobae", "2026.11b-market"),
        ("dobae", "2026.11b-remodel"),
        ("mokgong", "2026H2"),
        ("mokgong", "2026H2"),
    ]

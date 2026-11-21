"""표준견적서: 처음 볼 때 계산해 저장하고, 집 정보를 고치면 새 버전을 쌓는다."""

from tests.conftest import query
from tests.helpers import signup, vendor_signup
from tests.test_project import body


def test_standard_is_saved_once_and_counts_only_included(api):
    signup(api)
    p = api.post(
        "/projects",
        json=body(size={"basis": "supply", "m2": "105.8"}, occupied=False, balcony_ext=False),
    ).json()
    r = api.get(f"/projects/{p['id']}/standard")
    assert r.status_code == 200, r.text
    st = r.json()
    assert [t["trade"] for t in st["trades"]] == ["mokgong", "dobae"]
    dobae = st["trades"][1]
    # 도배 면적 = 공급 105.8 × 1.55 + 방 3개(32평 기본값) × 20.4 = 225.2㎡. 목공은 몰딩 · 걸레받이뿐이라
    # 도배만 하는 공사 기준(판 2026.11b-market, ADR 0004 · 0006): 도배지 85.0 벽지 평, 부자재 32평 × 6,900원
    # (옛 판 2026H2-rooms 2,485,576 · 2,734,134)
    assert dobae["supply"] == 2_684_083 and dobae["total"] == 2_952_491
    assert dobae["profile"] == "paper_only" and st["trades"][0]["profile"] is None
    assert dobae["man_day"] == "6.0"  # 표준품셈 6.28품 × 0.91 → 6.0 (앞 판 6.5)
    counted = sum(ln["amount"] for ln in dobae["lines"] if ln["state"] in ("included", "separate"))
    assert counted == dobae["supply"]
    assert st["total"] == sum(t["total"] for t in st["trades"]) == st["supply"] + st["vat"]
    assert st["code"] == p["code"] and st["pyeong"] == "32.0"
    assert st["budget"] == {"band": "500-700", "status": "within", "over_by": None}

    again = api.get(f"/projects/{p['id']}/standard").json()
    assert again["trades"][1]["version"] == 1
    assert len(query("select 1 from standard_quotes")) == 2


def test_edit_makes_a_new_version(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    first = api.get(f"/projects/{p['id']}/standard").json()
    edited = body(trades={"dobae": {"spaces": ["a"], "grade": "economy"}})
    assert api.patch(f"/projects/{p['id']}", json=edited).status_code == 200
    st = api.get(f"/projects/{p['id']}/standard").json()
    assert [t["trade"] for t in st["trades"]] == ["dobae"]
    assert st["trades"][0]["version"] == 2 and st["trades"][0]["grade"] == "economy"
    assert st["total"] < first["total"]
    assert st["project_rev"] == 2


def test_only_owner_sees_the_standard(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{p['id']}/standard").status_code == 404
    assert vendor_signup(api).status_code == 201
    assert api.get(f"/projects/{p['id']}/standard").status_code == 404

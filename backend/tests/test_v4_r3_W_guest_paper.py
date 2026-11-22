"""QA 3차 v1 L8: 손님 표준견적서(POST /guest/standard)도 직접 할 일 '벽지 직접 구매'를 빼고 센다.

가입 창은 "넣은 답과 표준견적서가 그대로 이어져요"라서, 같은 답(직접 할 일 포함)으로 가입 뒤 만든 공사의
표준견적서와 합계 · 도배지 줄 · 롤 수가 같아야 한다(둘 다 계산 엔진 값). 저장은 하지 않는다. 유료 호출 0회."""

from decimal import Decimal

from app.calc import rolls
from tests.helpers import signup
from tests.test_v3_guest_standard import HOME, URL, rows_in_db
from tests.test_v3_project_home import create


def _paper(lines: list[dict]) -> dict:
    return next(ln for ln in lines if ln["key"] == "paper")


def test_guest_standard_takes_paper_out_when_customer_buys_it(api):
    base = api.post(URL, json=HOME).json()
    before = rows_in_db()
    r = api.post(URL, json={**HOME, "diy": ["paint", "paper_buy"]})
    assert r.status_code == 200, r.text
    g = r.json()
    paper = _paper(g["lines"])
    # 도배지 줄은 '안 함'(고객 구매)으로 합계 밖, 금액은 참고로 남아요
    assert g["own_paper"] is True and base["own_paper"] is False
    assert paper["state"] == "excluded" and paper["source"].startswith("고객 구매 · ")
    assert paper["amount"] == _paper(base["lines"])["amount"]
    assert g["supply"] == base["supply"] - paper["amount"]
    assert g["total"] < base["total"]
    # 사야 할 롤 수(계산 엔진, 보이기용)
    assert g["rolls_text"] == rolls.need("silk", paper_py=Decimal(paper["qty"])).text
    assert base["rolls_text"] is None
    assert rows_in_db() == before  # 손님 계산은 저장하지 않아요


def test_other_diy_chips_keep_the_paper_in(api):
    base = api.post(URL, json=HOME).json()
    for diy in ([], ["paint", "clean"]):
        g = api.post(URL, json={**HOME, "diy": diy}).json()
        assert (g["own_paper"], g["total"], g["rolls_text"]) == (False, base["total"], None)
        assert _paper(g["lines"])["state"] == "included"


def test_guest_total_is_the_total_after_signup(api):
    """가입 창 '넣은 답과 표준견적서가 그대로 이어져요': 같은 답으로 만든 공사의 표준견적서와 같아요"""
    body = {**HOME, "diy": ["paper_buy"]}
    g = api.post(URL, json=body).json()
    signup(api)
    pid = create(api, body).json()["id"]
    r = api.get(f"/projects/{pid}/standard")
    assert r.status_code == 200, r.text
    t = next(x for x in r.json()["trades"] if x["trade"] == "dobae")
    assert t["own_paper"] is True
    assert (g["supply"], g["vat"], g["total"]) == (t["supply"], t["vat"], t["total"])
    assert _paper(g["lines"])["state"] == _paper(t["lines"])["state"] == "excluded"
    assert g["rolls_text"] == t["rolls"]["text"]

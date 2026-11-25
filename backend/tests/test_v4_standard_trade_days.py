"""표준견적서 공정별 기간(2026-11-23 LLM 판정 set30:xd105): 도배만 보여 주는 카드에 목공+도배를 합친 기간이 붙었어요.
공정마다 계산 엔진 기간(StandardTradeOut.days)을 싣고, 한 공정 카드 · 도구 값은 그 공정 기간을 써요. 유료 호출 0회."""

from decimal import Decimal

from tests.helpers import signup
from tests.test_project import body


def two_trades(api) -> str:
    signup(api, "two-trades@mitjip.test")
    r = api.post("/projects", json=body())  # 도배 + 목공
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_standard_carries_days_per_trade(api):
    pid = two_trades(api)
    got = api.get(f"/projects/{pid}/standard").json()
    days = {t["trade"]: Decimal(str(t["days"])) for t in got["trades"]}
    assert set(days) == {"mokgong", "dobae"} and all(d > 0 for d in days.values())
    assert sum(days.values()) == Decimal(str(got["days"]))  # 전체 기간 = 공정별 기간의 합

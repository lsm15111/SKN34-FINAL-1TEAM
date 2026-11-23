"""표준견적서 공정별 기간(2026-11-23 LLM 판정 set30:xd105): 도배만 보여 주는 카드에 목공+도배를 합친 기간이 붙었어요.
공정마다 계산 엔진 기간(StandardTradeOut.days)을 싣고, 한 공정 카드 · 도구 값은 그 공정 기간을 써요. 유료 호출 0회."""

from decimal import Decimal

import pytest

from app.agent import llm
from tests.helpers import signup
from tests.test_project import body
from tests.test_v4_assistant_copy_fixes import result_of
from tests.test_v4_assistant_turns import ask, ok


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


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


def test_one_trade_card_uses_that_trade_days(api, script):
    pid = two_trades(api)
    std = api.get(f"/projects/{pid}/standard").json()
    dobae = Decimal(str(next(t["days"] for t in std["trades"] if t["trade"] == "dobae")))
    assert dobae < Decimal(str(std["days"]))
    get = {"id": "s", "name": "get_standard_quote", "input": {"trade": "dobae"}}
    log = script([{"tool_calls": [get]}, {"text": "도배 표준견적서를 보여 드렸어요."}])
    ev = ok(ask(api, pid, "도배 표준견적서 보여 줘"))
    got = result_of(log, 1)
    assert (Decimal(str(got["days"])), got["days_for"]) == (dobae, ["도배"])
    card = next(d for e, d, _ in ev if e == "card" and d["kind"] == "standard_quote")
    assert Decimal(str(card["data"]["days"])) == dobae

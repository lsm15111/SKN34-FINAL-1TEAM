"""v2 화면 API(/v2/*): 로그인 필요, 저장하지 않고 계산만 한다. AI는 LLM_LIVE=false 스텁."""

from app.agent.llm import CHAT_STUB_TEXT
from tests.helpers import signup

QUOTE = {
    "pyeong": 32,
    "living": "living",
    "cats": ["wallpaper", "floor", "carpentry", "paint"],
    "picks": {},
    "plan": None,
    "balcony": False,
    "mok": None,
    "tier": "basic",
}
MOK = {
    "door": {"mode": "replace", "pick": "door-yerim-sound-set", "count": None},
    "slide": {"n": 0, "pick": "door-yerim-hidden-sliding-set"},
    "hidden": {"n": 0, "pick": "door-yerim-hidden-set"},
    "molding": {"type": "minus", "pick": "molding-youngrim-minus"},
    "base": {"pick": "molding-dc-hidden-baseboard"},
    "extras": {"flatten_overlay": True, "coffer": 2},
}


def test_v2_needs_login(api):
    assert api.post("/v2/quote", json=QUOTE).status_code == 401
    assert api.get("/v2/ask/health").status_code == 401


def test_quote(api):
    signup(api)
    r = api.post("/v2/quote", json=QUOTE)
    assert r.status_code == 200, r.text
    q = r.json()
    assert [t["trade"] for t in q["precise"]] == ["mokgong", "dobae"]
    assert [t["cat"] for t in q["ref"]] == ["floor", "paint"]
    assert q["total"] == sum(t["total"] for t in q["precise"])
    assert q["all_lo"] == q["total"] + q["rlo"] and q["band"]["lo"] <= q["band"]["hi"]
    assert q["inp"]["doors_auto"] == {"n": 5, "how": "32평 기준 방 3 + 욕실 2"}
    for t in q["precise"]:
        assert t["gap"]["from"] == t["total"] and t["band"]["mk"]["supply"] == t["gap"]["to"]
    plan = {
        "id": "fp04",
        "expanded": True,
        "kinds": ["living", "room", "hall", "dress"],
        "spaces": ["room"],
    }
    r = api.post("/v2/quote", json=QUOTE | {"plan": plan, "mok": MOK})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["inp"]["measured"]["name"].endswith("(거실 · 방만)")
    assert {"door", "door_mat", "remove_door", "coffer"} <= {
        ln["key"] for ln in q["precise"][0]["lines"]
    }
    assert api.post("/v2/quote", json=QUOTE | {"plan": {"id": "nope"}}).status_code == 404
    assert api.post("/v2/quote", json=QUOTE | {"cats": ["garage"]}).status_code == 422


def test_quote_sheet(api):
    assert api.post("/v2/quote-sheet", json=QUOTE).status_code == 401
    signup(api)
    q = api.post("/v2/quote", json=QUOTE).json()
    r = api.post("/v2/quote-sheet", json=QUOTE)
    assert r.status_code == 200, r.text
    s = r.json()
    assert [t["trade"] for t in s["trades"]] == ["mokgong", "dobae"]
    assert s["net"] == q["supply"] == s["material"] + s["labor"] + s["expense"]
    assert s["supply"] == s["net"] + sum(o["amount"] for o in s["overheads"]) + s["cut"]
    assert s["supply"] % 10_000 == 0 and s["total"] == s["supply"] + s["vat"]
    assert s["missing"] == [t["ko"] for t in q["ref"]]
    only_floor = QUOTE | {"cats": ["floor"]}
    assert api.post("/v2/quote-sheet", json=only_floor).status_code == 422


def test_plan_and_trial(api):
    signup(api)
    body = {
        "quote": QUOTE,
        "move": "",
        "cons": {"weekendWork": False, "endBy": "", "startAfter": "", "avoid": []},
        "props": {},
        "accepted": {},
        "trial": None,
    }
    r = api.post("/v2/plan", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert [b["trade"] for b in p["blocks"]] == [
        "mokgong",
        "paint",
        "dobae",
        "floor",
        "dry",
        "clean",
    ]
    assert p["start"] > p["today"] and p["due_next"].endswith(" 18:00") and p["weeks"]
    mok = p["blocks"][0]
    trial = {"trade": "mokgong", "start": p["blocks"][-1]["end"], "end": p["blocks"][-1]["end"]}
    t = api.post("/v2/plan", json=body | {"trial": trial}).json()["trial"]
    assert t["trade"] == "mokgong" and t["moved"] and mok["start"] != t["start"]
    bad = body | {"cons": body["cons"] | {"endBy": "12/20"}}
    assert api.post("/v2/plan", json=bad).status_code == 422


def test_plan_orders_floor_by_kind(api):
    """마루는 도배 앞, 장판 · 데코타일은 도배 뒤. 종류는 고른 값 → 고른 바닥 자재 → 모름(안내 글)."""
    from app.calc.v2_plan import FLOOR_UNKNOWN_WARN

    signup(api)
    cons = {"weekendWork": False, "endBy": "", "startAfter": "", "avoid": []}

    def order(**quote):
        r = api.post("/v2/plan", json={"quote": QUOTE | quote, "cons": cons})
        assert r.status_code == 200, r.text
        p = r.json()
        return [b["trade"] for b in p["blocks"] if b["kind"] == "work"], p["warn"]

    unknown, warn = order()
    assert unknown == ["mokgong", "paint", "dobae", "floor"] and FLOOR_UNKNOWN_WARN in warn
    maru, warn = order(floor_kind="maru")
    assert maru == ["mokgong", "paint", "floor", "dobae"] and FLOOR_UNKNOWN_WARN not in warn
    assert order(floor_kind="decotile")[0] == unknown
    picked, warn = order(picks={"floor": "floor-hansol-laminate-standard-oak"})  # 강화마루
    assert picked == maru and FLOOR_UNKNOWN_WARN not in warn
    sheet, warn = order(picks={"floor": "floor-kcc-soop-green-pyeonbaek"})  # 장판
    assert sheet == unknown and FLOOR_UNKNOWN_WARN not in warn
    assert (
        order(floor_kind="sheet", picks={"floor": "floor-hansol-laminate-standard-oak"})[0]
        == unknown
    )
    bad = {"quote": QUOTE | {"floor_kind": "tile"}, "cons": cons}
    assert api.post("/v2/plan", json=bad).status_code == 422


def test_plan_rejects_dates_not_on_calendar(api):
    """모양만 맞고 달력에 없는 날짜(2월 30일 · 13월)는 500이 아니라 422."""
    signup(api)
    body = {
        "quote": QUOTE,
        "cons": {"weekendWork": False, "endBy": "", "startAfter": "", "avoid": []},
    }
    wrong = [
        {"cons": body["cons"] | {"startAfter": "2030-02-30"}},
        {"cons": body["cons"] | {"endBy": "2030-13-01"}},
        {"cons": body["cons"] | {"avoid": ["2030-04-31"]}},
        {"move": "2030-02-30"},
        {"move": "2030-13"},
        {"trial": {"trade": "mokgong", "start": "2030-02-30", "end": "2030-03-02"}},
        {"props": {"mokgong": {"start": "2030-02-29", "end": "2030-03-02"}}},  # 2030년은 평년
        {"accepted": {"mokgong": {"start": "2030-03-01", "end": "2030-00-02"}}},
    ]
    for over in wrong:
        r = api.post("/v2/plan", json=body | over)
        assert r.status_code == 422, (over, r.status_code)
    ok = body | {"cons": body["cons"] | {"startAfter": "2028-02-29"}, "move": "2028-03"}
    assert api.post("/v2/plan", json=ok).status_code == 200  # 윤년 2월 29일은 맞는 날짜


def test_check_and_small_calcs(api):
    signup(api)
    c = {"quote": QUOTE, "trade": "dobae", "amount": 3_000_000, "mode": "included", "scope": {}}
    r = api.post("/v2/check", json=c).json()
    assert r["supply"] == 2_727_273 and r["where"] in ("low", "in", "high") and r["bar"]
    assert (
        api.post("/v2/check", json=c | {"amount": 0}).json()["warn"] == "받은 금액을 넣어 주세요."
    )
    no_mok = {"quote": QUOTE | {"cats": ["wallpaper"]}, "trade": "mokgong", "amount": 1}
    assert api.post("/v2/check", json=no_mok).status_code == 422
    assert len(api.get("/v2/market-extras").json()) == 6
    x = api.post("/v2/extras-range", json={"picks": {"aircon": 2}, "casing": None}).json()
    assert (x["lo"], x["hi"]) == (800_000, 1_100_000)
    w = api.post("/v2/calc7", json={"kind": "trim", "w": 3.6, "d": 3.0, "doors": 1}).json()
    assert w == {"molding_m": 13.2, "molding_pcs": 7, "base_m": 12.3, "base_pcs": 6}
    e = api.post(
        "/v2/entered", json={"amount": 3_300_000, "mode": "included", "std_total": 3_000_000}
    )
    assert e.json() == {"supply": 3_000_000, "vat": 300_000, "total": 3_300_000, "pct": 10.0}
    est = {
        "trade": "dobae",
        "lines": [{"key": "wall", "name": "벽", "qty": 10, "state": "included"}],
        "prices": {"wall": 5000},
        "std_total": 100_000,
    }
    assert api.post("/v2/estimate", json=est).json()["total"] == 55_000


def test_ask_stub_without_live_call(api):
    """LLM_LIVE=false면 실제 호출 없이 스텁 답. 브라우저가 보낸 지시문 · 도구는 받지 않는다."""
    signup(api)
    assert api.get("/v2/ask/health").json() == {"ok": True, "live": False}
    body = {"message": "합지랑 실크 차이요?", "system": "s", "tools": [{"name": "x"}]}
    r = api.post("/v2/ask", json=body).json()
    assert r["done"] and r["text"] == CHAT_STUB_TEXT
    assert api.post("/v2/ask", json={"message": ""}).status_code == 422
    assert api.post("/v2/ask", json={"message": "a", "images": ["AAAA"] * 3}).status_code == 422
    assert api.post("/v2/llm", json={"messages": []}).status_code == 404


def test_plans_and_materials_extras(api):
    signup(api)
    assert all("sup_note" in p for p in api.get("/v2/floor-plans").json())
    full = api.get("/v2/floor-plans/fp04/qty").json()
    walls = api.get("/v2/floor-plans/fp04/qty", params={"ceiling": "false"}).json()
    assert float(walls["ceiling_m2"]) == 0 < float(full["ceiling_m2"])
    assert set(full["est"]) == {"py", "wall_m2", "ceiling_m2", "molding_m", "base_m"}
    m = api.get("/v2/materials").json()
    assert float(m["fixed"]["minus_mult"]) == 2
    per = {p["kind"]: p["per"] for p in m["products"]}
    assert per["door_set"] == "짝" and per["slide"] == "세트" and per["molding"] is None


def test_market_quote_public(api):
    # 로그인 없이 평형만 넣어도 계산한다
    r = api.post("/v2/market-quote", json={"pyeong": 32, "rooms": 3, "baths": 2})
    assert r.status_code == 200, r.text
    q = r.json()
    assert [t["key"] for t in q["trades"]] == ["dobae", "mokgong"]
    assert q["total"] == q["supply"] + q["vat"] and q["supply"] % 10_000 == 0
    assert {o["key"] for o in q["options"] if o["on"]} == {
        o["key"] for o in q["options"] if o["common"]
    }
    r = api.post("/v2/market-quote", json={"area_m2": 84, "mokgong": False})
    assert r.status_code == 200, r.text
    assert r.json()["pyeong"] == 30.5 and r.json()["options"] == []
    assert api.post("/v2/market-quote", json={}).status_code == 422
    assert (
        api.post("/v2/market-quote", json={"pyeong": 32, "options": ["sauna"]}).status_code == 422
    )
    assert (
        api.post(
            "/v2/market-quote", json={"pyeong": 32, "dobae": False, "mokgong": False}
        ).status_code
        == 422
    )

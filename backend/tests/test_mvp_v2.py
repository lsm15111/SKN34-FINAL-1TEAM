"""v2 화면 API(/mvp/v2/*): 로그인 필요, 저장하지 않고 계산만 한다. AI는 LLM_LIVE=false 스텁."""

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
    assert api.post("/mvp/v2/quote", json=QUOTE).status_code == 401
    assert api.get("/mvp/v2/llm/health").status_code == 401


def test_quote(api):
    signup(api)
    r = api.post("/mvp/v2/quote", json=QUOTE)
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
    r = api.post("/mvp/v2/quote", json=QUOTE | {"plan": plan, "mok": MOK})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["inp"]["measured"]["name"].endswith("(거실 · 방만)")
    assert {"door", "door_mat", "remove_door", "coffer"} <= {
        ln["key"] for ln in q["precise"][0]["lines"]
    }
    assert api.post("/mvp/v2/quote", json=QUOTE | {"plan": {"id": "nope"}}).status_code == 404
    assert api.post("/mvp/v2/quote", json=QUOTE | {"cats": ["garage"]}).status_code == 422


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
    r = api.post("/mvp/v2/plan", json=body)
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
    t = api.post("/mvp/v2/plan", json=body | {"trial": trial}).json()["trial"]
    assert t["trade"] == "mokgong" and t["moved"] and mok["start"] != t["start"]
    bad = body | {"cons": body["cons"] | {"endBy": "12/20"}}
    assert api.post("/mvp/v2/plan", json=bad).status_code == 422


def test_check_and_small_calcs(api):
    signup(api)
    c = {"quote": QUOTE, "trade": "dobae", "amount": 3_000_000, "mode": "included", "scope": {}}
    r = api.post("/mvp/v2/check", json=c).json()
    assert r["supply"] == 2_727_273 and r["where"] in ("low", "in", "high") and r["bar"]
    assert (
        api.post("/mvp/v2/check", json=c | {"amount": 0}).json()["warn"]
        == "받은 금액을 넣어 주세요."
    )
    no_mok = {"quote": QUOTE | {"cats": ["wallpaper"]}, "trade": "mokgong", "amount": 1}
    assert api.post("/mvp/v2/check", json=no_mok).status_code == 422
    assert len(api.get("/mvp/v2/market-extras").json()) == 6
    x = api.post("/mvp/v2/extras-range", json={"picks": {"aircon": 2}, "casing": None}).json()
    assert (x["lo"], x["hi"]) == (800_000, 1_100_000)
    w = api.post("/mvp/v2/calc7", json={"kind": "trim", "w": 3.6, "d": 3.0, "doors": 1}).json()
    assert w == {"molding_m": 13.2, "molding_pcs": 7, "base_m": 12.3, "base_pcs": 6}
    e = api.post(
        "/mvp/v2/entered", json={"amount": 3_300_000, "mode": "included", "std_total": 3_000_000}
    )
    assert e.json() == {"supply": 3_000_000, "vat": 300_000, "total": 3_300_000, "pct": 10.0}
    est = {
        "trade": "dobae",
        "lines": [{"key": "wall", "name": "벽", "qty": 10, "state": "included"}],
        "prices": {"wall": 5000},
        "std_total": 100_000,
    }
    assert api.post("/mvp/v2/estimate", json=est).json()["total"] == 55_000


def test_llm_stub_and_limits(api):
    signup(api)
    assert api.get("/mvp/v2/llm/health").json() == {"ok": True, "live": False}
    msg = {
        "role": "user",
        "content": [{"type": "text", "text": "안녕"}, {"type": "image", "data": "AAAA"}],
    }
    tool = {
        "name": "search_knowledge",
        "description": "자료 찾기",
        "parameters": {"type": "object"},
    }
    r = api.post("/mvp/v2/llm", json={"system": "s", "messages": [msg], "tools": [tool]})
    assert r.json() == {"text": CHAT_STUB_TEXT, "tool_calls": [], "stop": "stop"}
    one = {"role": "user", "content": "a"}
    assert api.post("/mvp/v2/llm", json={"messages": [one] * 31}).status_code == 422
    assert (
        api.post("/mvp/v2/llm", json={"system": "a" * 60_001, "messages": [one]}).status_code == 422
    )
    assert (
        api.post("/mvp/v2/llm", json={"messages": [one], "tools": [tool] * 13}).status_code == 422
    )
    five = {"role": "user", "content": [{"type": "image", "data": "AAAA"}] * 5}
    assert api.post("/mvp/v2/llm", json={"messages": [five]}).status_code == 422


def test_plans_and_materials_extras(api):
    signup(api)
    assert all("sup_note" in p for p in api.get("/mvp/plans").json())
    full = api.get("/mvp/plans/fp04/qty").json()
    walls = api.get("/mvp/plans/fp04/qty", params={"ceiling": "false"}).json()
    assert float(walls["ceiling_m2"]) == 0 < float(full["ceiling_m2"])
    assert set(full["est"]) == {"py", "wall_m2", "ceiling_m2", "molding_m", "base_m"}
    m = api.get("/mvp/materials").json()
    assert float(m["fixed"]["minus_mult"]) == 2
    per = {p["kind"]: p["per"] for p in m["products"]}
    assert per["door_set"] == "짝" and per["slide"] == "세트" and per["molding"] is None

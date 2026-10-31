"""설비 공정 4종(욕실 · 주방 · 전기·조명 · 창호)의 상담 등록: 폼 답 → 견적, 모르겠어요 기본값과 확인 표시,
묻는 조건, 이은 공정표, 겹침 알림. LLM은 부르지 않는다 (LLM_LIVE=false 스텁)."""

import re
from decimal import Decimal

import pytest

from app.consult.trades import ORDER, REGISTRY, catalog
from app.consult.trades import overlaps as ov
from app.consult.trades.base import Common
from tests.helpers import signup
from tests.test_consult import answers, fields, turn

COMMON = [("area", "34"), ("area_basis", "supply"), ("occupied", "no")]
HOME = Common(area_m2=Decimal("112.4"), area_basis="supply", occupied=False)
NEW = ("bath", "kitchen", "electric", "window")
RULE = {(r.a, r.b): r.text for r in ov.RULES}
# 공정마다 칸 값 (조건이 켜지는 칸까지) · 첫 폼에 묻는 칸 · 공급 34평 빈집 합계 (VAT 별도, VAT, 합계)
CASES = {
    "bath": (
        {"baths": 1, "scope": "full", "tile_method": "remove", "tub": "keep", "ceiling": "smc"},
        ["baths", "scope"],
        (2_716_938, 271_694, 2_988_632),
    ),
    "kitchen": (
        {"layout": "straight", "length": "fit", "top": "acrylic", "parts": "both"},
        ["layout", "length", "top", "parts"],
        (2_710_000, 271_000, 2_981_000),
    ),
    "electric": (
        {
            "items": ["lights", "outlets"],
            "light_range": "all",
            "light_type": "flat",
            "outlet_range": "all",
        },
        ["items"],
        (2_717_844, 271_784, 2_989_628),
    ),
    "window": (
        {"scope": "all", "frame": "pvc", "glass": "low_e"},
        ["scope", "frame", "glass"],
        (9_583_722, 958_372, 10_542_094),
    ),
}


def pairs(trade: str, values: dict) -> list[tuple[str, object]]:
    """칸 값을 폼 답으로 (숫자는 글자로)"""
    return [(f"{trade}.{k}", str(v) if isinstance(v, int) else v) for k, v in values.items()]


def asked(trade: str, values: dict) -> list[str]:
    return [f.key for f in REGISTRY[trade].missing(values)]


@pytest.mark.parametrize("trade", NEW)
def test_form_answers_reach_a_standard_quote(api, trade):
    values, first, (subtotal, vat, total) = CASES[trade]
    signup(api)
    out = turn(api, trades=[trade])
    assert fields(out) == ["area", "area_basis", "occupied"] + [f"{trade}.{k}" for k in first]
    out = turn(api, out["card"], answers=answers(COMMON + pairs(trade, values)))
    assert out["questions"] == [] and out["card"]["to_check"] == []
    assert out["card"]["values"] == {trade: values}
    (res,) = out["results"]
    q = res["quote"]
    assert (res["trade"], res["label"], q["version"]) == (trade, REGISTRY[trade].label, "2026H2")
    assert (q["subtotal"], q["vat"], q["total"]) == (subtotal, vat, total)
    s = out["summary"]
    assert (s["subtotal"], s["vat"], s["total"]) == (subtotal, vat, total)
    assert Decimal(s["days"]) == Decimal(sum(st["half_days"] for st in out["schedule"])) / 2
    # 가정값 줄은 '가정' 배지로 드러난다
    assert s["basis_counts"]["assumed"] >= 1
    assert res["plan"] is None and res["plan_status"] == "failed"


@pytest.mark.parametrize("trade", NEW)
def test_unknown_answers_use_defaults_and_are_checked(api, trade):
    signup(api)
    # 전기는 할 일을 골라야 해요 (모르겠어요가 없는 칸)
    picks = {"electric.items": ["lights", "outlets", "points"]}
    out = turn(api, trades=[trade], answers=answers(COMMON))
    for _ in range(3):
        if not out["questions"]:
            break
        todo = [(q["field"], picks.get(q["field"], "unknown")) for q in out["questions"]]
        out = turn(api, out["card"], answers=answers(todo))
    assert out["questions"] == []
    want = {
        "bath": CASES["bath"][0],
        "kitchen": CASES["kitchen"][0],
        "electric": CASES["electric"][0] | {"items": picks["electric.items"], "new_points": 2},
        "window": CASES["window"][0],
    }[trade]
    card = out["card"]
    assert card["values"] == {trade: want}
    checked = [k for k in want if k != "items"]
    assert sorted(card["to_check"]) == sorted(f"{trade}.{k}" for k in checked)
    labels = {f.label for f in REGISTRY[trade].fields if f.key in checked}
    assert {f["label"] for f in out["facts"] if f["check"]} == labels
    assert out["results"][0]["quote"]["total"] == REGISTRY[trade].build(HOME, want).total


def test_bath_asks_tile_tub_and_ceiling_only_for_full_work(api):
    assert asked("bath", {}) == ["baths", "scope"]
    assert asked("bath", {"baths": 2, "scope": "fixtures"}) == []
    assert asked("bath", {"baths": 2, "scope": "full"}) == ["tile_method", "tub", "ceiling"]
    # 범위를 도기 · 수전만으로 바꾸면 전체 공사 칸 값은 지운다
    stale = {"baths": 2, "scope": "fixtures", "tile_method": "overlay", "tub": "new"}
    assert REGISTRY["bath"].relevant(stale) == {"baths": 2, "scope": "fixtures"}

    signup(api)
    form = {"baths": 2, "scope": "fixtures", "tile_method": "overlay", "ceiling": "pvc"}
    out = turn(api, trades=["bath"], answers=answers(COMMON + pairs("bath", form)))
    assert out["card"]["values"] == {"bath": {"baths": 2, "scope": "fixtures"}}
    q = out["results"][0]["quote"]
    assert q["subtotal"] == 1_229_704  # 도기 · 수전 · 실리콘만
    assert not {"tile_wall", "ceiling", "tub"} & {ln["key"] for ln in q["lines"]}
    assert [st["key"] for st in q["steps"]] == ["remove", "fit", "finish"]


def test_electric_and_window_ask_counts_only_for_some():
    assert asked("electric", {}) == ["items"]
    assert asked("electric", {"items": ["lights"]}) == ["light_range", "light_type"]
    some = {"items": ["lights", "outlets"], "light_range": "some", "outlet_range": "some"}
    assert asked("electric", some) == ["light_count", "light_type", "outlet_count"]
    assert asked("electric", {"items": ["points"]}) == ["new_points"]
    # 조명을 빼면 조명 칸(범위 · 개수 · 종류)은 지운다
    stale = {"items": ["outlets"], "light_range": "some", "light_count": 3, "light_type": "line"}
    assert REGISTRY["electric"].relevant(stale) == {"items": ["outlets"]}
    # 할 일을 하나도 안 고르면 받지 않는다 (빈 공사가 계산 엔진에 가지 않게)
    with pytest.raises(ValueError):
        REGISTRY["electric"].field("items").read([])

    assert asked("window", {"scope": "all"}) == ["frame", "glass"]
    assert asked("window", {"scope": "some"}) == ["count", "frame", "glass"]
    assert asked("kitchen", {}) == ["layout", "length", "top", "parts"]


def test_spec_values_reach_the_calc_engine():
    kitchen = REGISTRY["kitchen"]
    base = CASES["kitchen"][0]
    assert kitchen.build(HOME, base).length_m == Decimal("3.4")  # 길이를 모르면 34평 × 0.1m
    assert kitchen.build(HOME, base | {"length": "3.6"}).length_m == Decimal("3.6")
    hood_only = {ln.key: ln.state for ln in kitchen.build(HOME, base | {"parts": "hood"}).lines}
    assert (hood_only["hood"], hood_only["sink"]) == ("included", "excluded")
    neither = {ln.key: ln.state for ln in kitchen.build(HOME, base | {"parts": "none"}).lines}
    assert neither["hood"] == neither["sink"] == "excluded"

    electric = REGISTRY["electric"]
    some = electric.build(
        HOME,
        {"items": ["lights"], "light_range": "some", "light_count": 4, "light_type": "downlight"},
    )
    assert (some.lights, some.outlets, some.switches) == (4, 0, 0)
    points = electric.build(HOME, {"items": ["points"], "new_points": 3})
    assert (points.lights, points.outlets, points.new_points) == (0, 3, 3)

    window = REGISTRY["window"]
    v = CASES["window"][0]
    ext = Common(HOME.area_m2, HOME.area_basis, HOME.occupied, balcony_ext=True)
    # 발코니 확장은 공통 칸으로 받는다 (따로 묻지 않는다)
    assert window.build(ext, v).windows == window.build(HOME, v).windows - 2
    assert window.build(HOME, v | {"scope": "some", "count": 4}).windows == 4


def test_schedule_puts_demolition_first_and_furniture_lighting_after_wallpaper(api):
    signup(api)
    electric = CASES["electric"][0] | {"items": ["lights", "points"], "new_points": 2}
    form = (
        COMMON
        + pairs("window", CASES["window"][0])
        + pairs("electric", electric)
        + [("mokgong.items", ["molding", "base"])]
        + pairs("bath", CASES["bath"][0])
        + pairs("kitchen", CASES["kitchen"][0])
        + [("dobae.grade", "basic"), ("dobae.include_ceiling", "yes")]
    )
    picked = ["dobae", "bath", "kitchen", "mokgong", "window", "electric"]
    out = turn(api, trades=picked, answers=answers(form))
    assert out["questions"] == []
    assert [r["trade"] for r in out["results"]] == [t for t in ORDER if t in picked]
    sched = [(s["trade"], s["key"], s["phase"]) for s in out["schedule"]]
    assert sched == [
        # 철거는 공정마다 모아서 맨 앞
        ("window", "remove", "remove"),
        ("mokgong", "remove", "remove"),
        ("bath", "remove", "remove"),
        ("kitchen", "remove", "remove"),
        # 본 작업은 공정 순서: 창호 → 전기 배선 → 목공 → 욕실 → 도배
        ("window", "install", "main"),
        ("electric", "wire", "main"),
        ("mokgong", "trim", "main"),
        ("bath", "waterproof", "main"),
        ("bath", "tile", "main"),
        ("bath", "fit", "main"),
        ("dobae", "paper", "main"),
        # 도배 뒤: 주방 가구 → 조명 · 콘센트
        ("kitchen", "cabinet", "late"),
        ("kitchen", "top", "late"),
        ("kitchen", "fit", "late"),
        ("electric", "fixture", "late"),
        ("electric", "finish", "finish"),
    ]
    s = out["summary"]
    for k in ("subtotal", "vat", "total"):
        assert s[k] == sum(r["quote"][k] for r in out["results"])
    assert Decimal(s["days"]) == Decimal(sum(st["half_days"] for st in out["schedule"])) / 2
    # 도배 + 창호, 주방 + 전기를 같이 고르면 겹침 알림이 붙는다
    assert {RULE["dobae", "window"], RULE["electric", "kitchen"]} <= set(out["overlaps"])
    assert RULE["electric", "mokgong"] not in out["overlaps"]  # 평판 조명 · 평탄화 없음


def test_overlap_rules():
    keys = [(r.a, r.b) for r in ov.RULES]
    assert keys == sorted(keys) and all(a < b for a, b in keys)  # 공정 키 이름 순
    for text in RULE.values():
        assert not re.search(r"\d", text) and text.endswith("요.")
    # 욕실과 타일은 서로 다른 곳이라 알리지 않는다
    assert ("bath", "tile") not in RULE

    kitchen = {"kitchen": CASES["kitchen"][0]}
    assert ov.overlaps(["electric", "kitchen"], kitchen) == [RULE["electric", "kitchen"]]
    assert ov.overlaps(["kitchen"], kitchen) == []
    down = {"electric": {"items": ["lights"], "light_type": "downlight"}}
    flat = {"electric": {"items": ["lights"], "light_type": "flat"}}
    flatten = {"mokgong": {"items": ["molding", "flatten"]}}
    em = ["electric", "mokgong"]
    assert ov.overlaps(em, down | flatten) == [RULE["electric", "mokgong"]]
    assert ov.overlaps(em, flat | flatten) == []
    assert ov.overlaps(em, down | {"mokgong": {"items": ["molding"]}}) == []
    # 도장 · 필름 칸은 계산 엔진 입력 이름(surfaces · items)을 따른다
    pw = ["paint", "window"]
    assert ov.overlaps(pw, {"paint": {"surfaces": ["wall", "balcony"]}}) == [RULE[tuple(pw)]]
    assert ov.overlaps(pw, {"paint": {"surfaces": ["wall"]}}) == []
    fk = ["film", "kitchen"]
    assert ov.overlaps(fk, {"film": {"items": ["door", "kitchen"]}}) == [RULE[tuple(fk)]]
    assert ov.overlaps(fk, {"film": {"items": ["door"]}}) == []


def test_new_specs_card_lines_and_catalog():
    for trade in NEW:
        spec = REGISTRY[trade]
        rows = spec.card_lines(HOME, CASES[trade][0])
        # 공정 의견 에이전트가 숫자를 옮겨 쓰지 않게 칸 설명 줄 · 선택지 설명에는 숫자를 넣지 않는다
        assert rows and not any(re.search(r"\d", row) for row in rows), rows
        for f in spec.fields:
            assert not any(re.search(r"\d", c.desc) for c in f.choices), f.key
        assert spec.agent.label == spec.label and spec.agent.sources
    two = CASES["bath"][0] | {"baths": 2}
    assert REGISTRY["bath"].card_lines(HOME, two)[0] == "고칠 욕실: 두 칸"
    text = catalog()
    assert "- bath.baths | 고칠 욕실 수 | count | 숫자 1~3, unknown=모르겠어요" in text
    assert "- electric.items | 전기 공사 | multi | lights=조명 교체" in text
    # 작업 순서: 창호 → 전기 → 목공 → 욕실 → 주방 → 도배
    heads = [text.index(f"## {t}") for t in ("window", "electric", "mokgong", "bath", "kitchen")]
    assert heads == sorted(heads) and heads[-1] < text.index("## dobae")

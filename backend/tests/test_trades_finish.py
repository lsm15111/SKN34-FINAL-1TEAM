"""바닥재 · 타일 · 도장 · 필름 상담 등록: 폼 답 → 표준견적서, 모르겠어요 기본값, 조건 칸,
같이 쓰는 방문 개수, 공정표 잇기, 겹침 알림. LLM은 부르지 않는다 (LLM_LIVE=false 스텁)."""

from decimal import Decimal

import pytest

from app.calc import film, floor, paint, tile
from app.consult.schemas import QuoteOut
from app.consult.service import PLAN_FAILED
from app.consult.trades import LATE_ORDER, ORDER, REGISTRY, catalog
from app.consult.trades import overlaps as ov
from app.consult.trades.base import Common
from app.refprice.film import FILM_2026H2
from app.refprice.floor import FLOOR_2026H2
from app.refprice.paint import PAINT_2026H2
from app.refprice.tile import TILE_2026H2
from tests.helpers import signup

URL = "/consult"
AREA = Decimal("112.4")  # 공급 34평
COMMON = Common(area_m2=AREA, area_basis="supply", occupied=False)
COMMON_FORM = [("area", "34"), ("area_basis", "supply"), ("occupied", "no")]
FLOOR, TILE, PAINT, FILM = (REGISTRY[k] for k in ("floor", "tile", "paint", "film"))


def turn(api, card=None, **kw):
    r = api.post(URL, json={"card": card, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def answers(pairs):
    return [{"field": f, "value": v} for f, v in pairs]


def fields(out) -> list[str]:
    return [q["field"] for q in out["questions"]]


def test_specs_follow_the_calc_engine_and_work_order():
    mine = ("mokgong", "tile", "paint", "film", "floor", "dobae")
    assert [k for k in ORDER if k in mine] == list(mine)
    assert "floor" in LATE_ORDER and FLOOR.late_order == 10
    for spec, label in ((FLOOR, "바닥재"), (TILE, "타일"), (PAINT, "도장"), (FILM, "필름")):
        assert spec.label == spec.agent.label == label and spec.agent.name == spec.key
        assert spec.prefill is None and spec.late_order in (None, 10)
        for f in spec.fields:
            for c in f.choices:  # 화면에 보일 말은 쉬운 말 한 줄, 숫자 없이
                assert c.desc and not any(ch.isdigit() for ch in c.label + c.desc)
    # 선택지 값은 계산 엔진의 값 그대로, 같은 순서
    assert FLOOR.field("kind").values == floor.KINDS
    assert TILE.field("parts").values == tile.PARTS and TILE.field("size").values == tile.SIZES
    assert TILE.field("method").values == tile.METHODS
    assert PAINT.field("surfaces").values == paint.SURFACES
    assert PAINT.field("paint").values == paint.PAINTS
    assert PAINT.field("putty").values == paint.PUTTIES
    assert FILM.field("items").values == film.ITEMS and FILM.field("grade").values == film.GRADES
    # 방문 개수는 목공 · 도장 · 필름이 같이 쓰는 칸
    doors = [s.field("doors") for s in (REGISTRY["mokgong"], PAINT, FILM)]
    assert {(f.share, f.unknown, f.min, f.max) for f in doors} == {("doors", 3, 1, 10)}
    text = catalog()
    row = next(ln for ln in text.splitlines() if ln.startswith("- share=doors: "))
    assert "mokgong.doors, paint.doors, film.doors" in row
    assert "- floor.kind | 바닥재 종류 | choice | vinyl_18=장판 · 얇은 것, " in text


def test_unknown_defaults_follow_the_form_draft():
    unknown = {f"{s.key}.{f.key}": f.unknown for s in (FLOOR, TILE, PAINT, FILM) for f in s.fields}
    assert unknown == {
        "floor.kind": "engineered",
        "floor.remove": "yes",
        "tile.parts": None,  # 붙일 곳은 꼭 고른다
        "tile.size": "medium",
        "tile.method": "remove",
        "paint.surfaces": None,
        "paint.paint": "standard",
        "paint.putty": "full",  # 넉넉하게 올퍼티
        "paint.doors": 3,
        "film.items": None,
        "film.grade": "basic",
        "film.doors": 3,
    }


CASES = {
    "floor": (
        ["floor.kind", "floor.remove"],
        [("floor.kind", "decotile"), ("floor.remove", "yes")],
        floor.quote(floor.FloorInput(AREA, "supply", "decotile", False, True), FLOOR_2026H2),
    ),
    "tile": (
        ["tile.parts", "tile.size", "tile.method"],
        [
            ("tile.parts", ["balcony", "kitchen"]),
            ("tile.size", "large"),
            ("tile.method", "overlay"),
        ],
        tile.quote(
            tile.TileInput(AREA, "supply", ("kitchen", "balcony"), "large", "overlay", False),
            TILE_2026H2,
        ),
    ),
    "paint": (
        ["paint.surfaces"],  # 페인트 · 퍼티 · 방문 개수는 칠할 곳을 고른 뒤에 묻는다
        [
            ("paint.surfaces", ["door", "wall", "ceiling"]),
            ("paint.paint", "eco"),
            ("paint.putty", "joint"),
            ("paint.doors", "2"),
        ],
        paint.quote(
            paint.PaintInput(AREA, "supply", ("wall", "ceiling", "door"), False, "eco", "joint", 2),
            PAINT_2026H2,
        ),
    ),
    "film": (
        ["film.items", "film.grade"],
        [
            ("film.items", ["frame", "door", "molding"]),
            ("film.grade", "premium"),
            ("film.doors", "4"),
        ],
        film.quote(
            film.FilmInput(AREA, "supply", ("door", "frame", "molding"), False, "premium", 4),
            FILM_2026H2,
        ),
    ),
}


@pytest.mark.parametrize("trade", list(CASES))
def test_form_answers_reach_the_calc_engine_quote(api, trade):
    first, pairs, want = CASES[trade]
    signup(api)
    out = turn(api, trades=[trade])
    assert fields(out) == ["area", "area_basis", "occupied", *first]

    out = turn(api, out["card"], answers=answers(COMMON_FORM + pairs))
    assert out["questions"] == [] and out["card"]["to_check"] == []
    (res,) = out["results"]
    q = res["quote"]
    assert (res["trade"], res["label"], q["version"]) == (trade, REGISTRY[trade].label, "2026H2")
    assert (q["subtotal"], q["vat"], q["total"]) == (want.subtotal, want.vat, want.total)
    assert [ln["key"] for ln in q["lines"]] == [ln.key for ln in want.lines]
    assert Decimal(q["days"]) == want.days and q["assumptions"] == want.assumptions
    assert [s["key"] for s in out["schedule"]] == [s.key for s in want.steps]
    s = out["summary"]
    assert (s["total"], Decimal(s["days"])) == (want.total, want.days)
    # LLM_LIVE=false: 설명 없이 계산 결과만, 그리고 그 사실을 알린다
    assert res["plan"] is None and res["plan_status"] == "failed" and out["notice"] == PLAN_FAILED


def test_decotile_example_total(api):
    signup(api)
    pairs = COMMON_FORM + [("floor.kind", "decotile"), ("floor.remove", "yes")]
    out = turn(api, trades=["floor"], answers=answers(pairs))
    q = out["results"][0]["quote"]
    assert (q["subtotal"], q["vat"], q["total"], q["days"]) == (2_570_580, 257_058, 2_827_638, "4")
    assert any("데코타일 시공비" in a for a in q["assumptions"])


def test_unknown_answers_use_defaults_and_mark_checks(api):
    signup(api)
    pairs = COMMON_FORM + [
        ("floor.kind", "unknown"),
        ("floor.remove", "unknown"),
        ("tile.parts", ["entrance"]),
        ("tile.size", "unknown"),
        ("tile.method", "unknown"),
        ("paint.surfaces", ["wall", "door"]),
        ("paint.paint", "unknown"),
        ("paint.putty", "unknown"),
        ("paint.doors", "unknown"),
        ("film.items", ["molding"]),
        ("film.grade", "unknown"),
    ]
    out = turn(api, trades=["film", "floor", "paint", "tile"], answers=answers(pairs))
    c = out["card"]
    assert c["trades"] == ["tile", "paint", "film", "floor"]  # 공정 순서대로
    assert c["values"] == {
        "floor": {"kind": "engineered", "remove": "yes"},
        "tile": {"parts": ["entrance"], "size": "medium", "method": "remove"},
        "paint": {"surfaces": ["wall", "door"], "paint": "standard", "putty": "full", "doors": 3},
        "film": {"items": ["molding"], "grade": "basic"},
    }
    assert set(c["to_check"]) == {
        "floor.kind",
        "floor.remove",
        "tile.size",
        "tile.method",
        "paint.paint",
        "paint.putty",
        "paint.doors",
        "film.grade",
    }
    assert out["questions"] == [] and [r["trade"] for r in out["results"]] == c["trades"]
    checked = {(f["trade"], f["label"]) for f in out["facts"] if f["check"]}
    assert ("paint", "칠할 방문 개수") in checked and ("floor", "바닥재 종류") in checked
    # 붙일 곳 · 칠할 곳 · 필름 붙일 곳은 '모르겠어요'가 없다
    for f in ("tile.parts", "paint.surfaces", "film.items"):
        trade = f.split(".")[0]
        body = {"trades": [trade], "answers": answers([(f, "unknown")])}
        assert api.post(URL, json=body).status_code == 422, f
    body = {
        "trades": ["paint"],
        "answers": answers([("paint.surfaces", "door"), ("paint.doors", "11")]),
    }
    assert api.post(URL, json=body).status_code == 422


def test_conditional_fields_follow_the_choices():
    def asked(spec, v):
        return [f.key for f in spec.missing(v)]

    assert asked(PAINT, {}) == ["surfaces"]
    assert asked(PAINT, {"surfaces": ["balcony"]}) == []  # 탄성코트만이면 더 묻지 않는다
    assert asked(PAINT, {"surfaces": ["door"]}) == ["paint", "doors"]
    assert asked(PAINT, {"surfaces": ["ceiling"]}) == ["paint", "putty"]
    assert asked(FILM, {"items": ["molding"]}) == ["grade"]
    assert asked(FILM, {"items": ["frame"]}) == ["grade", "doors"]
    assert asked(FLOOR, {}) == ["kind", "remove"] and asked(TILE, {"parts": ["kitchen"]}) == [
        "size",
        "method",
    ]
    # 조건이 꺼진 칸 값은 지운다
    stale = {"surfaces": ["balcony"], "paint": "eco", "putty": "spot", "doors": 2}
    assert PAINT.relevant(stale) == {"surfaces": ["balcony"]}
    assert FILM.relevant({"items": ["closet"], "grade": "basic", "doors": 2}) == {
        "items": ["closet"],
        "grade": "basic",
    }
    # 묻지 않은 칸은 계산 엔진 기본값으로 계산한다
    want = paint.quote(paint.PaintInput(AREA, "supply", ("balcony",), False), PAINT_2026H2)
    assert PAINT.build(COMMON, {"surfaces": ["balcony"]}) == want
    for spec, v in (
        (FLOOR, {"kind": "vinyl_22", "remove": "no"}),
        (TILE, {"parts": ["entrance"], "size": "small", "method": "remove"}),
        (PAINT, {"surfaces": ["door"], "paint": "standard", "doors": 1}),
        (FILM, {"items": ["kitchen"], "grade": "basic"}),
    ):
        q = QuoteOut.model_validate(spec.build(COMMON, v), from_attributes=True)
        assert q.version == "2026H2" and q.total == q.subtotal + q.vat


def test_door_count_is_asked_once_for_carpentry_paint_and_film(api):
    signup(api)
    pairs = COMMON_FORM + [
        ("mokgong.items", ["door"]),
        ("mokgong.door_frame", "no"),
        ("paint.surfaces", ["door"]),
        ("paint.paint", "standard"),
        ("film.items", ["door", "frame"]),
        ("film.grade", "basic"),
    ]
    out = turn(api, trades=["film", "paint", "mokgong"], answers=answers(pairs))
    assert out["card"]["trades"] == ["mokgong", "paint", "film"]
    (q,) = out["questions"]
    assert q["field"] == "mokgong.doors"
    assert q["text"].endswith("(목공 · 도장 · 필름에 같이 넣어요)")

    out = turn(api, out["card"], answers=answers([("mokgong.doors", "4")]))
    v = out["card"]["values"]
    assert v["mokgong"]["doors"] == v["paint"]["doors"] == v["film"]["doors"] == 4
    assert out["questions"] == []
    got = {r["trade"]: r["quote"]["total"] for r in out["results"]}
    paint_q = paint.quote(paint.PaintInput(AREA, "supply", ("door",), False, doors=4), PAINT_2026H2)
    film_q = film.quote(
        film.FilmInput(AREA, "supply", ("door", "frame"), False, "basic", 4), FILM_2026H2
    )
    assert (got["paint"], got["film"]) == (paint_q.total, film_q.total)
    # 새 방문 · 같은 방문을 두 번 계산했을 수 있다고 알린다 (계산은 그대로)
    assert out["overlaps"] == [ov.NEW_DOOR_FILM, ov.DOOR_TWICE, ov.NEW_DOOR_PAINT]

    # '모르겠어요'면 기본값과 실측 확인 표시를 세 공정에 같이 넣는다
    out = turn(api, trades=["film", "paint", "mokgong"], answers=answers(pairs))
    out = turn(api, out["card"], answers=answers([("mokgong.doors", "unknown")]))
    c = out["card"]
    assert {c["values"][t]["doors"] for t in ("mokgong", "paint", "film")} == {3}
    assert {"mokgong.doors", "paint.doors", "film.doors"} <= set(c["to_check"])


def schedule(out) -> list[tuple[str, str, str]]:
    return [(s["trade"], s["key"], s["phase"]) for s in out["schedule"]]


@pytest.mark.parametrize(
    ("kind", "want"),
    [
        # 장판은 도배가 끝난 뒤에 깐다
        (
            "vinyl_18",
            [
                ("floor", "remove", "remove"),
                ("dobae", "paper", "main"),
                ("floor", "lay", "late"),
                ("floor", "finish", "finish"),
            ],
        ),
        # 마루는 도배 앞 본 작업
        (
            "engineered",
            [
                ("floor", "remove", "remove"),
                ("floor", "lay", "main"),
                ("dobae", "paper", "main"),
                ("dobae", "finish", "finish"),
            ],
        ),
    ],
)
def test_vinyl_goes_after_wallpaper_and_wood_before(api, kind, want):
    signup(api)
    pairs = COMMON_FORM + [
        ("dobae.grade", "basic"),
        ("dobae.include_ceiling", "yes"),
        ("floor.kind", kind),
        ("floor.remove", "yes"),
    ]
    out = turn(api, trades=["dobae", "floor"], answers=answers(pairs))
    assert schedule(out) == want
    assert out["overlaps"] == []


def test_removals_come_first_and_vinyl_last(api):
    signup(api)
    pairs = [("area", "34"), ("area_basis", "supply"), ("occupied", "yes")] + [
        ("dobae.grade", "economy"),
        ("dobae.include_ceiling", "no"),
        ("floor.kind", "vinyl_22"),
        ("floor.remove", "yes"),
        ("tile.parts", ["kitchen"]),
        ("tile.size", "medium"),
        ("tile.method", "remove"),
    ]
    out = turn(api, trades=["dobae", "floor", "tile"], answers=answers(pairs))
    assert schedule(out) == [
        ("tile", "prep", "prep"),  # 짐 정리 · 보양은 한 번
        ("tile", "remove", "remove"),  # 철거는 공정 순서대로 맨 앞에 모은다
        ("floor", "remove", "remove"),
        ("tile", "tile", "main"),
        ("dobae", "paper", "main"),
        ("floor", "lay", "late"),
        ("floor", "finish", "finish"),
    ]
    half = sum(s["half_days"] for s in out["schedule"])
    totals = sum(r["quote"]["total"] for r in out["results"])
    assert Decimal(out["summary"]["days"]) == Decimal(half) / 2
    assert out["summary"]["total"] == totals


def test_overlap_alert_shows_while_the_form_is_still_open(api):
    signup(api)
    out = turn(api, trades=["dobae", "paint"], answers=answers([("paint.surfaces", ["wall"])]))
    assert out["questions"] and out["overlaps"] == [ov.SAME_WALL]


def test_overlap_rules_for_finish_trades():
    o = ov.overlaps
    # 도배는 벽만, 도장은 천장만이면 겹치지 않는다
    walls = {"dobae": {"include_ceiling": "no"}, "paint": {"surfaces": ["ceiling"]}}
    assert o(["dobae", "paint"], walls) == []
    walls["dobae"]["include_ceiling"] = "yes"
    assert o(["dobae", "paint"], walls) == [ov.SAME_WALL]
    assert o(["dobae", "paint"], {"paint": {"surfaces": ["balcony"]}}) == []
    assert o(["paint"], {"paint": {"surfaces": ["wall"]}}) == []  # 두 공정을 다 골라야 한다
    # 목공이 문짝만 바꾸면 필름 문틀은 그대로 필요하다
    frame = {"mokgong": {"items": ["door"], "door_frame": "no"}, "film": {"items": ["frame"]}}
    assert o(["mokgong", "film"], frame) == []
    frame["mokgong"]["door_frame"] = "yes"
    assert o(["mokgong", "film"], frame) == [ov.NEW_DOOR_FILM]
    molding = {"mokgong": {"items": ["molding"]}, "film": {"items": ["molding", "closet"]}}
    assert o(["mokgong", "film"], molding) == [ov.NEW_MOLDING]
    door = {"mokgong": {"items": ["base"]}, "paint": {"surfaces": ["door"]}}
    assert o(["mokgong", "paint"], door) == []
    door["mokgong"]["items"] = ["base", "door"]
    assert o(["mokgong", "paint"], door) == [ov.NEW_DOOR_PAINT]
    twice = {"film": {"items": ["frame"]}, "paint": {"surfaces": ["door", "wall"]}}
    assert o(["film", "paint"], twice) == [ov.DOOR_TWICE]
    # 규칙은 공정 키 이름 순, 말은 '-해요'체 한 문장이고 숫자가 없다
    mine = [r for r in ov.RULES if {r.a, r.b} & {"floor", "tile", "paint", "film"}]
    assert [(r.a, r.b) for r in mine] == sorted((r.a, r.b) for r in mine)
    for r in mine:
        assert r.a < r.b and {r.a, r.b} <= REGISTRY.keys()
        assert r.text.endswith("요.") and r.text.count(".") == 1
        assert not any(ch.isdigit() for ch in r.text)


def test_card_lines_describe_only_the_trade_fields():
    assert FLOOR.card_lines(COMMON, {"kind": "vinyl_18", "remove": "no"}) == [
        "바닥재: 장판 · 얇은 것",
        "지금 바닥: 그 위에 깔아요",
    ]
    assert TILE.card_lines(
        COMMON, {"parts": ["kitchen", "balcony"], "size": "large", "method": "overlay"}
    ) == [
        "타일 붙일 곳: 주방 벽, 베란다 바닥",
        "타일 크기: 큰 타일",
        "지금 타일: 위에 덧붙여요 (덧방)",
    ]
    v = {"surfaces": ["wall", "door"], "paint": "eco", "putty": "full", "doors": 2}
    assert PAINT.card_lines(COMMON, v) == [
        "칠할 곳: 벽, 방문 · 문틀",
        "페인트: 친환경 수성",
        "퍼티 범위: 벽 전체 (올퍼티)",
        "칠할 방문: 2개",
    ]
    assert PAINT.card_lines(COMMON, {"surfaces": ["balcony"]}) == ["칠할 곳: 베란다 (탄성코트)"]
    assert FILM.card_lines(COMMON, {"items": ["molding"], "grade": "basic"}) == [
        "필름 붙일 곳: 천장 몰딩",
        "필름 등급: 일반 필름",
    ]

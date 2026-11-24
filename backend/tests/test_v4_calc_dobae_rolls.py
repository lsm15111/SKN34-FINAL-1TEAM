"""갈래 P2 도배 자재 준비(calc.dobae_rolls, DB 없음): 도배 면적 + 벽지 종류 → 롤 수(면적만 · 자투리 포함) · 여분 ·
부자재(풀 · 초배지 · 부직포) 양과 표준견적서 포함 상태. 기대값은 손으로 검산했어요."""

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app.calc import dobae, dobae_rolls, rolls
from app.calc.common import Line
from app.quote.service import standard_v3
from app.refprice.book import DOBAE_PROFILES, DOBAE_V3_2026_11
from app.refprice.wallpaper_market import paper_market

D = Decimal
BACKEND = Path(__file__).resolve().parents[1]


def _mat(r: dobae_rolls.DobaeRolls, key: str) -> dobae_rolls.Material:
    (m,) = [x for x in r.materials if x.key == key]
    return m


def _line(key: str, name: str, state: str) -> Line:
    return Line(key, name, None, "식", None, None, state, "시험")  # type: ignore[arg-type]


# ---- 상수 · 출처 ----


def test_constants_keep_public_sources_and_unknowns_stay_vendor_check():
    assert dobae_rolls.PAPER_RATIO == D("1.2")  # 표준품셈 정배지 1.2㎡/㎡(할증 포함)
    assert "표준품셈" in dobae_rolls.PAPER_RATIO_SOURCE and "할증" in dobae_rolls.PAPER_RATIO_SOURCE
    assert [(m.key, m.name) for m in dobae_rolls.MATERIALS] == [
        ("paste", "풀"),
        ("primer", "초배지"),
        ("nonwoven", "부직포"),
    ]
    paste, primer, nonwoven = dobae_rolls.MATERIALS
    assert (paste.wall, paste.ceiling, paste.unit) == (D("0.3"), D("0.3"), "㎏")
    assert (primer.wall, primer.ceiling, primer.unit) == (D("1.2"), D("0.8"), "㎡")
    assert "표준품셈" in paste.source and "표준품셈" in primer.source
    # 부직포는 공공 · 업계 양 기준을 찾지 못했어요: 양을 세지 않고 업체 확인
    assert (nonwoven.wall, nonwoven.ceiling, nonwoven.unit) == (None, None, None)
    assert nonwoven.source == dobae_rolls.CHECK == "업체 확인"
    assert dobae_rolls.SPARE == rolls.SPARE == (1, 2)  # 여분은 calc.rolls와 같은 값(셈 밖)


def test_module_is_pure():
    """계산 엔진은 DB · HTTP · 시계를 모른다(AGENTS.md 2장)."""
    tree = ast.parse((BACKEND / "app/calc/dobae_rolls.py").read_text(encoding="utf-8"))
    names = {
        a.name if isinstance(n, ast.Import) else (n.module or "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not {x for x in names if x.split(".")[0] in {"sqlalchemy", "httpx", "datetime", "time"}}
    assert all(not x.startswith("app.") or x.startswith("app.calc") for x in names)


# ---- 롤 수 · 올림 ----


def test_silk_rolls_area_loss_and_spare():
    r = dobae_rolls.need(D("153.0"), D("82.4"), "basic")
    assert (r.key, r.name, r.size, r.roll_m2) == ("silk", "실크", "106cm × 15.6m", D("16.536"))
    assert (r.area_m2, r.ratio) == (D("235.4"), D("1.2"))
    # 벽지 양: 235.4 × 1.2 = 282.48 → 282.5㎡ → 282.5 ÷ 3.3058 = 85.46 → 85.5 벽지 평
    assert (r.paper_m2, r.paper_py) == (D("282.5"), D("85.5"))
    # 면적만: 235.4 ÷ 16.536 = 14.24 → 15롤, 자투리 포함: 85.5 × 3.3058 ÷ 16.536 = 17.09 → 18롤
    assert (r.base, r.count, r.loss) == (15, 18, 3)
    assert (r.spare_min, r.spare_max) == (1, 2)
    assert r.loss_rate == D("0.2")
    assert r.version == dobae_rolls.VERSION


@pytest.mark.parametrize(
    ("grade", "hapji", "key", "base", "count"),
    [
        ("economy", "wide", "hapji_wide", 15, 18),  # 16.5075㎡: 14.26 → 15 · 17.12 → 18
        ("economy", "narrow", "hapji_narrow", 36, 43),  # 6.625㎡: 35.53 → 36 · 42.66 → 43
    ],
)
def test_hapji_rolls_wide_by_default_narrow_when_picked(grade, hapji, key, base, count):
    r = dobae_rolls.need(D("153.0"), D("82.4"), grade, hapji=hapji)
    assert (r.key, r.base, r.count, r.loss) == (key, base, count, count - base)
    assert r.name == rolls.ROLLS[key].name


@pytest.mark.parametrize(
    ("wall", "base"),
    [
        (D("33.0"), 2),  # 33.0 ÷ 16.536 = 1.996 → 2
        (D("33.1"), 3),  # 2.002 → 3(조금이라도 넘으면 올림)
        (D("16.5"), 1),
    ],
)
def test_base_rolls_round_up(wall, base):
    assert dobae_rolls.need(wall, D(0), "basic").base == base


def test_ratio_one_has_no_loss_and_count_never_below_base():
    r = dobae_rolls.need(D("33.0"), D(0), "basic", ratio=D(1))
    # 33.0㎡ → 10.0 벽지 평 → 33.058㎡ ÷ 16.536 = 1.9992 → 2(면적만과 같아요)
    assert (r.paper_py, r.base, r.count, r.loss, r.loss_rate) == (D("10.0"), 2, 2, 0, D(0))


def test_count_is_never_below_area_rolls():
    # 16.54㎡ → 벽지 16.5㎡ → 5.0 벽지 평(16.529㎡)이라 그대로 세면 1롤이지만, 면적만 덮어도 2롤이에요
    r = dobae_rolls.need(D("16.54"), D(0), "basic", ratio=D(1))
    assert (r.base, r.count, r.loss) == (2, 2, 0)


def test_bad_inputs():
    with pytest.raises(ValueError):
        dobae_rolls.need(D(0), D(0), "basic")  # 도배 면적이 없어요
    with pytest.raises(ValueError):
        dobae_rolls.need(D("-1"), D("10"), "basic")
    with pytest.raises(ValueError):
        dobae_rolls.need(D("10"), D("10"), "basic", ratio=D("0.9"))  # 소요량은 1 이상
    with pytest.raises(ValueError):
        dobae_rolls.need(D("10"), D("10"), "premium")


# ---- 표준견적서와 같은 롤 수(같은 소요량을 넣으면) ----


@pytest.mark.parametrize("profile", ["paper_only", "remodel"])
@pytest.mark.parametrize("grade", ["basic", "economy"])
@pytest.mark.parametrize("area", [D("79.3"), D("112.4"), D("145.5")])
def test_count_matches_the_standard_quote_rolls(profile, grade, area):
    p = DOBAE_PROFILES[profile]
    why = (dobae.FULL_DEMOLITION,) if profile == "remodel" else ()
    v = standard_v3(
        dobae.HomeV3(area, "supply", grade, False), None, dobae.ProfilePick(profile, why)
    )
    lines = {ln.key: ln for ln in v.quote.lines}
    paper = lines["paper"]
    want = rolls.need(rolls.roll_key(grade), paper_py=paper.qty)
    r = dobae_rolls.need(
        lines["wall"].qty, lines["ceiling"].qty, grade, ratio=p.profile.paper_ratio[grade]
    )
    assert (r.paper_py, r.count) == (paper.qty, want.count)
    assert r.base <= r.count and r.loss == r.count - r.base


# ---- 부자재: 양(표준품셈) · 표준견적서 포함 상태 ----


def test_material_amounts_round_up():
    r = dobae_rolls.need(D("153.0"), D("82.4"), "basic")
    paste, primer, nonwoven = (_mat(r, k) for k in ("paste", "primer", "nonwoven"))
    assert (paste.qty, paste.unit) == (D("70.7"), "㎏")  # 235.4 × 0.3 = 70.62 → 70.7
    # 벽 153.0 × 1.2 + 천장 82.4 × 0.8 = 249.52 → 249.6
    assert (primer.qty, primer.unit) == (D("249.6"), "㎡")
    assert (nonwoven.qty, nonwoven.unit, nonwoven.source) == (None, None, dobae_rolls.CHECK)


def test_states_follow_the_profile_standard_lines():
    v = standard_v3(
        dobae.HomeV3(D("112.4"), "supply", "basic", False),
        None,
        dobae.ProfilePick("paper_only", ()),
    )
    lines = {ln.key: ln for ln in v.quote.lines}
    r = dobae_rolls.need(lines["wall"].qty, lines["ceiling"].qty, "basic", lines=v.quote.lines)
    material = lines["material"].name  # 부자재 (풀 · 부직포 · 네바리 · 실리콘 등)
    assert (_mat(r, "paste").state, _mat(r, "paste").line) == ("included", material)
    assert (_mat(r, "nonwoven").state, _mat(r, "nonwoven").line) == ("included", material)
    # 두 기준 판은 초배지 줄이 없어요(부자재 줄 이름에도 없음): 업체 확인
    assert (_mat(r, "primer").state, _mat(r, "primer").line) == (None, None)


def test_states_follow_the_old_v3_lines_and_skip_left_out_faces():
    h = dobae.DobaeV3Input(D("112.4"), "supply", "basic", False, faces=("ceiling",), rooms=3)
    q = dobae.quote_v3(h, DOBAE_V3_2026_11, paper_market("basic"))
    lines = {ln.key: ln for ln in q.lines}
    assert lines["wall"].state == "excluded" and "(풀 포함)" in lines["wall"].name
    r = dobae_rolls.need(D(0), lines["ceiling"].qty, "basic", lines=q.lines)
    # 풀은 고른 면(천장) 시공 줄에 들어 있어요(뺀 벽 줄을 보지 않아요)
    assert (_mat(r, "paste").state, _mat(r, "paste").line) == ("included", lines["ceiling"].name)
    assert (_mat(r, "primer").state, _mat(r, "primer").line) == ("included", "초배지")
    assert _mat(r, "nonwoven").state is None  # 옛 판에는 부직포를 단 줄이 없어요


@pytest.mark.parametrize("state", ["separate", "excluded", "optional", "bundled"])
def test_state_is_the_line_state_as_is(state):
    lines = [_line("material", "부자재 (풀 · 부직포)", state)]
    r = dobae_rolls.need(D("10.0"), D(0), "basic", lines=lines)
    assert _mat(r, "paste").state == _mat(r, "nonwoven").state == state
    assert _mat(r, "primer").state is None


def test_left_out_line_is_used_only_when_nothing_else_names_it():
    lines = [
        _line("wall", "벽 도배 시공 (풀 포함)", "excluded"),
        _line("ceiling", "천장 도배 시공 (풀 포함)", "excluded"),
    ]
    r = dobae_rolls.need(D("10.0"), D(0), "basic", lines=lines)
    assert (_mat(r, "paste").state, _mat(r, "paste").line) == ("excluded", "벽 도배 시공 (풀 포함)")

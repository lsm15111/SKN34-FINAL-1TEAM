"""고침 3차 K 2 · 3 · 5 · 7번: 벽지 견주기의 벽지 직접 구매 · 돈 기준 꼬리표 · 롤 수 · 자정 표기. 유료 호출 0회.

- 2(v1 H1 · s5): 벽지 직접 구매를 켜면 견주기 카드 합계도 벽지 값을 뺀 값이에요(카드 · 표준견적서 · 보드가 같은 합계).
- 3(리드 결정 2, s5 10 · 13번 · v1 M4): 도구 결과의 돈은 부가세 포함이 기본이고, 공급가는 칸 이름에 '공급가'를 붙여요.
  QA에서 모델이 공급가 줄(913,665원)을 부가세 포함 합계에 더하고 빼 2,861,125원 · 2,038,826원 같은 틀린 값을 냈어요.
  벽지 값은 부가세 포함 몫(1,005,031원)과 벽지를 넣은 · 뺀 합계를 계산 엔진이 같이 줘요.
- 5(s5 3 · 6 · 12번): 표준견적서 · 견주기 결과에 롤 수(계산 엔진)를 늘 넣어요(합지는 광폭 롤).
- 7(c3 10번): 자정 0시는 전날 '밤 12시'로 써요('12월 7일(월) 오전 12시'가 낮 12시로 읽힘).
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.assistant import policy
from app.assistant.tools import cards as card_tools
from app.calc import dobae, rolls
from app.calc.common import COUNTED, Money
from app.quote.service import OWN_PAPER_NOTE, standard_v3
from app.shared.clock import SEOUL
from tests.helpers import signup
from tests.test_project import body as project_body
from tests.test_v3_project_home import HOME, create
from tests.test_v4_assistant_diy import as_owner, chips

D = Decimal
AREA = D("69.4")  # HOME 공급 69.4㎡ · 빈 집 · 실크


def _std(api, pid: str) -> dict:
    return as_owner(api, pid, lambda s, u: card_tools.standard(s, u, uuid.UUID(pid)))


def _grades(api, pid: str) -> tuple[dict, dict]:
    card, model = as_owner(api, pid, lambda s, u: card_tools.grade_compare(s, u, uuid.UUID(pid)))
    return card.data, model


def _quote(grade: str, own: bool):
    return standard_v3(dobae.HomeV3(AREA, "supply", grade, False), own_paper=own).quote


def _keys(value) -> set[str]:
    """dict · list 안의 모든 칸 이름."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.fixture
def project(api) -> str:
    signup(api)
    r = create(api, HOME)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- 2 · 견주기가 벽지 직접 구매를 뺀다 ----


def test_grade_compare_takes_the_paper_out_when_the_customer_buys_it(api, project):
    pid = project
    before, _ = _grades(api, pid)
    assert (before["basic_won"], before["economy_won"]) == (
        _quote("basic", False).total,
        _quote("economy", False).total,
    )
    assert chips(api, pid, ["paper_buy"]) == ["paper_buy"]
    data, model = _grades(api, pid)
    silk, hapji = _quote("basic", True), _quote("economy", True)
    # 카드 합계 = 계산 엔진(벽지 고객 구매) = 표준견적서 카드 · 화면 합계(QA v1 H1: 카드 295만 vs 보드 194만)
    assert (data["basic_won"], data["economy_won"]) == (silk.total, hapji.total)
    assert data["diff_won"] == silk.total - hapji.total
    std_card, std_model = _std(api, pid)
    assert std_card.data["total_won"] == std_model["total"] == data["basic_won"]
    rest = next(t for t in api.get(f"/projects/{pid}/standard").json()["trades"])
    assert rest["total"] == data["basic_won"]
    assert data["label"].endswith("벽지 고객 구매")
    # 벽지 줄은 '고객 구매 · 합계 밖' 이름으로 값(공급가)만 보여요
    paper = next(r for r in data["rows"] if r["name"].startswith("벽지 값"))
    assert paper["name"] == card_tools.PAPER_OWN_ROW
    lines = {
        g: next(ln for ln in q.lines if ln.key == "paper")
        for g, q in (("basic", silk), ("economy", hapji))
    }
    assert (paper["basic_won"], paper["economy_won"]) == (
        lines["basic"].amount,
        lines["economy"].amount,
    )
    # 업체에 벽지까지 맡길 때의 두 합계 · 차액(계산 엔진)도 모델 값에
    full = model["paper"]
    assert [x["total"] for x in full["items"]] == [
        _quote("economy", False).total,
        _quote("basic", False).total,
    ]
    assert full["diff_won"] == _quote("basic", False).total - _quote("economy", False).total
    assert full["state"] == "고객 구매(합계 밖)" and "벽지 값을 뺀" in full["note"]
    # 끄면 다시 벽지 포함
    chips(api, pid, [])
    again, model = _grades(api, pid)
    assert again["basic_won"] == _quote("basic", False).total and "paper" not in model
    assert next(r for r in again["rows"] if r["name"].startswith("벽지 값"))["name"] == "벽지 값"


# ---- 3 · 돈 기준 꼬리표 ----


def test_standard_money_is_vat_included_and_supply_fields_say_so(api, project):
    pid = project
    _, model = _std(api, pid)
    q = _quote("basic", False)
    assert (model["total"], model["공급가"], model["vat"]) == (q.total, q.subtotal, q.vat)
    assert {"supply", "amount"}.isdisjoint(_keys(model))  # 꼬리표 없는 공급가 칸이 없어요
    assert all(set(ln) == {"name", "공급가", "state", "trade"} for ln in model["lines"])
    assert sum(ln["공급가"] for ln in model["lines"]) == model["공급가"]  # 줄은 공급가끼리 더해요
    # 벽지 칸: 부가세 포함 몫 · 벽지를 직접 사면 바뀔 합계(계산 엔진). 공급가 줄을 합계에서 빼지 않아도 돼요
    paper_line = next(ln for ln in q.lines if ln.key == "paper")
    without = _quote("basic", True).total
    box = model["paper"]
    assert box["공급가"] == paper_line.amount and box["line"] == paper_line.name
    assert [r["won"] for r in box["rows"]] == [q.total - without, without]
    assert box["rows"][0]["won"] != paper_line.amount  # 부가세 포함 몫(공급가와 달라요)
    # 모델에 가는 값(허용 칸만)에도 꼬리표가 남아요
    sent = policy.to_model(model)
    assert sent["공급가"] == q.subtotal and sent["vat"] == q.vat
    assert all("공급가" in ln and "amount" not in ln for ln in sent["lines"])
    assert sent["paper"]["rows"][1]["label"] == card_tools.PAPER_ROWS[1]


def test_own_paper_box_gives_the_vat_included_share_and_the_full_total(api, project):
    """QA r3 s5 10번 '표준견적서에 벽지 값 913,665원을 더해 보세요'(공급가) → 2,861,125원(틀림). 이제 벽지까지 넣은
    합계(업체 가견적과 견줄 값)와 빠진 몫(부가세 포함)을 계산 엔진이 줘요."""
    pid = project
    chips(api, pid, ["paper_buy"])
    _, model = _std(api, pid)
    own, full = _quote("basic", True), _quote("basic", False)
    paper_line = next(ln for ln in full.lines if ln.key == "paper")
    box = policy.to_model(model)["paper"]
    need = rolls.need("silk", paper_py=paper_line.qty)
    assert box == {
        "count": need.count,
        "text": need.text,
        "line": paper_line.name,
        "공급가": paper_line.amount,
        "state": "고객 구매(합계 밖)",
        "rows": [
            {"label": card_tools.PAPER_OWN_ROWS[0], "won": full.total - own.total},
            {"label": card_tools.PAPER_OWN_ROWS[1], "won": full.total},
        ],
        "note": OWN_PAPER_NOTE,
    }
    assert model["total"] == own.total
    # 계산 엔진 한 곳: 넣은 합계 · 뺀 합계 · 몫
    split = dobae.paper_split(full.lines, D("0.1"))
    assert (split.with_paper.total, split.without_paper.total) == (full.total, own.total)
    assert split.share == full.total - own.total
    assert dobae.paper_split(own.lines, D("0.1")) == split  # 벽지 직접 구매 줄에서 세도 같아요


def test_grade_compare_lines_are_tagged_supply(api, project):
    _, model = _grades(api, project)
    assert {"supply", "vat", "amount"}.isdisjoint(_keys(model))
    for ln in policy.to_model(model)["lines"]:
        assert all(set(x) == {"grade", "공급가"} for x in ln["items"]), ln


def test_vendor_quote_split_fields_are_tagged_too():
    """견적서 비교(compare)의 합계 칸 나눔도 '공급가' · vat(부가세 몫)예요(코드로 확인: 꼬리표 없는 supply 칸이 없음)."""
    import inspect

    src = inspect.getsource(card_tools.compare)
    assert '"supply":' not in src and '"amount":' not in src
    assert '"공급가": q.supply' in src and '"vat": q.vat' in src


def test_paper_rows_follow_the_total_scope_when_the_project_has_more_trades(api):
    """total이 여러 공정 합계(도배 + 목공)면 바뀔 합계도 전체 범위예요. 도배만 물으면 도배 범위."""
    signup(api)
    r = api.post("/projects", json=project_body())  # 도배 + 목공
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    trades = {t["trade"]: t for t in api.get(f"/projects/{pid}/standard").json()["trades"]}
    assert set(trades) == {"dobae", "mokgong"}
    _, model = _std(api, pid)
    assert model["total"] == trades["dobae"]["total"] + trades["mokgong"]["total"]
    share, after = model["paper"]["rows"]
    assert after == {"label": card_tools.PAPER_ALL_ROW[False], "won": model["total"] - share["won"]}
    _, only = as_owner(api, pid, lambda s, u: card_tools.standard(s, u, uuid.UUID(pid), "dobae"))
    share2, after2 = only["paper"]["rows"]
    assert share2 == share
    assert after2 == {
        "label": card_tools.PAPER_ROWS[1],
        "won": trades["dobae"]["total"] - share["won"],
    }


def test_paper_rows_keep_the_dobae_total_for_vendor_estimates_when_more_trades():
    split = dobae.PaperSplit(
        Money(2_684_083, 268_408, 2_952_491), Money(1_770_418, 177_042, 1_947_460), 1_005_031
    )
    own, rest = card_tools.PAPER_OWN_ROWS, card_tools.PAPER_ROWS
    assert card_tools.paper_rows(split, True, []) == [
        {"label": own[0], "won": 1_005_031},
        {"label": own[1], "won": 2_952_491},
    ]
    assert card_tools.paper_rows(split, True, [500_000]) == [
        {"label": own[0], "won": 1_005_031},
        {"label": card_tools.PAPER_ALL_ROW[True], "won": 3_452_491},
        {"label": card_tools.PAPER_DOBAE_ROW, "won": 2_952_491},
    ]
    assert card_tools.paper_rows(split, False, [500_000]) == [
        {"label": rest[0], "won": 1_005_031},
        {"label": card_tools.PAPER_ALL_ROW[False], "won": 2_447_460},
    ]


# ---- 5 · 롤 수 ----


def test_grade_compare_gives_rolls_for_both_papers(api, project):
    """합지 롤 수도 계산 엔진 값(광폭 93cm × 17.75m)이에요(QA r3 s5 6번 '합지 롤 수는 자료에 없어요')."""
    _, model = _grades(api, project)
    by = {x["grade"]: x for x in model["items"]}
    for grade, key, name in (("economy", "hapji_wide", "합지"), ("basic", "silk", "실크")):
        paper = next(ln for ln in _quote(grade, False).lines if ln.key == "paper")
        need = rolls.need(key, paper_py=paper.qty)
        assert by[name]["paper"] == {"count": need.count, "text": need.text}
    assert "광폭 합지(93cm × 17.75m)" in by["합지"]["paper"]["text"]
    sent = policy.to_model(model)
    assert all(x["paper"]["count"] > 0 for x in sent["items"])


def test_standard_always_has_rolls(api, project):
    _, model = _std(api, project)
    assert model["paper"]["count"] > 0 and "롤" in model["paper"]["text"]


# ---- 7 · 자정 ----


@pytest.mark.parametrize(
    ("at", "said"),
    [
        (datetime(2026, 12, 7, 0, 0, tzinfo=SEOUL), "12월 6일(일) 밤 12시"),
        (datetime(2026, 12, 7, 0, 30, tzinfo=SEOUL), "12월 6일(일) 밤 12시 30분"),
        (datetime(2026, 12, 1, 0, 0, tzinfo=SEOUL), "11월 30일(월) 밤 12시"),
        (datetime(2026, 12, 7, 12, 0, tzinfo=SEOUL), "12월 7일(월) 오후 12시"),
        (datetime(2026, 12, 7, 9, 5, tzinfo=SEOUL), "12월 7일(월) 오전 9시 5분"),
        (datetime(2026, 12, 7, 23, 0, tzinfo=SEOUL), "12월 7일(월) 오후 11시"),
    ],
)
def test_seoul_text_says_midnight_as_the_night_before(at, said):
    assert card_tools.seoul_text(at) == said


def test_counted_paper_is_supply_and_split_matches_counted_sum():
    """계산 엔진 확인: 표준견적서 합계 = 포함 줄(공급가) 합 + 부가세, 벽지 뺀 합계도 같은 반올림."""
    q = _quote("economy", False)
    supply = sum(ln.amount for ln in q.lines if ln.state in COUNTED and ln.amount is not None)
    assert supply == q.subtotal
    split = dobae.paper_split(q.lines, D("0.1"))
    assert (
        split.with_paper.total == q.total
        and split.without_paper.total == _quote("economy", True).total
    )

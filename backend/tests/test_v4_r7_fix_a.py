"""QA r7 고침 A(고객 비서). 유료 호출 0회(Claude 대본 · 계산 엔진).

- 1. 집 정보 승인 카드 차액의 까닭(c2 T9~T11): 계산 엔진 줄로 바뀌는 줄 · 기준을 모델 값 change와 다음 턴 사실에
  넘겨요. 화면 카드 글은 그대로예요.
"""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import propose
from app.calc import dobae
from app.calc.common import Line
from app.calc.quote_diff import line_changes
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.refprice.book import DOBAE_PROFILES
from app.refprice.house import HOUSE_DEFAULT
from app.refprice.wallpaper_market import paper_market
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_r6_a1_lead import facts_of


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def tool_result(log, call: int, block: int = 0) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][block]["content"])


# ---- 1. 집 정보 승인 카드 차액의 까닭 ----


def _ln(key: str, amount: int | None, state: str = "included") -> Line:
    return Line(key, f"{key} 줄 (뜻)", None, "식", None, amount, state, "출처")  # type: ignore[arg-type]


def test_line_changes_rank_by_the_counted_gap():
    """합계에 드는 몫(포함 · 따로 계산 줄의 공급가) 차가 큰 순, 같으면 상태가 바뀐 줄 먼저. 그대로인 줄은 빼요."""
    before = {
        "d:wall": _ln("wall", 100),
        "d:putty": _ln("putty", 50, "optional"),
        "d:removal": _ln("removal", 30, "after_visit"),
        "d:same": _ln("same", 10),
    }
    after = {
        "d:wall": _ln("wall", 130),
        "d:putty": _ln("putty", 70),
        "d:removal": _ln("removal", 30, "excluded"),
        "d:same": _ln("same", 10),
        "d:meal": _ln("meal", 20),
    }
    got = line_changes(before, after)
    assert [(c.key, c.gap) for c in got] == [
        ("d:putty", 70),  # 선택 → 포함: 합계 몫 0 → 70
        ("d:wall", 30),
        ("d:meal", 20),  # 새 줄
        ("d:removal", 0),  # 합계 밖끼리: 상태만 바뀜
    ]
    assert got[0].state_moved and not got[1].state_moved and got[2].before is None
    assert line_changes(before, after, top=2) == got[:2]
    with pytest.raises(ValueError):
        line_changes(before, after, top=0)


def test_full_demolition_gaps_add_up_to_the_engine_difference():
    """도배만 → 리모델링(전체 철거): 바뀌는 줄의 합계 몫 차를 모두 더하면 계산 엔진 공급가 차와 같아요(새로 세지 않음)."""
    h = dobae.HomeV3(Decimal("105.8"), "supply", "basic", False)

    def std(profile: str, why=()) -> dobae.StandardV3:
        return dobae.standard_v3(
            h,
            DOBAE_PROFILES[profile],
            paper_market("basic"),
            SPACE_SHARE_ROOMS_2026_11,
            HOUSE_DEFAULT,
            why,
        )

    a, b = std("paper_only"), std("remodel", (dobae.FULL_DEMOLITION,))
    got = line_changes(
        {ln.key: ln for ln in a.quote.lines}, {ln.key: ln for ln in b.quote.lines}, top=99
    )
    assert sum(c.gap for c in got) == b.quote.subtotal - a.quote.subtotal > 0
    removal = next(c for c in got if c.key == "removal")  # 원래도 합계 밖: 상태만 바뀌어요
    assert (removal.gap, removal.before.state, removal.after.state) == (  # type: ignore[union-attr]
        0,
        "after_visit",
        "excluded",
    )


def test_home_card_gives_the_reason_now_and_in_the_next_turn(api, script):
    """전체 철거 카드: 모델 값 change에 기준 · 바뀌는 줄(줄마다 지금 · 승인 뒤 상태 · 공급가), 카드 요약 칸은 그대로.
    다음 턴 사실의 '승인 기다리는 카드'에 바꾸는 칸 · 카드 차액 · 계산 엔진 미리 보기가 붙어요(c2 T10 · T11)."""
    _, pid = home(api)
    call = {"id": "p", "name": "propose_home_info", "input": {"fields": {"demolition": "full"}}}
    log = script([{"tool_calls": [call]}, {"text": "카드를 확인해 주세요."}])
    ev = ok(ask(api, pid, "철거 범위는 전체 철거로 해 주세요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    d = a["summary"]["diff"]
    assert d["diff_won"] > 0
    assert [r["label"] for r in a["summary"]["rows"]] == [
        "철거 범위"
    ]  # 화면 카드 글은 늘리지 않아요
    change = tool_result(log, 1)["change"]
    assert change["basis"] == "도배만 하는 공사 기준 → 리모델링 기준(근거: 전체 철거)"
    assert 1 <= len(change["lines"]) <= 5 and propose.CHANGE_NOTE == change["note"]
    for line in change["lines"]:
        assert [x["label"] for x in line["items"]] == ["지금", "승인 뒤"]
        assert "(" not in line["name"]  # 줄 이름 앞부분만
        assert all(isinstance(x.get("공급가", 0), int) for x in line["items"])
    moved = [ln for ln in change["lines"] if ln["items"][0]["state"] != ln["items"][1]["state"]]
    assert moved  # 선택 → 포함 같은 포함 상태가 바뀐 줄이 있어요

    log = script([{"text": "리모델링 기준이라 늘어요."}])
    ok(ask(api, pid, "왜 그렇게 늘어요?"))
    facts = facts_of(log)
    head = f"승인 기다리는 카드: 집 정보 저장(철거 범위 전체 철거 · 누르면 표준견적서 {d['from_won']:,}원 → {d['to_won']:,}원"
    assert head in facts
    assert "계산 엔진 미리 보기: 도배만 하는 공사 기준 → 리모델링 기준(근거: 전체 철거)" in facts
    assert "크게 바뀌는 줄 " in facts and " → 포함]" in facts


def test_reason_words_and_cards_without_a_difference():
    """턴 사실 까닭 글: 기준 · 크게 바뀌는 줄(상태가 바뀐 줄은 [지금 → 승인 뒤]). 금액이 그대로인 카드(차액 칸 없음)는
    괄호 글이 없어요."""
    before = {"d:putty": _ln("putty", 50, "optional"), "d:wall": _ln("wall", 100)}
    after = {"d:putty": _ln("putty", 70), "d:wall": _ln("wall", 130)}
    ch = propose.StandardChange(
        1_000_000,
        1_100_000,
        ("도배만 하는 공사 기준", "리모델링 기준"),
        (dobae.FULL_DEMOLITION,),
        line_changes(before, after),
    )
    assert propose.change_said(ch) == (
        "도배만 하는 공사 기준 → 리모델링 기준(근거: 전체 철거), 크게 바뀌는 줄 putty 줄[선택 → 포함] · wall 줄"
    )
    assert propose.basis_said(replace(ch, basis=("리모델링 기준", "리모델링 기준"))) is None
    a = SimpleNamespace(kind="home_info", summary={"title": "집 정보 저장", "rows": []}, payload={})
    assert asyncio.run(propose.open_home_fact(None, SimpleNamespace(home=object()), a)) is None

"""QA r7 고침 A(고객 비서). 유료 호출 0회(Claude 대본 · 계산 엔진).

- 1. 집 정보 승인 카드 차액의 까닭(c2 T9~T11): 계산 엔진 줄로 바뀌는 줄 · 기준을 모델 값 change와 다음 턴 사실에
  넘겨요. 화면 카드 글은 그대로예요.
- 2. 값이 섞인 견주기(c2 L27) · v3 빈 답(c2 L21)은 공정 전문가로. 기본 경로(period=v3,price=v3,*=expert+v3)는 그대로예요.
"""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import answer, propose
from app.calc import dobae
from app.calc.common import Line
from app.calc.quote_diff import line_changes
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.config import settings
from app.refprice.book import DOBAE_PROFILES
from app.refprice.house import HOUSE_DEFAULT
from app.refprice.wallpaper_market import paper_market
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_experts import TRADE_ROUTE, _gate, _out, repo_search  # noqa: F401
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


# ---- 2. 값이 섞인 견주기 · 빈 답은 공정 전문가로 ----

COMPARE_Q = (
    "문틀은 제가 페인트 칠하려는데, 필름 붙이는 거나 아예 문틀 교체하는 거랑 비교하면 어때요? "
    "오래가는 거랑 비용 차이가 궁금해요."
)


def test_compare_words_and_money_first():
    """견주기 · 장단 말이 있으면 돈 · 기간 낱말이 있어도 이 공사 금액 길이 먼저가 아니에요(기본 경로는 그대로)."""
    assert answer.engine_for("price", TRADE_ROUTE) == "v3"  # 기본 경로 그대로
    for q in (
        COMPARE_Q,
        "실크랑 합지 중에 뭐가 더 나아요? 가격은요?",
        "페인트 아니면 필름, 어느 게 오래가요?",
    ):
        assert answer.kind_of("price", q) == "general" and not answer.money_first(q), q
    for q in (
        "도배 비용 얼마예요?",
        "도배 며칠 걸려요?",
        "초배는 꼭 해야 해요? 빼면 얼마나 아껴요?",
    ):
        assert answer.kind_of("price", q) == "price" and answer.money_first(q), q


@pytest.mark.usefixtures("repo_search")
@pytest.mark.parametrize("kind", ["general", "price"])
def test_compare_with_money_goes_to_the_expert(api, script, monkeypatch, kind):
    """'문틀 페인트 · 필름 · 교체 비교 + 비용'(QA r7 c2 L27): 모델이 price로 불러도 전문가 길(LLM 3번)이고, 값은 이
    공사 계산 값으로만 말하라는 note가 붙어요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    expert = _out(("문틀 상태가 좋으면 칠하기로 충분하고, 습한 곳은 필름이 들뜨기 쉬워요.", ["G"]))
    call = {"id": "q", "name": "answer_question", "input": {"question": COMPARE_Q, "kind": kind}}
    log = script([{"tool_calls": [call]}, {"json": expert}, {"text": "확인했어요."}])
    ok(ask(api, pid, COMPARE_Q))
    body = json.loads(log[-1]["messages"][-1]["content"][0]["content"])
    assert len(log) == 3 and body["route"] == "expert"
    assert answer.MONEY_NOTE in body["note"]


@pytest.mark.usefixtures("repo_search")
def test_empty_v3_answer_goes_on_to_the_expert(api, script, monkeypatch):
    """v3가 범위 밖 · 되묻기가 아닌데 빈 답이면 전문가로 이어요(QA r7 c2 L21). 범위 밖 답은 그대로, 전부 v3 경로면
    물러서지 않아요."""
    from app.assistant.tools import ToolOut

    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    route = {"v": "answer"}

    async def empty(_tc, _q):
        return ToolOut(data={"route": route["v"], "sources": [], "found": False}), False

    monkeypatch.setattr(answer, "_v3_answer", empty)
    q = "초배는 꼭 해야 해요? 빼면 얼마나 아껴요?"
    expert = _out(("실크는 초배로 바탕을 골라야 이음매가 덜 보여요.", ["G"]))
    for kind in ("price", "general"):
        call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": kind}}
        log = script([{"tool_calls": [call]}, {"json": expert}, {"text": "확인했어요."}])
        ok(ask(api, pid, q))
        body = json.loads(log[-1]["messages"][-1]["content"][0]["content"])
        assert len(log) == 3 and body["route"] == "expert", kind
        assert "v3_empty" not in body  # 기록 칸은 모델에 가지 않아요
    route["v"] = "out_of_scope"  # 범위 밖 안내는 v3 그대로(전문가를 부르지 않아요)
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "price"}}
    log = script([{"tool_calls": [call]}, {"text": "확인했어요."}])
    ok(ask(api, pid, q))
    assert len(log) == 2
    route["v"] = "answer"
    monkeypatch.setattr(settings, "assistant_answer_route", "v3")  # 전부 v3면 물러서지 않아요
    log = script([{"tool_calls": [call]}, {"text": "확인했어요."}])
    ok(ask(api, pid, q))
    assert len(log) == 2

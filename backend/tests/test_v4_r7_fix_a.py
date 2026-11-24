"""QA r7 고침 A(고객 비서). 유료 호출 0회(Claude 대본 · 계산 엔진).

- 1. 집 정보 승인 카드 차액의 까닭(c2 T9~T11): 계산 엔진 줄로 바뀌는 줄 · 기준을 모델 값 change와 다음 턴 사실에
  넘겨요. 화면 카드 글은 그대로예요.
- 2. 값이 섞인 견주기(c2 L27) · v3 빈 답(c2 L21)은 공정 전문가로. 기본 경로(period=v3,price=v3,*=expert+v3)는 그대로예요.
- 3. 전문가 답(c1 6 · 10 · 13 · 25턴 · c2 18문항 중 12): 근거 조각 · 출처 이름 알아 두기 카드, 확인할 조건 끝 물음
  (아는 칸을 되묻는 조건은 버림), 카드 인용 '-다'체는 '-요'체로(못 바꾸면 원문 인용).
- 4. 첫 인사 · 첫 칩 · 지시문 첫 답이 도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기를 알려요.
- 5. 비서가 되물은 것에 고객이 답하면 그 답으로 판단 한 문장을 먼저 잇기(c2 L22 → L23, 지시문 규칙).
- 6. 비서 실측 요청 카드에 고객이 말한 희망 기간(화면 N3): wish 칸, 검사는 계산 엔진(화면 요청과 같은 규칙).
- 7. 지금 할 일 줄은 한 답에 한 번, 지난 턴과 같은 상태면 다시 말하지 않기(c1 19 · 27 · 20~23턴).
"""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant.experts import agent as experts
from app.assistant.tools import answer, cards, propose
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


# ---- 3. 전문가 답의 근거 · 출처 카드 · 확인할 조건 끝 물음 · '-해요'체 카드 인용 ----


def test_plain_excerpts_read_polite_or_stay_quoted():
    """카드 발췌 '-다'체는 자주 나오는 끝만 '-요'체로(QA r7 c2 L21 '…안내한다.' · '…본다.'), 못 바꾸면 원문 인용 그대로."""
    assert (
        cards.quoted("이음매는 띠초배로 보강하도록 안내한다.")
        == "이음매는 띠초배로 보강하도록 안내해요."
    )
    assert cards.quoted("바탕 상태를 먼저 살펴본다. 들뜬 곳은 제거한다.") == (
        "바탕 상태를 먼저 살펴봐요. 들뜬 곳은 제거해요."
    )
    assert cards.quoted("바탕은 충분히 건조되어야 한다.") == "바탕은 충분히 건조돼야 해요."
    assert cards.quoted("이 작업은 필수입니다.") == "이 작업은 필수예요."
    assert cards.quoted("시공 기준이다.") == "시공 기준이에요."
    # 한 문장이라도 못 바꾸면 줄 전체를 원문 인용으로(섞어 바꾸지 않아요)
    assert (
        cards.quoted("도배지를 바른다. 기포는 뺀다.") == "자료에서 “도배지를 바른다. 기포는 뺀다.”"
    )
    assert cards.quoted("실크는 닦을 수 있어요.") == "실크는 닦을 수 있어요."  # '-요'체는 그대로


def test_expert_ask_about_a_known_fact_is_dropped():
    """확인할 조건이 이 집 사실로 아는 칸(살면서 · 벽지 종류 · 철거)을 되묻으면 버려요(전문가 출력 검사)."""
    out = experts.ExpertOut.model_validate(
        _out(("곰팡이는 없애고 말린 뒤 도배해요.", ["G"]), ask_="살면서 공사하시는지")
    )
    known = frozenset({"living", "grade"})
    note = experts.refine("도배", out, {}, "", known)
    assert note.ask == "" and note.dropped["known"] == 1
    for ask_ in ("지금 벽에 결로 자국이 있는지", "살면서 공사하시는지"):
        got = experts.refine("도배", out.model_copy(update={"ask": ask_}), {}, "", frozenset())
        assert got.ask == ask_  # 모르는 칸이면 그대로


def _piece(ref: str, text: str, **kw) -> "experts.Piece":
    return experts.Piece(
        ref, kw.pop("kind", "표준시방서"), "KCS 41 51 05 도배공사", "3.3 바탕", text, **kw
    )


def test_expert_card_shows_cited_pieces_and_public_sources():
    """전문가 답이 기댄 조각(근거 번호 차례) → 알아 두기 카드: 공공 · 표준은 펴낸 곳, 그 밖은 자료 종류 이름. 전문 지식(G)만
    기댄 답은 카드가 없어요."""
    k1 = _piece(
        "K1", "곰팡이는 제거하고 충분히 건조해야 한다.", publisher="국토교통부", official=True
    )
    k2 = _piece("K2", "현장에서는 곰팡이 방지제를 바르기도 한다.", kind="시공 후기")
    note = experts.Note(
        trade="도배",
        pieces={"K1": k1, "K2": k2, "K3": _piece("K3", "쓰지 않은 조각이다.")},
        answer=[experts.Line("곰팡이는 없애고 말린 뒤 도배해요.", ("K1", "G"))],
        cautions=[experts.Line("방지제를 바르기도 해요.", ("K2",))],
    )
    card = answer.expert_card([note])
    assert card is not None and card.kind == "knowledge" and card.card_id.startswith("know-")
    assert card.data["lines"] == [
        "곰팡이는 제거하고 충분히 건조해야 해요.",
        "현장에서는 곰팡이 방지제를 바르기도 해요.",
    ]
    assert card.data["source"] == "국토교통부 · 시공 후기"
    only_g = experts.Note(trade="도배", pieces={"K1": k1}, answer=[experts.Line("말려요.", ("G",))])
    assert answer.expert_card([only_g]) is None


@pytest.mark.usefixtures("repo_search")
def test_expert_turn_sends_the_card_and_ends_with_the_ask(api, script, monkeypatch):
    """전문가 길 턴: 알아 두기 카드(출처)를 같이 보내고, 답에 묻는 말 · 다음 걸음이 없으면 확인할 조건을 끝 물음으로
    붙여요(QA r7 c1 6 · 10 · 13 · 25턴). 모델이 물음으로 끝내면 붙이지 않아요."""
    from app.assistant.experts import agent as experts_agent
    from tests.test_v4_assistant_offers import cards_of, tokens

    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    k1 = _piece(
        "K1", "곰팡이는 제거하고 충분히 건조해야 한다.", publisher="국토교통부", official=True
    )

    async def consult(_trades, _question, _home, _terms=()):
        line = experts.Line("곰팡이는 없애고 말린 뒤 도배해요.", ("K1",))
        return [
            experts.Note(
                trade="도배", pieces={"K1": k1}, answer=[line], ask="지금 벽에 결로 자국이 있는지"
            )
        ]

    monkeypatch.setattr(experts_agent, "consult", consult)
    q = "곰팡이 핀 벽에 그냥 도배해도 돼요?"
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "general"}}
    log = script([{"tool_calls": [call]}, {"text": "곰팡이는 없애고 말린 뒤 도배해요."}])
    ev = ok(ask(api, pid, q))
    body = tool_result(log, 1)
    assert answer.CARD_NOTE in body["note"]
    (card,) = cards_of(ev, "knowledge")
    assert card["data"]["source"] == "국토교통부"
    assert tokens(ev).endswith("\n\n지금 벽에 결로 자국이 있는지 알려 주시겠어요?")
    log = script([{"tool_calls": [call]}, {"text": "곰팡이는 없애고 말려요. 벽에 물기도 있나요?"}])
    ev = ok(ask(api, pid, q))
    assert tokens(ev).endswith("벽에 물기도 있나요?")  # 모델이 물었으면 끝 물음을 더 붙이지 않아요
    assert answer.ask_tail({"route": "v2g", "items": []}) is None
    assert (
        answer.ask_tail(
            {
                "route": "expert",
                "items": [{"label": answer.ASK_LABEL, "lines": [{policy.DATA_KEY: "벽 상태"}]}],
            }
        )
        is None
    )  # '…지' 꼴이 아니면 붙이지 않아요


# ---- 4. 첫 인사 · 첫 칩이 도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기를 알려요 ----


def test_first_greeting_and_chips_name_the_three():
    """처음 화면 인사(두세 문장) · 첫 칩과 지시문 첫 답 규칙이 지식 질문 · 직접 할 일 · 집 조건 바꾸기를 알려요(QA r7
    c1 · c2 · c4 그대로). 칩이 무료 모드에서 가는 길은 test_v4_assistant_free_qa CHIP_PATH가 봐요."""
    from tests.test_v4_assistant_free_qa import ROOT, first_chips

    feed = (ROOT / "frontend/components/assistant/Feed.tsx").read_text(encoding="utf-8")
    assert "도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물어보세요." in feed
    chips = first_chips()
    assert {"직접 할 수 있는 일 있어요?", "집 정보 바꾸고 싶어요", "업체 추천해 줘"} <= set(chips)
    from app.assistant import prompts

    assert "도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물을 수 있다고" in prompts.rules(
        "customer"
    )


# ---- 5. 되물은 답 잇기 ----


def test_rule_continues_from_the_answer_to_our_question():
    """앞 답에서 비서가 물은 것('물기 · 누수 흔적도 있나요?')에 고객이 답하면 그 답으로 판단을 이어요(QA r7 c2 L23)."""
    from app.assistant import prompts

    rules = prompts.rules("customer")
    assert (
        "바로 앞 답에서 내가 물은 것에 고객이 답하면 그 답을 받은 판단 한 문장을 먼저 말해" in rules
    )


# ---- 6. 비서 실측 요청 카드에 고객이 말한 희망 기간 ----


def test_said_wish_uses_the_screen_request_rule():
    """고객이 말한 희망 기간 검사는 화면 요청(visit.flow.request)과 같은 규칙: 내일부터 · 끝이 앞이 아님 · 62일 안."""
    from datetime import date, timedelta

    from app.calc import slots
    from app.visit.models import WISH_SPAN_MAX

    t, day = date(2026, 11, 24), timedelta(days=1)
    assert slots.said_wish(t + day, t + 3 * day, t) is None
    assert slots.said_wish(t + day, t + day, t) is None  # 하루
    assert slots.said_wish(t, t + 3 * day, t) == "past"
    assert slots.said_wish(t + 3 * day, t + day, t) == "order"
    assert slots.said_wish(t + day, t + day * (1 + WISH_SPAN_MAX), t) is None
    assert slots.said_wish(t + day, t + day * (2 + WISH_SPAN_MAX), t) == "long"
    assert slots.SPAN_MAX == WISH_SPAN_MAX


def test_visit_request_card_takes_the_said_wish(api, script, monkeypatch):
    """'25일에서 27일 사이로요'(QA r7 화면 N3): 카드 희망 기간 · 실행한 요청이 고객이 말한 기간이에요. 규칙에 맞지 않는
    기간은 카드 없이 까닭(도구 오류)."""
    from datetime import timedelta

    from app.shared.clock import today_seoul
    from tests.conftest import query
    from tests.test_v3_visit_kit import customer, quiet, vendor
    from tests.test_v4_assistant_actions import approve
    from tests.test_v4_r6_a1_cards import RECOMMEND

    quiet(monkeypatch)
    vendor(api, "r7wish@mitjip.test", "결도배")
    _, pid = customer(api)
    start = today_seoul() + timedelta(days=2)
    end = start + timedelta(days=2)
    wish = {"start": start.isoformat(), "end": end.isoformat()}
    req = {
        "id": "p",
        "name": "propose_visit_request",
        "input": {"trade": "dobae", "vendor_refs": ["v1"], "wish": wish},
    }
    script([{"tool_calls": [RECOMMEND]}, {"tool_calls": [req]}, {"text": "카드를 확인해 주세요."}])
    ev = ok(ask(api, pid, "결도배에 실측 요청 보내 주세요. 모레부터 사흘 사이로요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    rows = {r["label"]: r["value"] for r in a["summary"]["rows"]}
    assert rows["희망 기간"] == cards.md_range(start, end)
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (v,) = query("select wish_start, wish_end from visits where project_id = $1::uuid", pid)
    assert (v["wish_start"], v["wish_end"]) == (start, end)

    bad = {**req, "input": {**req["input"], "wish": {"start": wish["end"], "end": wish["start"]}}}
    log = script([{"tool_calls": [bad]}, {"text": "기간을 다시 알려 주세요."}])
    ev = ok(ask(api, pid, "27일부터 25일까지로 해 주세요"))
    err = tool_result(log, 1)
    assert err["error"] == "bad_wish" and err["message"] == propose.WISH_SAID["order"]
    assert not [x for x in acts(ev) if x["status"] == "proposed"]


# ---- 7. 지금 할 일 줄은 한 답에 한 번 · 상태가 같으면 다시 말하지 않기 ----


def test_now_state_sentences():
    for t in (
        "지금은 결도배 답을 기다리는 중이에요.",
        "네, 내일 두 업체의 실측을 기다리시면 돼요.",
        "우리집벽지 실측은 11월 25일 오전에 예정돼 있어요.",
        "지금은 업체를 골라 실측을 요청할 차례예요.",
    ):
        assert policy.now_state(t), t
    for t in (
        "실크는 닦을 수 있어요.",
        "카드를 눌러 주세요.",
        "지금 바로 보내 드릴게요.",
        "다음 차례로 넘어가요.",
    ):
        assert not policy.now_state(t), t


def test_one_now_line_per_answer(api, script):
    """모델이 지금 단계를 이미 말했으면 코드의 지금 할 일 줄을 붙이지 않아요(QA r7 c1 19 · 27턴: '지금은 …' 두 번)."""
    from tests.test_v4_assistant_offers import tokens

    q = "이제 뭐부터 하면 돼요?"
    _, pid = home(api, "now1@mitjip.test")
    script([{"text": "확인했어요. 지금은 업체 답을 기다려 주세요."}])
    assert tokens(ok(ask(api, pid, q))) == "확인했어요. 지금은 업체 답을 기다려 주세요."
    _, pid = home(api, "now2@mitjip.test")  # 견줌: 지금 단계가 없는 답이면 붙여요
    script([{"text": "확인했어요."}])
    assert tokens(ok(ask(api, pid, q))).startswith("확인했어요.\n\n지금은 ")


def test_same_state_is_not_said_again(api, script, monkeypatch):
    """지난 턴과 같은 업체 · 상태의 지금 단계 문장은 다시 말하지 않고, 지금 할 일 줄도 붙이지 않아요(QA r7 c1 20~23턴).
    고객이 날짜 · 할 일을 물은 턴은 그대로 둬요."""
    from tests.test_v3_visit_kit import add, customer, quiet, vendor
    from tests.test_v3_visit_kit import ask as send_visits
    from tests.test_v4_assistant_offers import tokens

    quiet(monkeypatch)
    vid = vendor(api, "r7state@mitjip.test", "결도배")
    _, pid = customer(api)
    assert add(api, pid, vid).status_code == 201
    assert send_visits(api, pid, [vid]).status_code == 201
    script([{"text": "알겠어요. 결도배 답을 기다리는 중이에요."}])
    assert (
        tokens(ok(ask(api, pid, "업체 답은 어때요?"))) == "알겠어요. 결도배 답을 기다리는 중이에요."
    )
    script([{"text": "송금은 제가 할 수 없어요. 결도배 답을 기다리는 중이에요."}])
    assert tokens(ok(ask(api, pid, "계약금 송금해 줘"))) == "송금은 제가 할 수 없어요."
    script([{"text": "아직 답이 없어요. 결도배 답을 기다리는 중이에요."}])
    said = tokens(ok(ask(api, pid, "결도배 답은 언제 와요?")))
    assert said == "아직 답이 없어요. 결도배 답을 기다리는 중이에요."

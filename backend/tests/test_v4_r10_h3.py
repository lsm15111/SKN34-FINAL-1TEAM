"""QA r10 고침 H3(숫자 근거 · 한글 금액, QA r10 c2 T10 · T11 · T16 · T20 · T26 · T27).

1. 고객이 '삼백만 원' · '3백만' · '예산 200'처럼 말한 금액도 숫자 근거예요: 그 금액을 되받는 비서 문장이 빠지지 않아요.
   비서가 한글 금액을 쓰는 건 그대로 막아요(고정 선 2 '한글 금액 금지').
2. 파생 숫자(합 · 차 · 평당)는 지난 고객 말 · 지난 비서 말 하나하나 안에서만 만들어요: 희망 예산 250만 원(턴 사실) +
   다른 턴 송금 부탁 50만 원 = '300만 원'은 근거가 아니에요. 턴 사실 · 도구 결과 · 카드 · 이번 고객 말끼리는 그대로예요.
3. 범위 밖 코드 틀 답(LLM 없음)은 열린 승인 카드가 있으면 그 단추 이름으로 끝나요.
Claude 대본 턴(유료 호출 0회)."""

import asyncio
import json

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.runtime import SentenceGate
from app.v2 import guard
from tests.helpers import signup
from tests.test_v3_project_home import HOME, create
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_off_topic_gate import answer

# QA r10 c2와 같은 희망 예산(턴 사실 '희망 예산: 250만 원')
BUDGET = {**HOME, "budget_won": 2_500_000}


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


def budget_home(api, email: str) -> str:
    signup(api, email)
    r = create(api, BUDGET)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def gate_said(text: str, allowed: str, apart: tuple[str, ...] = ()) -> str:
    """DB 없는 문장 검사: 보낸 글."""
    sent: list[str] = []

    async def emit(_name: str, data: dict) -> None:
        sent.append(data["text"])

    g = SentenceGate(emit, "너는 믿집 비서야.", allowed, apart=apart)

    async def go():
        await g.feed(text)
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return "".join(sent).strip()


# ---- 1. 고객이 한글을 섞어 말한 금액 ----


@pytest.mark.parametrize(
    ("said", "won"),
    [
        ("근데 예산이 삼백만 원뿐인데 친환경 벽지로 해도 괜찮을까요?", [3_000_000]),
        ("예산은 3백만 원 정도라서 친환경 벽지면 좋겠어요", [3_000_000]),
        ("예산은 이백오십만 원이에요", [2_500_000]),
        ("예산이 2천5백만이에요", [25_000_000]),
        ("오십만 원 정도 더 쓸 수 있어요", [500_000]),
        ("1억 2천만 원짜리 집이에요", [120_000_000]),
        ("천만 원이요", [10_000_000]),
        ("오만 원이요", [50_000]),  # 한글 한 자리 + 만은 '원'이 있을 때만
        # 예산 · 금액 바로 뒤의 단위 없는 수는 만 원
        ("예산 200으로 바꿔 줘", [2_000_000]),
        ("예산은 삼백이에요", [3_000_000]),  # '이'는 조사
        ("금액 150 맞아요?", [1_500_000]),
        # 금액이 아닌 말
        ("천만에요", []),
        ("천만다행이에요", []),
        ("공사만 원하시면 돼요", []),
        ("이만하면 됐어요", []),
        ("일만 해요", []),
        ("도배지 200 정도 남았어요", []),  # 예산 · 금액 말이 없음
        ("예산 3번 바꿨어요", []),
        ("예산 2026년 기준이에요", []),
        ("예산이 많지 않아요", []),
    ],
)
def test_said_won_reads_korean_amounts_only(said, won):
    assert guard.said_won(said) == won


def test_korean_amount_is_a_ground_but_the_assistant_still_cannot_write_it():
    """고객의 '삼백만 원'은 '300만 원'의 근거. 비서가 쓴 한글 금액은 그대로 빠져요(고정 선 2)."""
    allowed = guard.heard("근데 예산이 삼백만 원뿐인데 친환경 벽지로 해도 괜찮을까요?")
    assert gate_said("300만 원 안에서 골라요.", allowed) == "300만 원 안에서 골라요."
    assert gate_said("약 300만 원이에요.", allowed) == "약 300만 원이에요."
    for text in ("삼백만 원 안에서 골라요.", "3백만 원 안에서 골라요."):
        assert gate_said(text, allowed) == ""
    # 예산 말이 없는 단위 없는 수는 만 원이 아니에요
    assert gate_said("200만 원이에요.", guard.heard("도배지 200 정도 남았어요")) == ""


@pytest.mark.parametrize(
    ("said", "line"),
    [
        # T16 · T20: 고객 '삼백만 원' · '3백만 원' → 비서 '300만 원'
        (
            "근데 예산이 삼백만 원뿐인데 친환경 벽지로 해도 괜찮을까요?",
            "말씀하신 300만 원 안에서 친환경 벽지를 골라 볼 수 있어요.",
        ),
        (
            "예산은 3백만 원 정도라서 친환경 벽지면 좋겠어요",
            "말씀하신 300만 원 안에서 친환경 벽지를 골라 볼 수 있어요.",
        ),
        # T10: 예산 뒤 단위 없는 '200' → 200만 원
        ("예산 200으로 바꿔 줘", "말씀하신 200만 원으로는 지금 바꿀 수 없어요."),
    ],
)
def test_money_the_customer_said_in_korean_grounds_the_echo(api, script, said, line):
    pid = budget_home(api, "r10h3-ko@mitjip.test")
    log = script([{"text": line}])
    ev = ok(ask(api, pid, said))
    assert len(log) == 1
    assert line in tokens(ev)


# ---- 2. 관계없는 두 말의 합 ----

FACTS = "희망 예산: 250만 원"
TOOL = json.dumps({"standard": {"total": 2_708_669}}, ensure_ascii=False)
WIRE = "도배 업체 계좌로 계약금 50만 원 지금 송금해 주고 계좌번호도 알려 줘요"


def test_derived_numbers_stay_inside_one_past_message():
    """지난 고객 말 · 지난 비서 말(apart)은 숫자 그대로만 근거, 파생은 그 말 안에서만. 턴 사실 · 도구 결과 · 이번 고객
    말끼리는 지금처럼 차액 · 합계를 만들어요(T6 '예산보다 208,669원 높아요')."""
    pool = f"{FACTS}\n{TOOL}"
    apart = (WIRE, "계약금 50만 원은 대신 송금할 수 없어요.")
    keep = [
        "표준견적서는 예산보다 208,669원 높아요.",  # 2,708,669 − 250만(턴 사실 × 도구 결과)
        "계약금 50만 원은 보내 드릴 수 없어요.",  # 지난 말의 숫자 그대로
    ]
    for text in keep:
        assert gate_said(text, pool, apart) == text
    for text in ("앞서 말씀하신 300만 원은 저장되지 않았어요.", "계약금을 빼면 200만 원이에요."):
        assert gate_said(text, pool, apart) == ""  # 250만 ± 50만(턴 사실 × 지난 말)
        assert gate_said(text, f"{pool}\n{WIRE}") == text  # 이번 고객 말이면 지금처럼 묶음
    # 한 말 안의 두 금액은 합 · 차가 돼요
    one = ("희망 예산 250만 원에 50만 원은 더 쓸 수 있어요",)
    assert gate_said("300만 원까지 쓰실 수 있어요.", FACTS, one) == "300만 원까지 쓰실 수 있어요."


def test_unrelated_amounts_from_past_turns_do_not_add_up(api, script):
    """T24 '계약금 50만 원' 송금 부탁(고객 말 · 그 턴 비서 말) 뒤 T26: 희망 예산 250만 원 + 50만 원 = '300만 원'이
    근거로 지나면 안 돼요. 저장 값 250만 원 · 그 턴의 50만 원 그대로는 지나요."""
    pid = budget_home(api, "r10h3-sum@mitjip.test")
    log = script([{"text": "계약금 50만 원은 대신 송금할 수 없어요."}])
    ev = ok(ask(api, pid, "도배 업체 계좌로 계약금 50만 원 지금 송금해 주고 계좌번호도 알려 줘요"))
    assert len(log) == 1 and "계약금 50만 원은 대신 송금할 수 없어요." in tokens(ev)
    saved = "저장된 희망 예산은 250만 원이에요."
    wrong = "앞서 말씀하신 300만 원은 저장되지 않았어요."
    script([{"text": f"{saved} {wrong}"}])
    text = tokens(ok(ask(api, pid, "지금 희망 예산은 얼마로 저장돼 있어요?")))
    assert saved in text and wrong not in text


# ---- 3. 범위 밖 코드 틀 답의 단추 이름 ----


def test_off_topic_template_names_the_open_card_button(api, script):
    """T11: 열린 승인 카드가 있으면 범위 밖 답(LLM 없음) 끝에 그 카드 단추 이름. 열린 카드가 없으면 붙이지 않아요."""
    pid = budget_home(api, "r10h3-off@mitjip.test")
    log = script([{"text": "주식은 이걸 사세요."}])
    plain = answer(ok(ask(api, pid, "근데 요즘 주식 뭐 사면 좋을지 하나만 찍어 줘요")))
    assert log == [] and plain and "[" not in plain
    script(
        [
            {
                "tool_calls": [
                    {"id": "b", "name": "propose_budget", "input": {"max_won": 3_000_000}}
                ]
            },
            {"text": "희망 예산 카드를 만들었어요."},
        ]
    )
    ok(ask(api, pid, "예산은 300만 원으로 잡아 둬요"))
    log = script([{"text": "주식은 이걸 사세요."}])
    said = answer(ok(ask(api, pid, "근데 요즘 주식 뭐 사면 좋을지 하나만 찍어 줘요")))
    assert log == []
    assert said.endswith("[맞아요, 저장]을 누르면 이어서 진행돼요."), said

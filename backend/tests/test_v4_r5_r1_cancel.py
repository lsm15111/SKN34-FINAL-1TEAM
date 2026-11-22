"""고침 5차 R1(QA r5 A s1-3 · s6-2): 취소 고르기 결과의 메모 글이 칩을 가리킨다. '둘 다 취소' 칩이 있는데 비서가
'"둘 다"라고 말씀해 주세요'라고 말로 하라고 함. 두 곳이면 [둘 다 취소], 셋 이상이면 [모두 취소]. 유료 호출 0회(Claude 대본)."""

import uuid
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant.runtime import RefTable
from app.assistant.tools import ToolCtx, propose
from app.shared.clock import SEOUL
from tests.test_v4_assistant_new_tools import cards_of, results, two_requests
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, ok


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


CHIP = "아래 칩에서 업체나 [둘 다 취소]를 고르면 돼요."


def test_two_requests_note_points_to_the_both_chip(api, script):
    """s1-3 · s6-2: 대상 없이 '취소해 줘' → 고르기 칩 + 메모 글. 메모가 칩 [둘 다 취소]를 가리키고, 칩을 가리키는 답은 누를
    승인 카드가 없어도 그대로 간다."""
    w = two_requests(api)
    answer = f"어느 업체 요청을 취소할까요? {CHIP}"
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "t0", "name": "propose_visit_cancel", "input": {"code": "other"}}
                ]
            },
            {"text": answer},
        ]
    )
    ev = ok(ask(api, w["pid"], "실측 요청 취소해 줘"))
    (got,) = results(log)
    assert got["state"] == "choose" and got["note"] == propose.CANCEL_CHOOSE_NOTE
    assert "칩" in got["note"] and "[둘 다 취소]" in got["note"]
    (pick,) = cards_of(ev, "options")
    assert pick["data"]["options"][-1]["label"] == "둘 다 취소"
    assert tokens(ev) == answer and policy.NO_CARD not in tokens(ev)


def ctx() -> ToolCtx:
    now = datetime(2026, 11, 22, 16, 30, tzinfo=SEOUL)
    return ToolCtx(
        user=None,  # type: ignore[arg-type]
        surface="customer",
        turn_id=uuid.uuid4(),
        chat_id=uuid.uuid4(),
        project_id=None,
        visit_id=None,
        today=date(2026, 11, 22),
        now=now,
        refs=RefTable(uuid.uuid4()),
    )


def test_three_requests_note_points_to_the_all_chip():
    rows = [
        NS(id=uuid.uuid4(), vendor_name=name, trade="dobae", status=status)
        for name, status in (("결도배", "requested"), ("마루와벽", "offered"), ("한결", "booked"))
    ]
    out = propose.cancel_choose(ctx(), rows)
    note = out.data["note"]
    assert "[모두 취소]" in note and "[둘 다 취소]" not in note
    assert out.cards[0].data["options"][-1]["label"] == "모두 취소"
    two = propose.cancel_choose(ctx(), rows[:2])
    assert two.data["note"] == propose.CANCEL_CHOOSE_NOTE
    assert two.cards[0].data["options"][-1]["label"] == "둘 다 취소"

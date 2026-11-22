"""고침 4차 P 갈래 · 보이지 않는 글자로 끊은 번호가 비서 턴 저장 · LLM 입력 전에 가려지는지(QA r4 x1 턴 6), 가림 전후를
견주는 기억 검사는 보이지 않는 글자만으로 걸리지 않는지. 유료 호출 0회(Claude 대본). 번호는 모두 지어낸 값이에요."""

import pytest

from app.agent import llm
from app.assistant import memory
from app.shared.text import CONTROL, INVISIBLE
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok

ZW, FILLER, BOM = chr(0x200B), chr(0x3164), chr(0xFEFF)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def test_turn_saves_and_sends_numbers_split_by_hidden_letters_masked(api, script):
    _, pid = home(api)
    log = script([{"text": "연락처 · 동호수 · 계좌는 비서가 주고받지 않아요."}])
    said = (
        f"연락은 010{FILLER}1234{FILLER}5678로 주세요. 집은 101동{ZW}1203이에요. "
        f"입금은 3333 01 2345678로 할게요{BOM}"
    )
    ev = ok(ask(api, pid, said))
    assert ev[-1][0] == "done"
    (row,) = query("select text from chat_messages where role = 'user'")
    assert row["text"] == (
        "연락은 (번호 가림)로 주세요. 집은 (동호수 가림)이에요. 입금은 (계좌 가림)로 할게요"
    )
    assert not INVISIBLE.search(row["text"]) and not CONTROL.search(row["text"])
    sent = str(log[0]["messages"])
    for needle in ("5678", "1203", "2345678", "3333 01"):
        assert needle not in sent, needle


def test_memory_check_is_not_tripped_by_hidden_letters_alone():
    """기억 값 검사(memory._bad)는 '가림 전후가 다른가'로 연락처를 찾는다: 보이지 않는 글자만 든 말은 그대로 두고,
    보이지 않는 글자로 끊은 동호수는 연락처로 본다."""
    assert memory._bad(f"주말{ZW} 오전이 편해요") is None
    assert memory._bad(f"101동{ZW}1203") == "contact"

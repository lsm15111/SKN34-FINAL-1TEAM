"""v4 비서 기억 고치기(QA r1 '고칠 것' c1-2 · c1-4 · c3-3 · c4-7): 카드 단추 글은 기억을 뽑지 않음 ·
안 되는 때('평일엔 회사')를 되는 때로 저장하지 않고 같은 말의 되는 때('주말')로 · 옛 기억의 부정은 prefs가 뒤집음 ·
목록 칸(직접 할 일)은 덮지 않고 더함 · 이사 · 입주 때(move_in) 칸. 유료 호출 0회(Claude 대본)."""

from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import memory
from app.assistant.memory import Item
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok


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


def it(key: str, value: str, quote: str) -> Item:
    return Item(key=key, value=value, evidence_quote=quote)


def row(key: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value)


def sweep(api) -> None:
    from app import worker

    api.portal.call(partial(worker.sweep, datetime.now(UTC)))


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


# ---- 안 되는 때 (DB 없음) ----


def test_busy_days_become_the_free_days_in_the_same_message():
    msg = "제가 평일엔 회사에 있어서요. 실측을 주말에 할 수는 없을까요?"
    (got,) = memory.validate([it("avail_days", "평일엔 회사", "제가 평일엔 회사에 있어서요")], msg)
    assert (got.value, got.evidence_quote) == ("주말", "실측을 주말에 할 수는 없을까요")
    msg = "오전은 안 되고 오후만 돼요"
    (got,) = memory.validate([it("avail_half", "오전은 안 되고", msg)], msg)
    assert got.value == "오후만"


@pytest.mark.parametrize(
    ("key", "value", "msg"),
    [
        ("avail_days", "평일은 안 돼요", "평일은 안 돼요"),  # 되는 때를 말하지 않음
        ("avail_days", "평일엔 회사", "평일엔 회사예요"),
        ("avail_half", "아침엔 출근", "아침엔 출근해요"),
        ("avail_days", "2.1(월)", "2.1(월) 오전으로 할게요"),  # 한 번 고른 날짜(c4)
        ("avail_days", "12월 5일 토요일", "12월 5일 토요일에 와 주세요"),
    ],
)
def test_busy_or_one_day_is_not_saved(key, value, msg):
    assert memory.validate([it(key, value, msg)], msg) == []


def test_free_words_with_a_busy_quote_stay():
    """값이 되는 때면 인용에 안 되는 말이 있어도 그대로 받는다."""
    msg = "평일 저녁은 안 되고 주말만 돼요"
    (got,) = memory.validate([it("avail_days", "주말만", msg)], msg)
    assert got.value == "주말만"


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        ([row("avail_days", "평일엔 회사")], ("any", "weekend")),  # 옛 기억(뜻이 뒤집혀 쓰이던 것)
        ([row("avail_days", "평일엔 안 된다")], ("any", "weekend")),
        ([row("avail_days", "주말은 안 돼요")], ("any", "weekday")),
        ([row("avail_half", "오전엔 출근")], ("pm", "any")),
        ([row("avail_days", "주말에만")], ("any", "weekend")),
        ([row("avail_days", "토요일만")], ("any", "weekend")),
        (
            [row("avail_days", "평일 · 토요일"), row("avail_half", "평일 오후 · 토요일 오전")],
            ("am", "weekday"),
        ),
    ],
)
def test_prefs_reads_busy_words(rows, want):
    assert memory.prefs(rows) == want


# ---- 목록 칸 · 이사 (DB 없음) ----


def test_list_values_add_up():
    assert (
        memory.merged("조명 교체", "욕실 실리콘 · 주방 실리콘")
        == "조명 교체 · 욕실 실리콘 · 주방 실리콘"
    )
    assert memory.merged("실리콘 · 조명 교체", "욕실 실리콘") == "욕실 실리콘 · 조명 교체"
    assert memory.merged("조명 교체", "조명 교체") == "조명 교체"
    long = memory.merged("가" * 30, "나" * 20 + " · " + "다" * 20)
    assert len(long) <= memory.VALUE_MAX and long.endswith("다" * 20)  # 넘치면 오래된 것부터 뺀다
    assert memory.merged_quote("조명은 직접 해요", "실리콘도요") == "조명은 직접 해요 / 실리콘도요"
    assert memory.merged_quote("a / b", "b") == "a / b"


def test_list_items_in_one_message_merge():
    """한 말에서 직접 할 일이 두 줄로 나와도 둘째 줄을 버리지 않는다(c3: 첫 말의 실리콘이 빠짐)."""
    msg = "조명 교체랑 욕실 · 주방 실리콘은 저희가 직접 해요"
    (got,) = memory.validate(
        [it("diy", "조명 교체", msg), it("diy", "욕실 실리콘 · 주방 실리콘", msg)], msg
    )
    assert (got.value, got.evidence_quote) == ("조명 교체 · 욕실 실리콘 · 주방 실리콘", msg)
    two = memory.validate([it("pet", "강아지", msg), it("pet", "고양이", msg)], msg)
    assert two == []  # 인용 밖 값은 목록 칸이어도 버린다


def test_move_in_is_kept_but_money_is_not():
    msg = "12월 말에 이사 들어가요"
    (got,) = memory.validate([it("move_in", "12월 말 이사", msg)], msg)
    assert (got.key, got.value) == ("move_in", "12월 말 이사")
    assert memory.LABEL["move_in"] == "이사 · 입주" and memory.wants(msg)
    q = "이사 비용이 300만 원이라 12월 말에 들어가요"
    assert memory.validate([it("move_in", "이사 비용 300만 원", q)], q) == []


# ---- 턴 → 기억 일 → 저장 ----


def remember(api, script, pid: str, text: str, items: list[dict]) -> None:
    """무료 모드 턴 하나 → 기억 일을 Haiku 대본(items)으로 처리한다."""
    query("delete from jobs")
    llm.clear_stubs()
    assert ok(ask(api, pid, text))[-1][0] == "done"
    script([{"json": {"items": items}}])
    sweep(api)
    llm.clear_stubs()


def test_button_text_makes_no_memory_job(api):
    _, pid = home(api)
    ok(ask(api, pid, "11.28(토) 오전로 할래요", context={"choice": "visit_slot:s2"}))
    assert query("select id from jobs where kind = 'assistant_memory'") == []
    ok(ask(api, pid, "토요일 오전이 편해요"))  # 사람이 쓴 같은 꼴의 말은 일을 만든다
    assert len(query("select id from jobs where kind = 'assistant_memory'")) == 1


def test_diy_adds_up_and_move_in_reaches_the_facts(api, script):
    _, pid = home(api)
    remember(
        api,
        script,
        pid,
        "조명 교체는 저희가 직접 하려고요",
        [
            {
                "key": "diy",
                "value": "조명 교체",
                "evidence_quote": "조명 교체는 저희가 직접 하려고요",
            }
        ],
    )
    remember(
        api,
        script,
        pid,
        "욕실이랑 주방 실리콘도 저희가 직접 해요. 12월 말에 이사 들어가요",
        [
            {
                "key": "diy",
                "value": "욕실 실리콘 · 주방 실리콘",
                "evidence_quote": "욕실이랑 주방 실리콘도 저희가 직접 해요",
            },
            {
                "key": "move_in",
                "value": "12월 말 이사",
                "evidence_quote": "12월 말에 이사 들어가요",
            },
        ],
    )
    rows = {r["key"]: r for r in query("select * from assistant_memory")}
    assert rows["diy"]["value"] == "조명 교체 · 욕실 실리콘 · 주방 실리콘"  # 덮지 않고 더한다
    assert rows["diy"]["evidence_quote"] == (
        "조명 교체는 저희가 직접 하려고요 / 욕실이랑 주방 실리콘도 저희가 직접 해요"
    )
    (last,) = query(
        "select id from chat_messages where role = 'user' order by created_at desc limit 1"
    )
    assert (
        rows["diy"]["evidence_message_id"] == last["id"] == rows["move_in"]["evidence_message_id"]
    )
    got = {m["key"]: m["label"] for m in api.get("/assistant/memory").json()}
    assert got == {"diy": "직접 할 일", "move_in": "이사 · 입주"}
    log = script([{"text": "알겠어요."}])
    ok(ask(api, pid, "오늘 할 일 알려 줘"))
    assert "이사 · 입주: 12월 말 이사" in facts_of(log[0])

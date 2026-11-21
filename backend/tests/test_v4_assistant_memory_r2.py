"""v4 비서 기억 고침 2차(QA r2 갈래 E1): '안 되는 때'를 되는 때로 뒤집어 저장하지 않음(R2: 나열 · 앞에 온 부정 ·
값에 부정이 없는 말 · 없어요 · 싫어요) · 목록 칸(직접 할 일)이 줄이거나 뺀 말을 담음(R6) · 기억 뽑기 스키마 상한을
넘는 답 하나로 일 전체가 실패하거나 유료로 다시 하지 않음(R15). 유료 호출 0회(Claude 대본)."""

import json
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
from tests.test_v4_llm_claude import run as run_llm


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


# ---- R2: 안 되는 때 (DB 없음) ----


@pytest.mark.parametrize(
    ("key", "value", "msg"),
    [
        ("avail_days", "토요일이나 일요일은 안 돼요", "토요일이나 일요일은 안 돼요"),
        ("avail_days", "토요일, 일요일은 안 돼요", "토요일, 일요일은 안 돼요"),
        ("avail_days", "토요일", "토요일이나 일요일은 안 돼요"),
        ("avail_days", "평일", "안 되는 날은 평일이에요"),
        ("avail_days", "평일", "평일엔 회사라 안 돼요"),
        ("avail_days", "평일", "평일은 시간이 없어요"),
        ("avail_half", "오전", "오전은 싫어요"),
        ("avail_days", "주말", "주말은 피해 주세요"),
    ],
)
def test_busy_time_is_never_saved_as_free(key, value, msg):
    assert memory.validate([it(key, value, msg)], msg) == []


def test_busy_group_keeps_only_the_free_time():
    msg = "토요일이나 일요일은 안 되고 평일 저녁은 돼요"
    (got,) = memory.validate([it("avail_days", "토요일이나 일요일은 안 되고", msg)], msg)
    assert got.value == "평일"
    msg = "토요일은 되는데 일요일은 안 돼요"
    (got,) = memory.validate([it("avail_days", "토요일", msg)], msg)
    assert got.value == "토요일"


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        ([row("avail_days", "평일은 시간이 없어요")], ("any", "weekend")),
        ([row("avail_half", "오전은 싫어요")], ("pm", "any")),
        ([row("avail_days", "토요일이나 일요일은 안 돼요")], ("any", "weekday")),
        ([row("avail_days", "안 되는 날은 주말이에요")], ("any", "weekday")),
        ([row("avail_days", "토요일은 되는데 일요일은 안 돼요")], ("any", "weekend")),
    ],
)
def test_prefs_reads_busy_lists_and_words(rows, want):
    assert memory.prefs(rows) == want


# ---- R6: 목록 칸 줄이기 · 빼기 (DB 없음) ----


def test_list_value_can_shrink_and_drop():
    assert memory.only("실리콘", "생각해 보니 실리콘만 직접 할게요")
    assert memory.only("실리콘만", "실리콘만 할게요")
    assert not memory.only("실리콘", "실리콘도 직접 할게요")
    assert memory.without("조명 교체 · 실리콘", "조명은 업체에 맡길래요") == "실리콘"
    assert (
        memory.without("조명 교체 · 실리콘", "조명이랑 실리콘은 업체에 맡기고 페인트만 할게요")
        == ""
    )
    # 다른 일을 맡긴다는 말 · 멀리 떨어진 말은 빼지 않는다
    assert memory.without("조명 교체", "조명은 직접 하고 도배는 업체에 맡길게요") == "조명 교체"
    assert memory.without("조명 교체", "실리콘도 해 볼게요") == "조명 교체"
    assert memory.wants("조명은 업체에 맡길래요")


# ---- 턴 → 기억 일 → 저장 ----


def sweep(api) -> None:
    from app import worker

    api.portal.call(partial(worker.sweep, datetime.now(UTC)))


def remember(api, script, pid: str, text: str, items: list[dict] | Exception) -> None:
    """무료 모드 턴 하나 → 기억 일을 Haiku 대본(items)으로 처리한다."""
    query("delete from jobs")
    llm.clear_stubs()
    assert ok(ask(api, pid, text))[-1][0] == "done"
    script([items if isinstance(items, Exception) else {"json": {"items": items}}])
    sweep(api)
    llm.clear_stubs()


def diy(api) -> str | None:
    got = query("select value from assistant_memory where key = 'diy'")
    return got[0]["value"] if got else None


def test_diy_memory_shrinks_and_drops_in_turns(api, script):
    _, pid = home(api)
    said = "조명 교체랑 실리콘은 저희가 직접 해요"
    remember(
        api,
        script,
        pid,
        said,
        [{"key": "diy", "value": "조명 교체 · 실리콘", "evidence_quote": said}],
    )
    assert diy(api) == "조명 교체 · 실리콘"
    said = "생각해 보니 실리콘만 직접 할게요"
    remember(api, script, pid, said, [{"key": "diy", "value": "실리콘", "evidence_quote": said}])
    assert diy(api) == "실리콘"  # '만': 덮어쓴다
    said = "실리콘은 업체에 맡길래요"
    remember(api, script, pid, said, [])  # Haiku는 뺀 일을 뽑지 않는다
    assert diy(api) is None  # 다 뺐으면 그 기억을 지운다
    (job,) = query("select status from jobs where kind = 'assistant_memory'")
    assert job["status"] == "done"


# ---- R15: 기억 뽑기 스키마 ----


def test_extraction_keeps_good_items_and_ignores_long_or_broken_ones():
    raw = {
        "items": [
            {"key": "avail_days", "value": "주말", "evidence_quote": "주말이 편해요 " + "가" * 450},
            {"key": "style", "value": "화이트 톤"},  # 칸이 빠진 줄
            {"key": "style", "value": "화이트 톤", "evidence_quote": "화이트 톤이 좋아요"},
            *[{"key": "pet", "value": f"강아지{i}", "evidence_quote": "강아지"} for i in range(9)],
        ]
    }
    got = memory.Extracted.model_validate_json(json.dumps(raw, ensure_ascii=False))
    assert [x.key for x in got.items][:2] == ["avail_days", "style"] and len(got.items) == 11


def test_bad_extraction_answer_is_not_retried(api, monkeypatch, script):
    script([{"json": {"items": "목록이 아니에요"}}])

    async def go():
        return await memory.extract("주말이 편해요", None)

    assert run_llm(monkeypatch, go) == []  # 꼴이 틀린 답은 다시 부르지 않는다(유료 재시도 없음)
    script([{"stop": "max_tokens", "text": "{"}])
    assert run_llm(monkeypatch, go) == []
    script([RuntimeError("down")])
    with pytest.raises(llm.LLMError):  # 공급자 일시 오류는 일이 다시 해 본다
        run_llm(monkeypatch, go)


def test_long_quote_answer_saves_instead_of_failing_the_job(api, script):
    _, pid = home(api)
    said = "주말이 편해요. " + "집 정리를 천천히 하고 있어요. " * 25  # 인용이 400자를 넘는다
    remember(
        api,
        script,
        pid,
        said,
        [{"key": "avail_days", "value": "주말", "evidence_quote": said.strip()}],
    )
    (job,) = query("select status, attempts from jobs where kind = 'assistant_memory'")
    assert (job["status"], job["attempts"]) == ("done", 0)  # 실패해 유료로 다시 하지 않는다
    (got,) = query("select key, value, evidence_quote from assistant_memory")
    assert (got["key"], got["value"], got["evidence_quote"]) == ("avail_days", "주말", "주말")

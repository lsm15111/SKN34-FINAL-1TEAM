"""QA r7 고침 B 1(c1 · c2 기억 0): OpenAI 길 기억 뽑기가 물음이 섞인 말에서 빈 목록만 냈어요(출력 12토큰 = {"items":[]}).
지시문 memory_v4는 물음 속 자기 사실(반려동물 · 직접 할 일)을 뽑고 고객 낱말을 바꾸지 않게 해요. 검사는 직접 할 일을
조각마다 봐 인용 밖 조각만 빼요. 유료 호출 0회(가짜 OpenAI 클라이언트, 모델이 지시문을 따르는지는 소액 실확인 몫)."""

import json
from datetime import UTC, datetime
from functools import partial

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import memory, prompts
from app.assistant.memory import Item
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_openai import answer, openai  # noqa: F401 - 가짜 OpenAI 클라이언트 fixture

PET_ASK = "참 우리 집에 강아지 있는데 공사할 때 괜찮아요?"  # c1 13턴
DIY_ASK = (  # c2 L14
    "몰딩이랑 걸레받이는 새로 달 거예요. 그리고 문틀이랑 몰딩 페인트는 제가 직접 칠하고, 조명도 제가 직접 갈 "
    "거예요. 벽지도 제가 직접 사서 업체엔 시공만 맡기려고요. 페인트는 언제 칠하면 되고, 업체엔 뭘 알려야 해요?"
)


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def said_free(api, pid: str, text: str) -> None:
    """무료 모드 턴 하나(LLM 꺼짐) → 기억 뽑기 일이 생겨요."""
    llm.clear_stubs()
    ok(ask(api, pid, text))
    assert len(query("select id from jobs where kind = 'assistant_memory'")) == 1


def sweep(api) -> dict:
    from app import worker

    return api.portal.call(partial(worker.sweep, datetime.now(UTC)))


def items(*rows: tuple[str, str, str]) -> str:
    return json.dumps(
        {"items": [{"key": k, "value": v, "evidence_quote": q} for k, v, q in rows]},
        ensure_ascii=False,
    )


def test_memory_prompt_v4_takes_own_facts_said_inside_questions():
    assert prompts.version("memory") == "memory_v4"
    text = prompts.text("memory")
    assert "판: memory_v4" in text
    assert "물음이 섞인 메시지라도 고객이 자기 집 · 자기 상황을 사실로 말한 조각은 뽑아" in text
    assert '"집에 고양이가 두 마리 있는데 풀 냄새는 괜찮을까요?" → pet: "고양이 두 마리"' in text
    assert (
        '"강아지 키우는 집은 보통 어떤 벽지를 써요?" → 뽑을 것 없음' in text
    )  # 남의 집 · 일반 물음
    assert "'갈게요'를 '교체'로" in text and "'직접'은 고객이 그 말을 했을 때만" in text
    assert "자재를 고객이 직접 사는 것도 직접 할 일이야" in text
    # memory_v3의 물음 · 가정 · 견주기 · 부사 규칙은 그대로예요
    assert "물음 · 가정 · 견주기는 바람이 아니야" in text and "부사 · 말버릇" in text


def test_pet_said_with_a_question_is_saved_on_the_openai_path(api, openai):  # noqa: F811
    _, pid = home(api)
    said_free(api, pid, PET_ASK)
    log = openai([answer(items(("pet", "강아지", "우리 집에 강아지 있는데")))])
    assert sweep(api) == {("assistant_memory", "done"): 1}
    (row,) = query("select key, value, evidence_quote from assistant_memory")
    assert dict(row) == {
        "key": "pet",
        "value": "강아지",
        "evidence_quote": "우리 집에 강아지 있는데",
    }
    (req,) = log  # 기억 뽑기 요청: 작은 모델 · 추론 없음 · 엄격 꼴 · 고객 말 한 줄만
    assert (req["model"], req["reasoning"]) == ("gpt-6-luna", {"effort": "none"})
    assert req["instructions"] == prompts.text("memory")
    assert req["input"] == [{"role": "user", "content": PET_ASK}]
    fmt = req["text"]["format"]
    assert (fmt["name"], fmt["strict"]) == ("Extracted", True)


def test_diy_parts_survive_one_reworded_part(api, openai):  # noqa: F811
    """c2 L14: '조명 교체'(고객 말은 '갈 거예요') 한 조각 때문에 직접 할 일이 통째로 빠지던 답도 맞는 조각은 남아요."""
    _, pid = home(api)
    said_free(api, pid, DIY_ASK)
    quote = "문틀이랑 몰딩 페인트는 제가 직접 칠하고, 조명도 제가 직접 갈 거예요."
    openai([answer(items(("diy", "문틀 페인트 · 몰딩 페인트 · 조명 교체", quote)))])
    assert sweep(api) == {("assistant_memory", "done"): 1}
    (row,) = query("select key, value from assistant_memory")
    assert (row["key"], row["value"]) == ("diy", "문틀 페인트 · 몰딩 페인트")


def test_diy_answer_in_customer_words_keeps_every_part(api, openai):  # noqa: F811
    _, pid = home(api)
    said_free(api, pid, DIY_ASK)
    quote = (
        "문틀이랑 몰딩 페인트는 제가 직접 칠하고, 조명도 제가 직접 갈 거예요. "
        "벽지도 제가 직접 사서 업체엔 시공만 맡기려고요."
    )
    value = "문틀 페인트 · 몰딩 페인트 · 조명 · 벽지 직접 사서"
    openai([answer(items(("diy", value, quote)))])
    assert sweep(api) == {("assistant_memory", "done"): 1}
    (row,) = query("select value from assistant_memory where key = 'diy'")
    assert row["value"] == value  # '업체엔 시공만 맡기려고요'가 벽지 직접 구매를 빼지 않아요


@pytest.mark.parametrize(
    ("value", "quote", "want", "why"),
    [
        # 고객이 하지 않은 '직접'은 떼요(칸 이름이 직접 할 일)
        ("문 손잡이 직접", "문 손잡이만 제가 갈려고요", "문 손잡이", []),
        ("거실 조명 직접", "거실 조명은 제가 달게요", "거실 조명", []),
        # 고객이 '직접'이라고 했으면 그대로예요
        ("장판 직접 깔기", "장판은 제가 직접 깔려고요", "장판 직접 깔기", []),
        # 인용 밖 낱말이 든 조각만 빼요
        (
            "문틀 페인트 · 몰딩 페인트 · 조명 교체",
            "문틀이랑 몰딩 페인트는 제가 직접 칠하고, 조명도 제가 직접 갈 거예요.",
            "문틀 페인트 · 몰딩 페인트",
            ["diy:part_outside"],
        ),
        # 남는 조각이 없으면 그 줄은 버려요(고객이 하지 않은 말)
        ("조명 교체", "조명은 업체가 갈 거예요", None, ["diy:value_outside"]),
        ("직접", "거실 조명은 제가 달게요", None, ["diy:value_outside"]),
    ],
)
def test_diy_value_is_checked_part_by_part(value, quote, want, why):
    lost: list[str] = []
    got = memory.validate([Item(key="diy", value=value, evidence_quote=quote)], quote, lost)
    assert [x.value for x in got] == ([want] if want else []) and lost == why
    # 다른 칸은 그대로 통째로 봐요(인용 밖 낱말이 있으면 버림)
    assert (
        memory.validate([Item(key="style", value="화이트 톤", evidence_quote=quote)], quote) == []
    )

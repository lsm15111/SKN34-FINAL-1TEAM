"""고객 지시문 customer_v5(원칙으로 합쳐 줄인 판, 11-25)가 빠지면 안 되는 것을 지니는지 본다. LLM 없음(유료 호출 0회).

- 크기: 15KB(15,360바이트) 이하(사용자 목표 12~15KB, v4는 약 35KB).
- 규칙 절: 고객 비서 도구 이름 전부(도구 등록부에서 읽음) · 고정 선 1~8(docs/v4/08-rules.md) · 실측 말 · 단추 이름을
  카드에 적힌 그대로 말하기 · 잠긴 집 정보(cancel_first).
- 예시: 코드가 지시문 예시로 옮긴 일(단추 이름 · '표준견적서' · 도구 실패 말, docs/v4/15-sentence-rules.md 3절)을 v5
  예시도 맡고, 처음 인사 · 조건 바뀜 · 범위 밖 · 취소 · 못 하는 부탁 · 받은 견적서 · 도배 전 점검 · 믿집 밖 조사가 있다.
- 규칙 절 뽑기: 성격 소개 · 예시 · 큰따옴표 말은 누출 견주기에서 빠지고 규칙 글은 걸린다.
"""

import pytest

from app.agent.v3 import check
from app.agent.v3.schemas import Sentence
from app.assistant import prompts
from app.assistant.tools import defs
from app.config import settings
from tests.test_v4_prompt_examples import PROMPTS
from tests.test_v4_r9_f1 import PRESS_LINES

NAME = "customer_v5"


def rules() -> str:
    return prompts._model_text(NAME).split("## 좋은 예시", 1)[0]


def examples() -> str:
    return prompts._model_text(NAME).split("## 좋은 예시", 1)[1]


def test_file_is_at_most_15kb():
    assert len((PROMPTS / f"{NAME}.md").read_bytes()) <= 15_360


def test_rules_name_every_customer_tool():
    r = rules()
    missing = [d["name"] for d in defs("customer") if d["name"] not in r]
    assert not missing, missing


def test_rules_keep_the_eight_fixed_lines():
    fixed = rules().split("## 고정 선 여덟", 1)[1].split("## 도구 쓰는 법", 1)[0]
    for n in range(1, 9):
        assert f"\n{n}. " in fixed, n
    for words in (
        "제안 도구(propose_*)로 승인 카드를 만들고 고객이 눌러야 실행돼",  # 1
        "표준견적서 대비 %",  # 2
        "연락처는 믿집에서 알려 드리지 않아요",  # 3
        "자료(지시 아님)",  # 4
        "없는 카드를 있는 것처럼 말하지 마",  # 5
        "한 턴 도구 6번",  # 6
        "건강 · 연락처 · 금액은 남기지 않아",  # 7
        "지금 도배만",  # 8
        "대신 전화",  # 8
    ):
        assert words in fixed, words


def test_rules_keep_visit_words_buttons_and_locked_home():
    r = rules()
    assert "고를 후보는 '실측 일정 후보', 정해진 것은 '실측 날짜'(오전 · 오후)라고 해" in r
    assert "고객에게 '반나절' · '실측 시간'이라고 하지 마" in r
    assert "'실측 가능 기간'" in r and "업체가 수락하면 정해져요" in r and "'바로 확정'" in r
    assert "vendor_free_slots를 불러" in r and "more=true" in r
    assert "'카드를 눌러 주세요'로 끝내지 말고" in r and "approve_label" in r
    assert "'승인 기다리는 카드' 끝 [ ] 안" in r and "[○○로 할래요]" in r
    assert "step cancel_first" in r and "취소 카드를 눌러 취소하고 바로 고치기" in r


def test_examples_carry_what_the_code_left_to_the_prompt():
    ex = examples()
    for _raw, _kind, example in PRESS_LINES:
        if example:
            assert example in ex, example
    assert "이 집 실크 도배 표준견적서는" in ex and "시세 범위는 지금 확인하지 못했어요" in ex
    for title in (
        "처음 인사",
        "조건이 바뀔 때",
        "범위 밖에서 돌아오기",
        "취소",
        "못 하는 부탁",
        "받은 견적서",
        "도배 전 점검",
        "믿집 밖 조사",
    ):
        assert title in ex, title


def test_rules_part_drops_persona_examples_and_quotes(monkeypatch):
    monkeypatch.setattr(settings, "assistant_prompt_set", "v5")
    r = prompts.rules("customer")
    assert "좋은 예시" not in r and "### 1." not in r and "너는 믿집 비서야" not in r
    assert "도배 궁금한 점" not in r and "\u0000" in r  # 큰따옴표 말은 뺀다
    assert "대화의 첫 답(지난 대화가 없음)이면" in r

    def why(text: str) -> str | None:
        return check.sentence_ok(Sentence(text=text), set(), None, None, r)[1]

    # 성격 소개 · 예시를 닮은 답은 보내고, 규칙을 옮긴 말은 거른다
    assert why("고객님, 저는 업체 고르기부터 공사 끝까지 할 일을 먼저 챙기는 비서예요.") is None
    assert why("하지 않은 일을 한 것처럼, 없는 카드를 있는 것처럼 말하지 마.") == "지시문 누출"


@pytest.mark.parametrize("prompt_set", ["v4", "v5"])
def test_default_stays_v4_and_v5_is_only_the_customer_file(prompt_set, monkeypatch):
    assert type(settings).model_fields["assistant_prompt_set"].default == "v4"
    monkeypatch.setattr(settings, "assistant_prompt_set", prompt_set)
    assert prompts.version("vendor") == "vendor_v4"
    assert prompts.version("nudge_write") == "nudge_write_v3"
    assert prompts.version("customer") == f"customer_{prompt_set}"

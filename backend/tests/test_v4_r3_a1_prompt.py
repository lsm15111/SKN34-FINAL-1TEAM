"""고침 3차 A1(QA r3): 고객 · 업체 지시문(customer_v4 · vendor_v4)이 리드 결정 1~4를 지키는지 본다. LLM 없음.

- 결정 1 · 4: 답은 짧게, 예시 답도 그 길이(모델은 예시 길이를 따라 해요). '길어도 돼' 예외 없음. 11-22 말풍선(사용자)부터
  규칙은 '말풍선 둘(많아야 셋) · 모두 합쳐 많아야 다섯 문장 · 문장은 50자 안팎'이고, 예시 답 전체는 그대로 160자 안이에요.
- 결정 2: 목록(-, 1.) · 굵은 글씨 · 제목 없음. 결정 3: 한국어로만.
- 할 일 2: 이름 부르기 원리 · '반갑습니다' · 지키지 못할 약속 · 취소 까닭 · 조사는 부탁했을 때만 · 채팅이 열린 업체만.
"""

import re

import pytest

from app.assistant import prompts
from tests.test_v4_prompt_examples import PROMPTS, answers, sl

EXAMPLE_BUBBLES = 3  # '말풍선 둘(많아야 셋)'
EXAMPLE_SENTS = 5  # '모두 합쳐 많아야 다섯 문장'
SENT_CHARS = 60  # '문장은 50자 안팎'
EXAMPLE_CHARS = 160  # 예시 답 전체(모델이 예시 길이를 따라 해요)
BUBBLE = re.compile(r"\n[ \t]*\n")
LIST = re.compile(r"(?m)^\s*(?:[-*•]|\d{1,2}[.)])\s|\s(?:[-*•]|\d{1,2}[.)])\s(?=\S)")


def rules(name: str) -> str:
    return prompts._model_text(name).split("## 좋은 예시", 1)[0]


@pytest.mark.parametrize("name", ["customer_v4", "vendor_v4"])
def test_example_answers_are_short_and_plain(name):
    got = answers(name)
    assert got
    bad = {}
    for a in got:
        text, sents = a["text"], sl.sentences(a["text"])
        bubbles = [b for b in BUBBLE.split(text) if b.strip()]
        why = []
        if len(bubbles) > EXAMPLE_BUBBLES:
            why.append(f"말풍선 {len(bubbles)}개")
        if len(sents) > EXAMPLE_SENTS:
            why.append(f"{len(sents)}문장")
        if any(len(x) > SENT_CHARS for x in sents):
            why.append(f"{SENT_CHARS}자 넘는 문장")
        if len(text) > EXAMPLE_CHARS:
            why.append(f"{len(text)}자")
        if "**" in text or LIST.search(text) or "#" in text:
            why.append("목록 · 굵은 글씨 · 제목")
        if a["long"]:
            why.append("'길어도' 예외 제목")
        if why:
            bad[a["key"]] = why
    assert not bad, bad


@pytest.mark.parametrize("name", ["customer_v4", "vendor_v4"])
def test_rules_set_length_format_and_korean_only(name):
    r = rules(name)
    assert "말풍선 둘(많아야 셋)" in r and "많아야 다섯 문장" in r
    assert ("문장은 50자 안팎으로 짧게" if name == "customer_v4" else "문장은 짧게 끊고") in r
    assert "목록(-, 1.) · 굵은 글씨 · 제목을 쓰지 마" in r
    assert "한국어로만 답해" in r and "지금은 한국어로만 답할 수 있어요" in r
    assert "길어도 돼" not in prompts._model_text(name)


def test_customer_rules_follow_the_r3_list():
    r = rules("customer_v4")
    assert "화면이 로그인한 이름" not in r  # 이름 부르기 원리를 말하지 않게(s2)
    assert "'반갑습니다' 같은 '-습니다'체는 쓰지 마" in r
    assert "최근 처리한 카드 줄은 고객이 방금 누른 결과야" in r and "사과하거나 정정하지 말고" in r
    assert "'다시 확인해서 알려 드릴게요' 같은 약속" in r and "조사 결과" in r
    assert "그날에 맞춰 업체를 골라 드릴게요" in r
    assert "말하지 않았으면 other" in r
    assert "업체가 수락하면 정해져요" in r
    assert "고객이 부탁했을 때만 start_research" in r and "찾아볼지 묻기만" in r
    assert "채팅이 열린 업체만" in r and "업체가 실측 시간을 수락하면 채팅이 열려요" in r
    assert "새로 만들겠다거나 만들까 묻지 말고" in r
    assert "'먼저 확인해 볼게요' 같은 혼잣말" in r and "'도구가 실패해서'" in r
    assert "지난 턴들과 같은 끝 질문은 되풀이하지 마" in r
    assert "카드의 [채팅 열기]를 가리켜" not in prompts._model_text("customer_v4")


def test_cancel_example_uses_changed_only_when_the_customer_said_so():
    body = (PROMPTS / "customer_v4.md").read_text(encoding="utf-8").split("### 9. 취소", 1)[1]
    block = body.split("### 10.", 1)[0]
    said = next(ln for ln in block.splitlines() if ln.startswith("- 고객(이미 보냈을 때):"))
    tool = next(ln for ln in block.splitlines() if ln.startswith("- 도구(이미 보냈을 때):"))
    assert "changed" in tool and "일정이 바뀌" in said


def test_vendor_rules_ban_inside_words_and_written_choices():
    r = rules("vendor_v4")
    assert "'서버가' · '도구에 잡힌' · '이 결과엔'" in r
    assert "'이 업체의 다른 공사'처럼 남처럼 부르지 마" in r or "남처럼 부르지 말고" in r
    assert "글로 다시 묻지 말고" in r and "같은 확인을 다시 묻지 말고" in r
    assert "다른 요청의 카드를 이 요청에 붙이지 마" in r
    assert "새 카드로 바뀌어 닫힌 카드는 남아 있다고 하지 말고" in r

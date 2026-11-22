"""말풍선 나누기 지시문(11-22 밤, 사용자 '응 말풍선 나누기 넣어줘'): 고객 · 업체 v4 지시문에 말풍선 규칙이 있고,
좋은 예시의 비서 답은 빈 줄로 나눈 말풍선 꼴(둘~셋)이며 쉼표로 두 문장을 잇지 않는다. DB · LLM 없음."""

import re

import pytest

from app.assistant import prompts

REACTION = re.compile(r"^(좋아요|알겠어요|맞아요|그럼요),\s")


@pytest.mark.parametrize("surface", ["customer", "vendor"])
def test_prompts_ask_for_bubbles(surface):
    rules = prompts.rules(surface)
    assert "말풍선" in rules and "빈 줄" in rules
    assert "쉼표로 잇지" in rules
    # 옛 길이 규칙은 말풍선 규칙으로 바뀌었다
    assert "두세 문장, 150자" not in prompts.system(surface)


@pytest.mark.parametrize("surface", ["customer", "vendor"])
def test_example_answers_are_written_as_bubbles(surface):
    """좋은 예시의 비서 답(여러 문장)은 빈 줄로 나눈 말풍선 꼴이고, '…요, …' 쉼표 이음이 없다."""
    text = prompts.system(surface)
    examples = text.split("## 좋은 예시", 1)[1]
    answers = re.findall(
        r"^- 비서[^:\n]*:\n(.*?)(?=\n- |\n### |\Z)", examples, re.DOTALL | re.MULTILINE
    )
    assert len(answers) >= 6
    for a in answers:
        bubbles = [b for b in re.split(r"\n\s*\n", a.strip()) if b.strip()]
        assert len(bubbles) >= 2, a
        assert len(bubbles) <= 3, a
        for b in bubbles:
            # 단추 이름 · 첫 맞장구('좋아요,')는 빼고 본다
            plain = re.sub(r"\[[^\]]*\]", "", REACTION.sub("", b.strip()))
            assert not re.search(r"(요|다),\s", plain), b
    # 한 줄로 쓴 옛 꼴 비서 답이 남지 않았다
    assert not re.search(r"^- 비서[^:\n]*: \S", examples, re.MULTILINE)

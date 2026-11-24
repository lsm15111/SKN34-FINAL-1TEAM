"""고침 3차 A1(QA r3): 고객 · 업체 지시문(customer_v4 · vendor_v4)이 리드 결정 1~4를 지키는지 본다. LLM 없음.

- 결정 1 · 4: 답은 짧게, 예시 답도 그 길이(모델은 예시 길이를 따라 해요). '길어도 돼' 예외 없음. 11-22 말풍선(사용자)부터
  규칙은 '말풍선 둘(많아야 셋) · 모두 합쳐 많아야 다섯 문장 · 문장은 50자 안팎'이고, 예시 답 전체는 그대로 160자 안이에요.
- 결정 2: 목록(-, 1.) · 굵은 글씨 · 제목 없음. 결정 3: 한국어로만.
- 할 일 2: 이름 부르기 원리 · '반갑습니다' · 지키지 못할 약속 · 취소 까닭 · 조사는 부탁했을 때만 · 채팅이 열린 업체만.
- 고침 6차(QA r6): 고객 답은 두세 문장 · 많아야 네 문장(예시도 넷 안), 막는 답 뒤 지금 할 일로 돌아오기, 밤 알림은
  미룬 알림 줄이 있을 때만, 먼 지역 · 목공 · 업체에 알리는 길 · 누가 할 일 · 채팅 열림은 턴 사실 말대로.
"""

import re

import pytest

from app.assistant import prompts
from tests.test_v4_prompt_examples import PROMPTS, answers, sl

EXAMPLE_BUBBLES = 3  # '말풍선 둘(많아야 셋)'
# 고객 '많아야 네 문장'(고침 6차) · 업체 '많아야 다섯 문장'
EXAMPLE_SENTS = {"customer_v4": 4, "vendor_v4": 5}
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
        if len(sents) > EXAMPLE_SENTS[name]:
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
    assert "말풍선 둘(많아야 셋)" in r
    assert ("두세 문장, 많아야 네 문장" if name == "customer_v4" else "많아야 다섯 문장") in r
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
    assert (
        "채팅이 열린 업체만" in r
        and "그 줄 괄호 말대로" in r
        and "실측 날짜가 정해지면 채팅이 열려요" in r
    )
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


def test_customer_rules_follow_the_r6_list():
    """고침 6차(QA r6) 원리: 막는 답 뒤 지금 할 일로 · 밤 알림은 미룬 알림 줄이 있을 때만 · 먼 지역은 한 문장 · 목공은
    연결 준비 중과 다음 걸음 하나 · 업체에 알리는 실제 길 · 누가 할 일인지 · 기간은 보드와 같게 · 취향은 고르는 법."""
    r = rules("customer_v4")
    assert "범위 밖 · 잡담 · 되돌리기에도 한 문장으로 짧게 답하고 이 걸음으로 돌아와" in r
    assert "알림은 밤에도 바로 가" in r and "그 줄이 있을 때만 미룬 알림이 언제 가는지 말해" in r
    assert "밤 알림은 아침에 가요" not in prompts._model_text("customer_v4")
    assert "집과 먼 지역" in r and "지금 할 일로 돌아와" in r
    assert "그 업체 연결은 아직 준비 중이야" in r and "'공정을 바꾸세요'" in r
    assert "그 업체를 찾아 달라고 하면 이 말부터 하고" in r and "믿집 밖에서 찾아볼지 묻기만" in r
    assert "도배를 같이 하면 도배는 업체 연결까지 된다고" in r
    assert "업체에 전하는 길은 셋뿐이야" in r and "날짜 · 메모는 안 가" in r
    assert "요청은 두고 알리는 길(실측 때 · 열린 채팅)을 먼저 말하고" in r
    assert "고객에게 시키지 말고" in r and "건조 · 입주 청소까지" in r
    assert "취향은 정해 주지 말고 고르는 법을 말해" in r
    assert "모른다 · 확인할 수 없다고 하지 말고" in r and "[리뷰 쓰기]" in r


def test_vendor_rules_point_to_real_screen_paths():
    """고침 6차(QA r6 c4 V15 · V16 · V19 · V21): 못 하는 부탁도 대신 되는 길로. 수락한 날짜는 업체 화면
    [날짜 바꾸기]로 보내요(QA r7 c4 V18 · V26: 화면에 생긴 길을 '못 바꿔요'라고 함)."""
    r = rules("vendor_v4")
    assert "대신 되는 길(화면 단추 · 채팅 · 카드) 하나로 이어" in r
    assert "[추가 금액 올리기]" in r and "[공사 끝 알리기]" in r and "'리뷰 · 답글'" in r
    assert "[날짜 바꾸기]에서 새 날짜와 까닭을 보내 주세요" in r and "propose_dates" in r
    assert "바로 바꿀 수 없어요" not in r
    assert "알림은 밤에도 바로 가고" in r and "밤 9시~아침 9시 알림은 아침에 가" not in r


def test_card_made_words_say_what_pressing_does():
    """판정 에이전트 r8(S15 · S18): 카드를 만들고 누르면 무엇이 되는지 · 누르기 전엔 그대로인지를 말하지 않았어요."""
    r = rules("customer_v4")
    assert "다음 걸음은 누르면 무엇이 되는지로 말해" in r and "note에 없는 조건은 만들지 마" in r
    assert "누르기 전에는 마루와벽에 답이 가지 않아요" in r
    assert (
        "바닥 · 욕실 · 전기는 믿집이 금액 · 기간도 세지 않으니" in r
    )  # S11(목공은 표준견적서가 있어요)


def test_visit_words_for_customers():
    """고객에게 실측 후보는 '실측 일정 후보', 정해진 것은 '실측 날짜'(사용자 11-24: '반나절 후보' 표현이 이상해요)."""
    r = rules("customer_v4")
    assert "고를 후보는 '실측 일정 후보', 정해진 것은 '실측 날짜'(오전 · 오후)라고 해" in r
    assert "고객에게 '반나절' · '실측 시간'이라고 하지 마" in r

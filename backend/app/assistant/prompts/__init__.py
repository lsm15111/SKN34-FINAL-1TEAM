"""비서 지시문(판 번호 고정). 바꾸면 새 판 파일(customer_v2.md …)을 더하고 판 표(SETS · BASE)를 올린다(커밋 type prompt).

지시문에는 코드 값 · 규칙만 둔다. 업체 · 웹 · 고객 글은 넣지 않는다(턴 사실도 role:system 메시지로 따로 보낸다).
짧은 일(먼저 말 걸기 판정 · 문장, 기억 뽑기, 업체 브리핑 한 문장)은 Haiku 지시문을 따로 둔다.

- 판 고르기: settings.assistant_prompt_set(ASSISTANT_PROMPT_SET, 기본 v4). v4면 고객 · 업체 비서와 먼저 말 걸기 문장이
  새 판(customer_v4 · vendor_v4 · nudge_write_v3)이다. 판마다 지시문 글이 달라 프롬프트 캐시(지시문까지의 앞부분)도
  판마다 따로 맞는다. 같은 판이면 글이 같다(이 모듈이 파일마다 한 번 읽어 둔다).
- 표식: '<!-- 규칙 -->' · '<!-- 예시 -->'만 있는 줄은 코드만 읽고 모델에는 보내지 않는다. 문장 검사의 지시문 누출
  견주기(rules)는 규칙 절(규칙 표식부터 예시 표식 앞까지, 규칙 표식이 없는 파일은 글 전체에서 예시 절만 뺀 것)만 쓰고,
  그 안의 큰따옴표 말("…"라고 답해 · "…"처럼, 그대로 말해도 되는 말)도 뺀다. 성격 소개 · 좋은 예시를 닮은 답은
  누출로 버리지 않는다.
"""

import re
from functools import cache
from pathlib import Path

from app.config import settings

# 판 묶음마다 바뀌는 지시문(고객 · 업체 비서 · 먼저 말 걸기 문장). 켜는 결정은 리드가 해요(docs/v4/08-rules.md)
SETS: dict[str, dict[str, str]] = {
    "v3": {"customer": "customer_v3", "vendor": "vendor_v3", "nudge_write": "nudge_write_v2"},
    "v4": {"customer": "customer_v4", "vendor": "vendor_v4", "nudge_write": "nudge_write_v3"},
}
# 판 묶음과 상관없이 같은 지시문
BASE: dict[str, str] = {
    "nudge_judge": "nudge_judge_v1",
    "memory": "memory_v4",  # QA r7: 물음 속 자기 사실(반려동물) · 직접 할 일은 고객 낱말 그대로
    "brief": "brief_v2",
    "researcher": "researcher_v4",  # 조사 담당(worker, 웹 검색 · 가져오기, 진행 말 · 항목 꼴 · 자재 판매가 · 규격)
    # 공정 전문가 하위 에이전트(assistant/experts, 비서 answer_question 'expert' 엔진). 고객에게 직접 말하지 않아요
    "expert_dobae": "expert_dobae_v2",
    "expert_mokgong": "expert_mokgong_v2",
}
_DIR = Path(__file__).resolve().parent
MARK = re.compile(r"^<!--\s*(규칙|예시)\s*-->[ \t]*$")
# 그대로 말해도 되는 말(큰따옴표 안). 누출 견주기에서 빼고 빈 자리는 이어 붙지 않게 끊는다
QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")
CUT = "\u0000"


def version(name: str) -> str:
    """이름(customer · vendor · nudge_write · nudge_judge · memory · brief) → 지금 판 파일 이름."""
    return SETS[settings.assistant_prompt_set].get(name) or BASE[name]


@cache
def _raw(file: str) -> str:
    return (_DIR / f"{file}.md").read_text(encoding="utf-8")


@cache
def _model_text(file: str) -> str:
    """모델에 보내는 글: 표식 줄을 뺀다(표식이 없는 옛 판은 파일 글 그대로)."""
    lines = [ln for ln in _raw(file).splitlines() if not MARK.match(ln)]
    return "\n".join(lines).strip()


@cache
def _rules_text(file: str) -> str:
    lines = _raw(file).splitlines()
    on = not any(MARK.match(ln) and MARK.match(ln).group(1) == "규칙" for ln in lines)  # type: ignore[union-attr]
    kept: list[str] = []
    for ln in lines:
        m = MARK.match(ln)
        if m:
            on = m.group(1) == "규칙"
            continue
        if on:
            kept.append(ln)
    return QUOTED.sub(CUT, "\n".join(kept)).strip()


def text(name: str) -> str:
    """이름의 지시문 글(모델에 보내는 글)."""
    return _model_text(version(name))


def system(surface: str) -> str:
    """화면(customer · vendor)의 지시문. 판이 같으면 글이 같다(프롬프트 캐시)."""
    return text(surface)


def rules(surface: str) -> str:
    """화면 지시문의 규칙 절(문장 검사의 지시문 누출 견주기용, 모델에는 보내지 않는다)."""
    return _rules_text(version(surface))

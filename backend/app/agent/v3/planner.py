"""질문 분석기 (LLM 모드, 지시문 planner_v1). 데이터 화면(표준견적서 · 업체 자세히)에서 질문을 조각으로 나누고,
조각마다 꼴 · 가리킨 화면 항목 · 풀어 쓴 질문을 구조화 출력으로 받아요(docs/v3/agent-orchestrator.md 4장).

- 받는 것: 가린 질문, 보는 화면 이름, 화면 항목 목록(키 · 이름 · 짧은 뜻), 이 공사 공종. 숫자는 넘기지 않아요.
- 검사: items는 목록 안의 키만, 조각은 MAX_ASKS개까지, 빈 풀이 글은 원래 질문으로. 사용자 · 공사 id는 받지 않아요.
- 도구는 코드가 꼴로 골라요(screen_tools): 줄 · 비교 · 판단은 견적 설명 · 화면 사실, 뜻 · 방법 · 고를 것은 공종 지식,
  금액 · 기간은 계산 엔진.
- 실패(LLM 오류 · 조각 없음)면 None → 부르는 쪽은 지금 관문 길이에요.
"""

import json
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agent import llm
from app.agent.v3 import check, llm_mode
from app.agent.v3.schemas import ProjectFacts

PROMPTS = Path(__file__).with_name("prompts")
VERSION = "planner_v1"
DATA_VIEWS = ("standard", "vendor")  # 분석을 거는 화면(표준견적서 · 업체 자세히)
VIEW_KO = {"standard": "이 집 표준견적서", "vendor": "업체 자세히(가견적)"}
MAX_ASKS = 3
AskKind = Literal[
    "line", "compare", "judge", "rank", "what", "how", "choose", "price", "period", "schedule",
    "other",
]  # fmt: skip

# 표준견적서 줄 키 → 짧은 뜻(계산 엔진 calc/dobae.py 줄 정의). 분석기가 '인건비 · 밥값'을 줄에 잇는 데 써요
STANDARD_MEANING = {
    "wall": "벽 도배 시공비(사람이 바르는 일, 풀 포함, ㎡당)",
    "ceiling": "천장 도배 시공비(사람이 바르는 일, 풀 포함, ㎡당)",
    "paper": "도배지 값(벽지 평 × 시장 평균 가격)",
    "primer": "초배지 값",
    "occupied": "짐 있는 집 작업 할증",
    "removal": "기존 벽지 철거(실측 뒤 업체가 정함)",
    "waste": "폐기물 처리(실측 뒤 업체가 정함)",
    # 조건별 두 기준 판(calc/dobae.py PROFILE_LINES)에서 초배지 줄 대신 생긴 줄
    "material": "풀 · 부직포 · 네바리 · 실리콘 같은 부자재 값이에요",
    "putty": "도배 전에 벽 틈 · 굴곡을 메우는 퍼티 · 밑작업 값이에요",
    "meal": "작업자 1명 하루 밥값(식대)에 품 수를 곱한 값이에요",
    "truck": "자재를 나르는 차 · 주차 같은 운송 · 경비예요",
}
STATE_KO = {
    "included": "합계에 들어감",
    "bundled": "다른 줄에 묶여 들어감",
    "separate": "따로 계산해 합계에 들어감",
    "optional": "고르면 더함",
    "after_visit": "실측 뒤 업체가 정함(합계 밖)",
    "excluded": "안 함",
}


class Ask(BaseModel):
    text: str  # 그 조각을 풀어 쓴 질문('이 견적서' → '마루와벽 가견적', '밥값' → '식대')
    kind: AskKind
    items: list[str]  # 가리킨 화면 항목 키(목록에 있는 값만)
    trades: list[Literal["dobae", "mokgong"]]


class Plan(BaseModel):
    asks: list[Ask]
    out_of_scope: bool


@cache
def prompt() -> str:
    return (PROMPTS / f"{VERSION}.md").read_text(encoding="utf-8")


@cache
def rules() -> str:
    return prompt().split("## 예시")[0]


def items_of(view: str | None, facts: ProjectFacts | None) -> list[dict]:
    """화면 항목 목록(키 · 이름 · 뜻). 숫자는 넣지 않아요."""
    if facts is None:
        return []
    v = facts.screen.vendor if facts.screen is not None else None
    if view == "vendor" and v is not None:
        return [
            {"key": f"vendor.{x.key}", "name": x.name,
             "뜻": x.note or ("표준견적서에 없는 줄" if not x.in_standard else "표준견적서와 같은 일")}
            for x in v.lines
        ]  # fmt: skip
    if view == "standard" and facts.standard is not None:
        return [
            {"key": f"standard.{x.key}", "name": x.name,
             "뜻": " · ".join(t for t in (STANDARD_MEANING.get(x.key, ""), STATE_KO.get(x.state, "")) if t)}
            for x in facts.standard.lines
        ]  # fmt: skip
    return []


def screen_name(view: str | None, facts: ProjectFacts | None) -> str:
    v = facts.screen.vendor if facts is not None and facts.screen is not None else None
    if view == "vendor" and v is not None:
        return f"{v.vendor} 가견적(업체 자세히 화면)"
    return VIEW_KO.get(view or "", "화면")


def clean(p: Plan, question: str, keys: set[str]) -> Plan | None:
    """목록 밖 항목 키는 버리고, 조각은 MAX_ASKS개까지. 조각이 없으면 None."""
    asks = []
    for a in p.asks[:MAX_ASKS]:
        text = a.text.strip() or question
        items = [k for k in dict.fromkeys(a.items) if k in keys]
        asks.append(a.model_copy(update={"text": text[:200], "items": items}))
    if not asks and not p.out_of_scope:
        return None
    return p.model_copy(update={"asks": asks})


async def plan(question: str, view: str | None, facts: ProjectFacts | None) -> Plan | None:
    """질문 분석 한 번. 못 하면 None(부르는 쪽은 지금 관문 길)."""
    items = items_of(view, facts)
    if not items:
        return None
    trades = list(facts.trades) if facts is not None else []
    data = {"보는 화면": screen_name(view, facts), "화면 항목": items, "이 공사 공종": trades}
    messages = [
        ("system", prompt()),
        (
            "user",
            (
                f"<자료>{llm_mode._data(json.dumps(data, ensure_ascii=False))}</자료>\n"
                f"고객 질문: {llm_mode._data(check.mask(question))}"
            ),
        ),
    ]
    try:
        p = await llm.structured("planner", Plan, messages)
    except llm.LLMError:
        return None
    return clean(p, question, {x["key"] for x in items})

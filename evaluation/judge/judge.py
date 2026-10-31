"""판정 LLM: 공정 의견을 '필요한 정보만, 쉽게' 기준표(rubric_v1.md)로 기준마다 1~5점 매긴다.

- 층화 표본에만 쓰고, 실행기(run_agent.py --judge N --live)에서만 부른다. 호출은 app.agent.llm.parse로 한다.
- 시스템 프롬프트 = 기준표 + 그 공정의 지식(SKILL.md). 공정마다 같아 캐시된다.
- 판정 대상은 화면에 보이는 의견(코드 검사로 버린 항목을 뺀 것)이다.
- 점수 범위 검사는 스키마가 아니라 코드에서 한다 (app.agent.schemas와 같은 방식).
- 모델은 지금 LLM_MODEL 하나를 같이 쓴다 (llm.parse에 모델 인자가 없음).
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel

RUBRIC_VERSION = "rubric-v1"
RUBRIC = Path(__file__).with_name("rubric_v1.md")
CRITERIA = {
    "necessary_only": "필요한 정보만",
    "plain_words": "쉬운 말",
    "actionable": "할 일이 분명함",
    "correct": "틀린 내용 없음",
}


class Score(BaseModel):
    score: int
    reason: str


class Judgement(BaseModel):
    """판정 LLM 출력. 기준마다 점수(1~5)와 한 줄 이유"""

    necessary_only: Score
    plain_words: Score
    actionable: Score
    correct: Score


def system(skill: str) -> str:
    return RUBRIC.read_text(encoding="utf-8") + "\n\n# 공정 지식\n\n" + skill


def answer_text(plan: dict, sources: dict[str, str]) -> str:
    """화면 순서대로 의견을 글로 편다. 출처는 id 대신 이름으로 보인다."""
    rows = [f"요약: {plan['summary']}", "", "단계별 할 일:"]
    rows += [f"- {s['key']}: {s['note']}" for s in plan["steps"]]
    rows += ["", "실측 때 물어볼 것:", *(f"- {v}" for v in plan["visit_checks"])]
    rows += ["", "주의:"]
    rows += [
        f"- {c['text']} (출처: {sources.get(c['source'], c['source'])})" for c in plan["cautions"]
    ]
    return "\n".join(rows)


def user(agent_input: str, plan: dict, sources: dict[str, str]) -> str:
    """agent_input은 공정 에이전트가 받은 글 그대로다 (<input>…</input>)."""
    return f"{agent_input}\n\n<answer>\n{answer_text(plan, sources)}\n</answer>"


def check(j: Judgement) -> dict[str, dict]:
    """점수 범위 · 이유를 코드로 본다. 어긋나면 ValueError"""
    out = {}
    for key in CRITERIA:
        s = getattr(j, key)
        reason = s.reason.strip()
        if not 1 <= s.score <= 5:
            raise ValueError(f"{key}: 점수가 1~5 밖이에요")
        if not reason or len(reason) > 200:
            raise ValueError(f"{key}: 이유가 비었거나 너무 길어요")
        out[key] = {"score": s.score, "reason": reason}
    return out


async def judge(
    parse: Callable[..., Awaitable],
    skill: str,
    agent_input: str,
    plan: dict,
    sources: dict[str, str],
    effort: str = "low",
) -> tuple[dict[str, dict], object]:
    """parse는 app.agent.llm.parse (실행기가 기록용으로 감싸기 전 것을 넘긴다)."""
    j, usage = await parse(
        system(skill), user(agent_input, plan, sources), Judgement, effort=effort
    )
    return check(j), usage

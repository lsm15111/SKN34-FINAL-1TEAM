"""판정 LLM: 에이전트 답을 '필요한 정보만, 쉽게' 기준표로 기준마다 1~5점 매긴다.

- 기준표 둘: 공정 의견(rubric_v1.md) · 전문가 답(rubric_expert_v1.md, '질문에 맞게 답했는지' 포함)
- 층화 표본에만 쓰고, 실행기(--judge N --live)에서만 부른다. 호출은 app.agent.llm.parse(role="judge")라
  모델 · 생각 깊이는 LLM_MODEL_JUDGE · LLM_EFFORT_JUDGE로 따로 고른다 (비우면 LLM_MODEL · low)
- 시스템 프롬프트 = 기준표 + 그 공정의 지식(SKILL.md). 공정마다 같아 캐시된다
- 판정 대상은 화면에 보이는 답(코드 검사로 버린 항목을 뺀 것)이다
- 점수 범위 검사는 스키마가 아니라 코드에서 한다 (app.agent.schemas와 같은 방식)
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent


class Score(BaseModel):
    score: int
    reason: str


class Judgement(BaseModel):
    """공정 의견 판정: 기준마다 점수(1~5)와 한 줄 이유"""

    necessary_only: Score
    plain_words: Score
    actionable: Score
    correct: Score


class AnswerJudgement(BaseModel):
    """전문가 답 판정: 기준마다 점수(1~5)와 한 줄 이유"""

    answers_question: Score
    necessary_only: Score
    plain_words: Score
    correct: Score


@dataclass(frozen=True)
class Rubric:
    version: str
    path: Path
    criteria: dict[str, str]  # 기준 키 → 화면 말
    schema: type[BaseModel]


PLAN = Rubric(
    "rubric-v1",
    HERE / "rubric_v1.md",
    {
        "necessary_only": "필요한 정보만",
        "plain_words": "쉬운 말",
        "actionable": "할 일이 분명함",
        "correct": "틀린 내용 없음",
    },
    Judgement,
)
EXPERT = Rubric(
    "rubric-expert-v1",
    HERE / "rubric_expert_v1.md",
    {
        "answers_question": "질문에 맞게 답함",
        "necessary_only": "필요한 정보만",
        "plain_words": "쉬운 말",
        "correct": "틀린 내용 없음",
    },
    AnswerJudgement,
)
# 공정 의견 판정 이름 (예전 이름 그대로)
RUBRIC_VERSION, CRITERIA = PLAN.version, PLAN.criteria


def system(skill: str, rubric: Rubric = PLAN) -> str:
    return rubric.path.read_text(encoding="utf-8") + "\n\n# 공정 지식\n\n" + skill


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
    """공정 의견 판정 입력. agent_input은 공정 에이전트가 받은 글 그대로다 (<input>…</input>)."""
    return f"{agent_input}\n\n<answer>\n{answer_text(plan, sources)}\n</answer>"


def expert_user(context: str, question: str, answer: dict, sources: dict[str, str]) -> str:
    """전문가 답 판정 입력: 전문가가 받은 집 정보 · 질문과 화면에 보인 답"""
    names = [sources.get(s, s) for s in answer.get("sources") or []]
    used = f"\n(쓴 출처: {', '.join(names)})" if names else ""
    return (
        f"<input>\n집 정보:\n{context}\n\n고객 질문: {question}\n</input>\n\n"
        f"<answer>\n{answer['answer']}{used}\n</answer>"
    )


def check(j: BaseModel, rubric: Rubric = PLAN) -> dict[str, dict]:
    """점수 범위 · 이유를 코드로 본다. 어긋나면 ValueError"""
    out = {}
    for key in rubric.criteria:
        s = getattr(j, key)
        reason = s.reason.strip()
        if not 1 <= s.score <= 5:
            raise ValueError(f"{key}: 점수가 1~5 밖이에요")
        if not reason or len(reason) > 200:
            raise ValueError(f"{key}: 이유가 비었거나 너무 길어요")
        out[key] = {"score": s.score, "reason": reason}
    return out


def fake(rubric: Rubric = PLAN) -> dict:
    """가짜 판정 (모든 기준 5점, --fake 실행용)"""
    return {k: {"score": 5, "reason": "가짜 판정"} for k in rubric.criteria}


async def judge(
    skill: str, user_text: str, rubric: Rubric = PLAN, effort: str | None = None
) -> dict[str, dict]:
    """llm.parse(role="judge")로 매기고 점수를 검사한다. 사용량은 실행기가 parse를 감싸 남긴다."""
    from app.agent import llm

    j, _ = await llm.parse(
        system(skill, rubric), user_text, rubric.schema, role="judge", effort=effort
    )
    return check(j, rubric)

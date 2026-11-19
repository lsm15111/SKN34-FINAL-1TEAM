"""AI 칸 API 모양 (`/ai/*`, api.md 16절). 사용자 · 프로젝트는 서버가 세션으로 고정하고 LLM 출력으로 받지 않는다.

- 답 안의 숫자는 계산 엔진 값(CalcBox)뿐이고, 평가용 흔적(trace)은 내보내지 않는다.
- 출처는 이름 · 종류만 보낸다(주소 없음: `repo:` 같은 저장소 경로가 링크로 보이지 않게).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.v3.schemas import (
    TEXT_MAX,
    AskSlot,
    Button,
    CalcBox,
    Route,
    Section,
    UiCard,
    View,
)

NOTICE = "자동 답변"  # 9판 C09 · D01 화면 글(답 위 표시)
FIRST_NOTICE = "AI가 답해요. 금액 · 날짜는 믿집 계산을 그대로 보여 주고, 저장 · 확정은 하지 않아요."


class AiContext(BaseModel):
    screen: View | None = None
    project_id: uuid.UUID | None = None
    ids: list[str] = Field(default=[], max_length=5)


class AiTurnIn(BaseModel):
    client_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    chat_id: uuid.UUID | None = None
    context: AiContext = AiContext()
    button: Button | None = None


class AiSource(BaseModel):
    ref: str
    title: str
    kind: str = ""


class AiSection(BaseModel):
    title: str = ""
    sentences: list[str]
    caution: str = ""
    tip: str = ""
    source: Literal["card", "extract", "llm", "template", "calc"]
    route: Route
    trade: str | None = None
    sources: list[AiSource] = []
    cites: list[list[int]] = []  # 문장마다 출처 번호(AiAnswer.refs의 1부터). sentences와 같은 길이
    table: list[list[str]] = []  # 비교 블록 2칸 줄
    steps: bool = False  # 단계 블록


class AiBrief(BaseModel):
    """짧은 답: 먼저 보일 문장 1~3개(sections · unknown에서 고른 것). 나머지는 '자세히'에서 sections로 보여요."""

    form: str = "other"
    lines: list[str] = []
    more: int = 0
    cites: list[list[int]] = []  # 줄마다 출처 번호


class AiAnswer(BaseModel):
    notice: str = NOTICE
    sections: list[AiSection] = []
    calc: list[CalcBox] = []
    cards: list[UiCard] = []
    ask: AskSlot | None = None
    unknown: list[str] = []
    suggest: list[str] = []
    failed: bool = False
    brief: AiBrief | None = None
    refs: list[
        AiSource
    ] = []  # 이 답의 출처. 번호는 코드가 처음 나온 순서로 매겨요(LLM이 매기지 않음)


class AiTurnOut(BaseModel):
    """SSE `done` 이벤트 몸통."""

    chat_id: uuid.UUID | None
    rev: int | None
    mode: Literal["free", "llm"]
    route: Route
    answer: AiAnswer


class AiThreadOut(BaseModel):
    chat_id: uuid.UUID
    updated_at: datetime
    preview: str  # 마지막 질문 앞 40자


class AiMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    turn: int


class AiThreadDetailOut(BaseModel):
    chat_id: uuid.UUID
    rev: int
    messages: list[AiMessageOut]


class AiFaqOut(BaseModel):
    """로그인 전 자주 묻는 질문 칩(카드 파일만 읽음, 서버 계산 없음)."""

    id: str
    question: str
    sentences: list[str]
    tip: str = ""
    sources: list[AiSource] = []
    actions: list[str] = []


def section_out(s: Section) -> AiSection:
    src = []
    for x in s.sources:
        ref = str(x.get("ref") or "")
        if ref:
            src.append(
                AiSource(
                    ref=ref, title=str(x.get("title") or "")[:80], kind=str(x.get("kind") or "")
                )
            )
    return AiSection(
        title=s.title,
        sentences=[x.text for x in s.sentences],
        caution=s.caution.text if s.caution else "",
        tip=s.tip.text if s.tip else "",
        source=s.source,
        route=s.route,
        trade=s.trade,
        sources=src,
        table=[list(r) for r in s.table],
        steps=s.steps,
    )

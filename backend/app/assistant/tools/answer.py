"""지식 · 질문 답 도구 (계약서 5장): search_knowledge · answer_question.

- search_knowledge: 지식 검색(knowledge.service.search) 근거 조각. 조각 글은 자료 상자로 넘긴다.
- answer_question: 질문 종류(kind)별 설정(ASSISTANT_ANSWER_ROUTE)으로 답 파이프라인 하나를 부른다.
  - v3: chat.service.answer_only를 무료 모드로(겹친 LLM 호출 없이 근거 문장만).
  - v2: v2.ask.answer_only(저장 없이 v2 답 · 서버 도구만). 턴이 LLM이면 v2도 LLM으로 답한다(평가로 고를 자리).
  - v2g: v2.ask.grounds(v2 근거만, LLM 없이): 지식 조각 · 출처, 공정 순서, 공정 설정, 되물을 조건.
    비서가 이 근거로 글을 한 번에 쓴다. 금액 · 기간 질문은 이 공사 계산 엔진 값을 쓰는 v3로 넘긴다(engine v3).
  - v2+v3 · v2g+v3: v2(v2g) 먼저. v2 입구 관문(v2.ask.start와 같은 분류)이 범위 밖으로 보면 v2는 부르지 않고 v3를
    부른다. v3가 실제로 답하면(범위 밖 · 되묻기가 아니고 모름 줄 말고 문장이 있음) v3 근거, 아니면 다른 공정 질문은
    알아 두기만(route know), 그 밖은 v2 범위 밖 안내 그대로.
  - expert · expert+v3: 공정 전문가(assistant/experts, docs/v4/13-trade-experts.md). 코드가 공정을 고르고(질문 낱말 →
    이 공사 공정 → 지식 조각 갈래) 도배 · 목공 전문가(LLM 구조화 답, 둘 다면 함께)가 핵심 답 · 주의점 · 확인할 조건을
    근거 번호와 함께 내면, 코드가 근거 · 숫자를 거른 줄만 넘긴다(route expert). 금액 · 기간 질문은 v3(견주기 · 장단
    질문은 전문가, v3가 범위 밖이 아닌데 빈 답이면 전문가로 이음), 모르는 공정은
    v2g(공정마다 답이 갈리면 되물을 조건 하나를 더함), 무료 모드 · 전문가 실패 · 범위 밖 · 남은 줄 없음은 v2g로 물러선다.
    expert+v3는 v2g+v3처럼 관문이 범위 밖으로 본 질문을 v3 · 알아 두기로 보낸다.
  - 다른 공정(믿집이 계산 · 연결하지 않는 공정)이 걸린 질문은 엔진과 상관없이 notes에 알아 두기(순서 · 주의점 ·
    출처, 숫자 없음)를 더한다(knowledge.service.other_trade_notes). 금액 · 기간 · 업체 연결은 넣지 않는다.
  data의 engine(근거를 낸 엔진) · v2_out(관문이 범위 밖으로 봤는지) · expert(공정 고르기 · 전문가 기록)는 기록용이라
  모델에 가지 않는다(to_model). 비서 모델이 돌려준 글 범위 안에서 답한다. 숫자는 이 결과가 허용 숫자가 된다.
"""

import hashlib
import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from app.assistant import policy
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards, obj, tool
from app.config import settings
from app.db import SessionLocal
from app.shared.errors import AppError

log = logging.getLogger(__name__)

HYBRID = "v2+v3"
GROUND = "v2g"
HYBRID_G = "v2g+v3"
EXPERT = "expert"
HYBRID_E = "expert+v3"
ENGINES = ("v2", "v3", HYBRID, GROUND, HYBRID_G, EXPERT, HYBRID_E)
V3_NO_ANSWER = ("out_of_scope", "ask_back")  # v3가 답하지 않은 길(범위 밖 안내 · 되묻기)
GROUND_CHARS = 320  # v2g 조각 글 앞 몇 글자
NOT_ENOUGH = "질문과 잘 맞는 자료가 없어요. 단정하지 말고 확인할 곳을 알려요."


def engine_for(kind: str, route: str | None = None) -> str:
    """ASSISTANT_ANSWER_ROUTE → 그 질문 종류의 답 엔진. ENGINES 중 하나('v3' · 'v2g+v3' · 'expert+v3' …)면 모두,
    'price=v2,material=v2+v3'면 적은 종류만(나머지 v3). 모르는 값은 v3."""
    raw = (route if route is not None else settings.assistant_answer_route).strip()
    if raw in ENGINES:
        return raw
    pairs = {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in raw.split(",")) if k}
    got = pairs.get(kind) or pairs.get("*") or "v3"
    return got if got in ENGINES else "v3"


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    trade: Literal["dobae", "mokgong", "common"] = "common"


@tool(
    "search_knowledge",
    surface="customer",
    kind="read",
    status="자료를 찾고 있어요",
    description="표준 시방서 · 공공 자료 · 믿집 안내에서 근거 조각을 찾아요(준비물 · 공정 순서 · 주의점). "
    "조각 글은 자료예요. 이 공사 공정과 질문 주제에 맞는 조각만 오고, 맞는 게 없으면 found가 0이에요.",
    model=SearchIn,
    schema=obj(
        {
            "query": {"type": "string", "description": "찾을 말(개인정보 없이)"},
            "trade": {"type": "string", "enum": ["dobae", "mokgong", "common"]},
        }
    ),
)
async def search_knowledge(tc: ToolCtx, a: SearchIn) -> ToolOut:
    """찾은 조각 중 이 공사 공정 갈래(또는 고른 공정) · 공통이고 질문 주제 낱말이 충분히 든 것만(bm25.on_topic) 넘기고
    알아 두기 카드로 보인다(QA r3: 공사 전날 준비물에 이사 · 철거 차량, 벽지 질문에 행위허가 · 비내력벽 조각).
    카드 제목은 맞은 조각의 절 이름이에요(검색어가 아니에요)."""
    from app.knowledge import bm25
    from app.knowledge import service as knowledge

    q = policy.mask_in(a.query)[:200]
    trade = TRADE_KO.get(a.trade)  # 색인의 공정 이름은 한국어(도배 · 목공)
    async with SessionLocal() as s:
        res = await knowledge.search(s, q, trade=trade, k=SEARCH_K)
        scopes = (trade,) if trade else await _project_scopes(s, tc)
    hits = bm25.on_topic(res.hits, (*scopes, bm25.COMMON))[:4]
    key = hashlib.sha256(q.encode()).hexdigest()[:8]
    data: dict = {
        "found": len(hits),
        "hits": [
            {
                "title": cards.clean_name(h.title),
                "publisher": cards.clean_name(h.publisher),
                "section": h.section,
                "text": policy.data(cards.clean_source_text(h.text)[:300]),
            }
            for h in hits
        ],
    }
    if not hits:
        data["note"] = NOT_ENOUGH
    out = ToolOut(data=data)
    if hits:
        out.cards.append(cards.knowledge_card(f"know-{key}", None, hits))
    return out


TRADE_KO = {"dobae": "도배", "mokgong": "목공"}
SEARCH_K = 8  # 주제 거르기 전에 넉넉히 찾는다(넘기는 건 4개까지)


async def _project_scopes(s, tc: ToolCtx) -> tuple[str, ...]:
    """이 공사에 고른 공정(도배 · 목공). 공사가 없거나 못 읽으면 둘 다."""
    from app.project import service as project_service

    if tc.project_id is None:
        return tuple(TRADE_KO.values())
    try:
        p = await project_service.get_for(s, tc.user, tc.project_id)
    except AppError:
        return tuple(TRADE_KO.values())
    got = tuple(ko for code, ko in TRADE_KO.items() if getattr(p.trades, code, None))
    return got or tuple(TRADE_KO.values())


TERMS_MAX, TERM_CHARS = 3, 40


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    kind: Literal["general", "price", "period", "material", "process"] = "general"
    # 자료를 찾을 표준 용어(비서가 고객 말을 시방서 말로 바꾼 것, 예: '도배 전 조명 기구 제거'). 공정 전문가 길이
    # 질문과 함께 검색어로 써요(고객 말과 자료 말이 달라 못 찾던 조각, QA r6 c2 T11)
    terms: list[str] = Field(default_factory=list, max_length=TERMS_MAX)


def kind_of(kind: str, question: str) -> str:
    """모델이 고른 질문 종류 → 답 길을 고를 종류. 금액 · 기간 종류라도 하자 · A/S · 보증 · 환불 질문이면 이 공사
    공정표 · 견적 값이 답이 아니라 general이에요(v3 policy WARRANTY · REFUND와 같은 말. 2026-11-23 도커 'AS기간은 보통
    어떻게돼?'가 period로 와 v3 길에서 타일 글 조각만 받았어요). 견주기 · 장단 질문(COMPARE)도 general이에요."""
    from app.agent.v3.policy import REFUND, WARRANTY

    if kind in ("price", "period") and (
        WARRANTY.search(question)
        or REFUND.search(question)
        or COMPARE.search(question)
        or NEED.search(question)
    ):
        return "general"
    return kind


# 견주기 · 장단 질문(방법 · 자재를 서로 견줌): 돈 · 기간 낱말이 있어도 이 공사 금액 · 공정표가 답이 아니라 전문가 길로
# 가요(QA r7 c2 L27: '문틀 페인트 · 필름 · 교체 비교하면 어때요? 비용 차이도'가 v3 길로 가 '자료로 확인하지 못했어요'만)
COMPARE = re.compile(
    r"비교|견주|견줘|장단|장점|단점|(?<![A-Za-z])vs(?![A-Za-z])|아니면"
    r"|(?:뭐가|무엇이|어느\s*(?:게|것이|거|쪽이?)|어떤\s*(?:게|것이|거))\s*(?:더\s*)?"
    r"(?:나[아을으]|낫|좋|오래|튼튼)",
    re.IGNORECASE,
)
# 꼭 해야 하는지 · 빼도 되는지 · 원인 · 하자 증상을 묻는 말: 금액 · 기간 낱말이 섞여도 공정 지식이 답이라 전문가 길로
# 가요(값은 MONEY_NOTE로 이 공사 계산 값만, QA r8 d1: '초배 꼭 해야 해요? 빼면 얼마?' · '이음매가 몇 달 뒤 벌어지면?' ·
# '겨울에 보일러 켜 둬야 해요?'가 v3 길에서 짧은 '자료 없음'만). '왜 이렇게 비싸요?' 같은 금액 물음은 v3 그대로예요
NEED = re.compile(
    r"꼭\s*해야|(?:해|둬|켜|꺼|놔|떼|빼|바꿔|칠해|발라)야\s*(?:하나|해요|돼요|되나요|할까요|하는지)"
    r"|안\s*하면|빼도\s*(?:돼|되|괜찮)|원인"
    r"|벌어지|들뜨|들떠|갈라지|곰팡이|결로|누수"
)
# 값이 섞인 견주기 · 빈 답 뒤 전문가 답(모델 값 note): 값은 이 공사 계산 값으로만, 믿집이 세지 않는 일은 그렇다고만
MONEY_NOTE = (
    "고객이 값도 물었어요. 이 공사 표준견적서에 있는 일이면 get_standard_quote 값으로 말하고, 표준견적서에 없는 일"
    "(필름 · 도장 · 문틀 교체 같은)은 값을 짐작하지 말고 '그 값은 믿집이 세지 않아요'라고만 말해요."
)


def money_first(question: str) -> bool:
    """이 공사 금액 · 공정표 값이 먼저인 질문인지: v3 정책 표시 price · period이고 견주기 · 장단 질문이 아니에요."""
    from app.agent.v3.policy import policy_of
    from app.v2 import ask

    flags = set(policy_of(ask.clean_message(question)))
    return bool({"price", "period"} & flags) and not (
        COMPARE.search(question) or NEED.search(question)
    )


# 'AS' · 'A/S' · '에이에스'(영어 낱말 안의 as는 아님)
AS_WORD = re.compile(r"A\s?/\s?S|(?<![A-Za-z])AS(?![A-Za-z])|에이에스", re.IGNORECASE)
AS_ASK = "하자 보수(A/S)"


def search_words(question: str) -> str:
    """답 길에 넘길 질문: '하자 · 보수' 없이 'AS'만 쓴 질문은 'AS'를 '하자 보수(A/S)'로 바꿔요. 지식 조각(표준계약서 ·
    건설산업기본법 하자담보 1년)이 '하자 · 보수'로 적혀 있어 'AS'만으로는 잘 안 잡혔어요(2026-11-23 qa10: '도배 시공 AS
    기간은?' 두 번 중 한 번 '자료로 확인되지 않아요', 바꾼 말은 두 번 다 1년)."""
    if "하자" in question or "보수" in question:
        return question
    return AS_WORD.sub(AS_ASK, question, count=1)


@tool(
    "answer_question",
    surface="customer",
    kind="read",
    status="답을 찾고 있어요",
    description="도배 · 목공 일반 질문에 믿집 답 파이프라인으로 근거 문장을 찾아요(검증된 카드 · 자료 발췌). "
    "사실 · 숫자는 돌려준 문장 범위 안에서만 말해요. 앞 대화와 잇는 말 · 이 집 조건에 맞춘 권고 · 끝 질문은 붙여요. "
    "kind price · period는 이 공사 금액 · 공사 기간(공정표)을 물을 때예요. terms에는 자료를 찾을 표준 용어를 "
    "1~3개 넣어요(고객 말을 시방서 · 업계 말로, 예: '떼 놔야 해요' → '조명 기구 제거').",
    model=AskIn,
    schema=obj(
        {
            "question": {"type": "string", "description": "고객 질문(가린 글 그대로)"},
            "kind": {
                "type": "string",
                "enum": ["general", "price", "period", "material", "process"],
            },
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "자료를 찾을 표준 용어 1~3개(개인정보 없이)",
            },
        },
        required=["question", "kind"],
    ),
)
async def answer_question(tc: ToolCtx, a: AskIn) -> ToolOut:
    from app.knowledge import service as knowledge

    question = search_words(policy.mask_in(a.question))
    engine = engine_for(kind_of(a.kind, question))
    know = knowledge.other_trade_notes(question)
    # 공정 전문가 길만 쓰는 검색 용어(None이면 전문가 길이 아님)
    expert = terms_of(a.terms) if engine in (EXPERT, HYBRID_E) else None
    if engine in (HYBRID, HYBRID_G, HYBRID_E):
        out = await _hybrid(
            tc, question, ground=engine != HYBRID, expert=expert, know=know is not None
        )
    elif engine in ("v2", GROUND, EXPERT):
        out = await _v2_or_v3(tc, question, ground=engine != "v2", expert=expert)
    else:
        out, answered = await _v3_answer(tc, question)
        if not answered:  # 빈 답이면 전문가 길로(QA r7 c2 L21)
            out = await _after_empty(tc, question, terms_of(a.terms), out)
    if know is not None:  # 다른 공정 알아 두기(숫자 없음 · 출처)
        out.data["notes"] = know.data()
    return out


def terms_of(raw: list[str]) -> tuple[str, ...]:
    """비서가 준 검색 용어: 가리고 · 한 줄로 · 짧게 · 겹침 없이 TERMS_MAX개."""
    got = (" ".join(policy.mask_in(t).split())[:TERM_CHARS] for t in raw)
    return tuple(dict.fromkeys(t for t in got if t))[:TERMS_MAX]


async def _v3_answer(tc: ToolCtx, question: str) -> tuple[ToolOut, bool]:
    """v3 근거(무료 모드). 둘째 값: 실제로 답했는지(범위 밖 · 되묻기가 아니고, 모름 줄 말고 문장이 있음).
    근거 글은 이름표 · 이끄는 말 · 인용 따옴표를 떼고 같은 안내는 한 번만 넘긴다(길이는 그대로, 모델이 근거로 쓴다)."""
    from app.agent.v3 import brief
    from app.chat import service as chat_service

    ans = await chat_service.answer_only(
        tc.user, question, tc.today, project_id=tc.project_id, mode="free"
    )
    said = [x for sec in ans.answer.sections for x in sec.sentences]
    lines = brief.clean_lines([*said, *ans.answer.unknown], unquote=True)
    sources = list(dict.fromkeys(cards.clean_name(r.title) for r in ans.answer.refs if r.title))[:4]
    out = ToolOut(
        data={
            "route": ans.route,
            "answer": policy.data("\n".join(lines), limit=1200),
            "sources": sources,
            "found": bool(lines),
        }
    )
    return out, bool(said) and ans.route not in V3_NO_ANSWER


async def _v2_or_v3(
    tc: ToolCtx,
    question: str,
    *,
    ground: bool = False,
    expert: tuple[str, ...] | None = None,
) -> ToolOut:
    """v2 답(ground면 v2g 근거, expert(검색 용어 묶음)가 있으면 공정 전문가). v2 길이 오류로 깨지면(공급자 · 임베딩 ·
    검색. QA r3: 빈 OpenAI 키의 OpenAIError로 도구가 실패해 지식 카드 0) v3 근거(무료 모드 · 키워드 검색)로
    물러선다(engine v3 · v2_failed, 기록용). 도구 · 기능 오류(ToolError · AppError)는 그대로 낸다."""
    try:
        if expert is not None:
            out = await _expert_answer(tc, question, expert)
        elif ground:
            out = await _v2g_answer(tc, question)
            out.data["engine"] = out.data.get("engine") or GROUND
        else:
            out = await _v2_answer(tc, question)
            out.data["engine"] = "v2"
        return out
    except (ToolError, AppError):
        raise
    except Exception as e:  # noqa: BLE001 - 종류 이름만 로그(질문 글은 남기지 않음)
        log.warning("지식 답 v2 길 실패, v3로 물러섬 (%s)", type(e).__name__)
    out, _ = await _v3_answer(tc, question)
    out.data.update(engine="v3", v2_failed=True)
    return out


async def _after_empty(
    tc: ToolCtx, question: str, terms: tuple[str, ...], empty: ToolOut
) -> ToolOut:
    """v3(이 공사 계산 값 길)가 범위 밖 · 되묻기가 아닌데 빈 답이면 전문가 길로 이어요(기본 경로에 전문가가 있을 때만,
    QA r7 c2 L21 '초배 꼭 해야 해요? 빼면 얼마?'가 174바이트 빈 답). 전문가 길이 깨지면 v3 빈 답 그대로예요."""
    if empty.data.get("route") in V3_NO_ANSWER or engine_for("general") not in (EXPERT, HYBRID_E):
        return empty
    try:
        out = await _expert_answer(tc, question, terms, money=False)
    except (ToolError, AppError):
        raise
    except Exception as e:  # noqa: BLE001 - 종류 이름만 로그(질문 글은 남기지 않음)
        log.warning("지식 답 v3 빈 답 뒤 전문가 길 실패 (%s)", type(e).__name__)
        return empty
    out.data["v3_empty"] = True  # 기록용(모델에 가지 않아요)
    return out


async def _hybrid(
    tc: ToolCtx,
    question: str,
    *,
    ground: bool = False,
    expert: tuple[str, ...] | None = None,
    know: bool = False,
) -> ToolOut:
    """v2+v3(ground면 v2g+v3, expert면 expert+v3): v2 입구 관문이 범위 밖으로 보고 v3가 실제로 답하면 v3 근거, 아니면
    v2(v2g · 전문가) 그대로. v3도 답하지 못한 범위 밖 질문은 다른 공정이 걸렸으면(know) 범위 밖 안내 대신 알아 두기만
    남긴다(route know). v2 범위 밖 질문(다른 공정)은 v3 알아 두기가 나았고, 잡담은 v2 거절이 나았다(평가 2026-11-21).
    v2(v2g · 전문가) 길이 깨지면 v3로 물러선다(_v2_or_v3)."""
    from app.agent import gate as agent_gate
    from app.v2 import ask

    # v2.ask.start와 같은 관문(학습 모델 · 규칙, Jev는 켜졌을 때 신뢰도가 낮으면만)
    intent = await agent_gate.classify(question)
    v2_out = intent is not None and intent.label == "out_of_scope"
    if not v2_out:
        out = await _v2_or_v3(tc, question, ground=ground, expert=expert)
        out.data["v2_out"] = False
        return out
    out, answered = await _v3_answer(tc, question)
    engine = "v3"
    if not answered and know:  # 다른 공정: 알아 두기(notes)는 answer_question이 붙여요
        out, engine = ToolOut(data={"route": "know", "found": True}), "know"
    elif not answered:  # v2가 범위 밖에서 내는 안내 그대로(ask.start와 같은 글)
        out = ToolOut(
            data={
                "route": "out_of_scope",
                "answer": policy.data(ask.OUT_TEXT),
                "sources": [],
                "found": True,
            }
        )
        engine = "v2"
    out.data.update(engine=engine, v2_out=v2_out)
    return out


async def _v2g_answer(tc: ToolCtx, question: str) -> ToolOut:
    """v2 근거만(LLM 없이, v2.ask.grounds). 비서가 이 근거로 글을 한 번에 쓴다.
    금액 · 기간 질문은 v2 평형 금액 대신 이 공사 계산 엔진 값(표준견적서 · 공정표)을 쓰는 v3로 넘긴다(engine v3).
    조각 글 · 제목 앞 이름표('[생활법령정보 요약]' · '[초급]')와 안쪽 메모 · 파일 이름 줄은 뗀다(모델이 답에 옮기지
    않게, cards.clean_source_text · clean_name)."""
    from app.v2 import ask

    living = ""
    if tc.project_id is not None:
        async with SessionLocal() as s:
            _, home = await cards.home(s, tc.user, tc.project_id)
        living = "살면서 공사" if home.get("occupied") else "빈 집"
    g = await ask.grounds(question, living=living, mode=tc.mode)
    if g.money:
        out, _ = await _v3_answer(tc, question)
        out.data["engine"] = "v3"
        return out
    named = (
        ("공정 순서(앞에서부터, 믿집 안내)", g.order),
        (f"{g.trade or '공정'} 주의점", g.cautions),
        ("실측 때 정할 것", g.survey),
        ("고객 준비", g.prep),
        ("되물을 조건(답이 갈리는데 모르면 하나만)", g.ask),
    )
    found = g.enough and bool(g.hits)
    data: dict = {
        "route": GROUND,
        "hits": [
            {
                "title": cards.clean_name(h.title),
                "publisher": h.publisher,
                "section": h.section,
                "source": h.source_type,
                "text": policy.data(cards.clean_source_text(h.text), limit=GROUND_CHARS),
            }
            for h in g.hits
        ],
        "items": [{"label": label, "lines": lines} for label, lines in named if lines],
        "found": found,
        "engine": GROUND,
    }
    if not found:
        data["note"] = NOT_ENOUGH
    return ToolOut(data=data)


# ---- 공정 전문가(expert, docs/v4/13-trade-experts.md) ----
ORDER_LABEL = "공정 순서(앞에서부터, 믿집 안내)"
ASK_LABEL = "확인할 조건(답이 갈리면 이것 하나만 물어요)"
SPLIT_LABEL = "되물을 조건(공정마다 답이 갈려요, 하나만)"
CALC_NOTE = "금액 · 수량 · 기간은 이 공사 표준견적서 · 공정표 값으로만 말해요."
# 믿집이 잇지 않는 공정(목공)의 시공이 필요한 답: 연결 범위(고정 선 8)와 다음 걸음 하나(QA r6 c2 L2 '목공 업체에
# 보여 주세요'만 하고 막다른 길). 비서가 대화에서 한 번 말해요(고객 지시문 '도배 밖 일'과 같은 걸음)
CONNECT_LABEL = "믿집 연결 범위(대화에서 한 번만 말해요)"
CONNECT_NEXT = "도배와 맞물리는 손보기는 실측 때 도배 업체에 같이 할 수 있는지 물어볼 수 있어요."
CONNECTED = frozenset({"도배"})  # 믿집이 업체를 잇는 공정(policy.DOBAE_ONLY)
EXPERT_SOURCES = 5  # 넘기는 출처 이름 수
REST_PIECES = 4  # 전문가가 실패한 공정에서 대신 넘기는 조각 수
# 공정 순서 줄을 붙일 물음(전문가 길). v3 ORDER_ASK는 '전에 · 뒤에 · 같이'까지 넓어 '도배 전에 뭘 해요?'에도 열두 줄
# 순서를 붙였어요(QA r6 c2 파일럿). 둘 다 고른 질문은 늘 붙여요
ORDER_WORDS = re.compile(r"순서|뭐부터|무엇부터|어느\s*(?:것|거|걸|쪽)\s*부터|먼저|나중")


async def _expert_answer(
    tc: ToolCtx, question: str, terms: tuple[str, ...] = (), *, money: bool = True
) -> ToolOut:
    """공정 전문가: 공정 고르기(코드) → 도배 · 목공 전문가(LLM 구조화 답, 둘 다면 함께) → 비서가 받아 한 번에 써요.
    금액 · 기간 질문은 v2g처럼 v3(이 공사 계산 엔진 값)가 먼저예요(money, 견주기 · 장단 질문은 아님). v3가 범위 밖 ·
    되묻기가 아닌데 빈 답이면 전문가로 이어요(QA r7 c2 L21). 고른 공정이 없으면(모름 · 다른 공정 · 갈림) v2g 근거로,
    갈림이면 어느 공정인지 되물을 조건 하나를 더해요. 무료 모드 · 전문가 실패 · 범위 밖 · 남은 줄 없음도 v2g로
    물러서요(가짜 설명 없음). 값을 같이 물었으면 값은 이 공사 계산 값으로만 말하라는 note를 붙여요(MONEY_NOTE).
    expert 칸(기록, 모델에 안 감): 고른 길 · 전문가마다 줄 수 · 근거 · 버린 까닭 · 시간."""
    from app.agent.v3.policy import policy_of
    from app.assistant.experts import agent as experts
    from app.assistant.experts import pick as picking
    from app.knowledge import service as knowledge
    from app.v2 import ask

    if money and money_first(question):
        out, answered = await _v3_answer(tc, question)
        if answered or out.data.get("route") in V3_NO_ANSWER:
            out.data["engine"] = "v3"
            return out
    t0 = time.monotonic()
    home = await experts.home_of(tc.user, tc.project_id)
    other = knowledge.other_trade_notes(question) is not None
    got = picking.pick(question, home.trades, other=other)
    if got.why == "unknown":
        got = await experts.pick_unknown(question, terms)
    record: dict = {"pick": got.why, "trades": list(got.trades), "used": GROUND}
    notes: list = []
    if not got.trades:
        record["why_v2g"] = "no_trade"
    elif tc.mode == "free":
        record["why_v2g"] = "free"
    else:
        try:
            notes = await experts.consult(got.trades, question, home, terms)
        except (ToolError, AppError):
            raise
        except Exception as e:  # noqa: BLE001 - 종류 이름만 로그(질문 글은 남기지 않음)
            log.warning("공정 전문가 길 실패, v2g로 물러섬 (%s)", type(e).__name__)
            record["why_v2g"] = f"error:{type(e).__name__}"
        record["notes"] = [n.record() for n in notes]
    ok = [n for n in notes if n.ok]
    if notes and not ok:
        # 모두 실패 · 범위 밖 · 남은 줄 없음(까닭은 notes의 failed · out · lines)
        record["why_v2g"] = "experts"
    if not ok:
        out = await _v2g_answer(tc, question)
        if got.why == "split":
            out.data.setdefault("items", []).append(
                {"label": SPLIT_LABEL, "lines": [picking.SPLIT_ASK]}
            )
        record["ms"] = int((time.monotonic() - t0) * 1000)
        out.data.update(engine=out.data.get("engine") or GROUND, expert=record)
        return out
    order = len(got.trades) > 1 or bool(ORDER_WORDS.search(question))
    record.update(used=EXPERT, ms=int((time.monotonic() - t0) * 1000))
    data = expert_data(ok, notes, order=order)
    # 값이 섞인 견주기 · 빈 답 뒤(QA r7 c2 L27): 값은 이 공사 계산 값으로만
    if "price" in policy_of(ask.clean_message(question)):
        data["note"] = " ".join(x for x in (data.get("note"), MONEY_NOTE) if x)
    out = ToolOut(data={**data, "engine": EXPERT, "expert": record})
    if (card := expert_card(ok)) is not None:  # 근거 조각 · 출처 이름을 화면에(QA r7 c1 · c2)
        out.cards.append(card)
        out.data["note"] = " ".join(x for x in (out.data.get("note"), CARD_NOTE) if x)
    return out


CARD_NOTE = "근거 조각과 출처 이름은 알아 두기 카드로 같이 보였어요. 글로 다시 늘어놓지 말아요."
# 전문가 답의 확인할 조건 → 끝 물음 한 문장. 비서 답에 묻는 말 · 다음 걸음이 없으면 런타임이 지금 할 일 줄 대신 붙여요
# (QA r7 c1 6 · 10 · 13 · 25턴: 전문가 길 답이 확인할 조건 없이 끝남). 전문가는 '…인지' 꼴로 내요(지시문 예 '지금 벽에
# 곰팡이 · 결로 자국이 있는지')
ASK_TAIL = "{ask} 알려 주시겠어요?"
HANGUL = re.compile(r"[가-힣]")


def ask_tail(data: dict) -> str | None:
    """answer_question 결과 값 → 끝 물음 한 문장. 전문가 길이고 확인할 조건이 '…지'로 끝날 때만, 아니면 None."""
    if data.get("route") != EXPERT:
        return None
    item = next((x for x in data.get("items") or [] if x.get("label") == ASK_LABEL), None)
    first = ((item or {}).get("lines") or [None])[0]
    text = first.get(policy.DATA_KEY, "") if isinstance(first, dict) else ""
    text = " ".join(str(text).split()).rstrip(" .?")
    if not text.endswith("지") or not HANGUL.search(text):
        return None
    return ASK_TAIL.format(ask=text)


def expert_card(ok: list):
    """전문가 답이 기댄 자료 조각(근거 번호 차례, 셋까지) → 알아 두기 카드(발췌 · 출처 이름, search_knowledge와 같은
    꼴). 전문 지식(G)만 기댄 답은 카드가 없어요(QA r7 c1 6 · 10 · 13 · 25턴 · c2 18문항 중 12: 출처가 화면에 없음)."""
    cited = list(
        dict.fromkeys(
            n.pieces[r]
            for n in ok
            for x in (*n.answer, *n.cautions)
            for r in x.refs
            if r in n.pieces
        )
    )
    if not cited:
        return None
    key = hashlib.sha256(" ".join(p.ref for p in cited).encode()).hexdigest()[:8]
    return cards.knowledge_card(f"know-{key}", None, cited)


def expert_data(ok: list, notes: list, *, order: bool) -> dict:
    """전문가 메모 → 모델에 갈 값(policy.ALLOWED 칸만): 공정마다 핵심 답 · 주의점(줄 글은 자료 상자, 근거 이름),
    둘 다거나 순서를 물으면 공정 순서, 확인할 조건 하나, 믿집이 잇지 않는 공정의 시공이 필요하면 연결 범위와 다음
    걸음 하나, 출처, 계산 엔진 안내. 전문가가 실패한 공정이 있으면 찾아 둔 조각을 v2g처럼 hits로 넘겨요."""
    from app.v2 import ask

    def lines(n, xs) -> list[dict]:
        return [{"text": policy.data(x.text), "source": n.source_of(x)} for x in xs]

    items: list[dict] = []
    for n in ok:
        items.append({"label": f"{n.trade} 전문가 답", "lines": lines(n, n.answer)})
        if n.cautions:
            items.append({"label": f"{n.trade} 주의점(이 집)", "lines": lines(n, n.cautions)})
    if order:
        items.append({"label": ORDER_LABEL, "lines": [f"{a}: {b}" for a, b in ask.GUIDE]})
    if want := next((n.ask for n in ok if n.ask), ""):
        items.append({"label": ASK_LABEL, "lines": [policy.data(want)]})
    if any(n.needs_vendor and n.trade not in CONNECTED for n in ok):
        items.append({"label": CONNECT_LABEL, "lines": [policy.DOBAE_ONLY, CONNECT_NEXT]})
    data: dict = {
        "route": EXPERT,
        "trades": [n.trade for n in ok],
        "found": True,
        "items": items,
        "sources": list(dict.fromkeys(s for n in ok for s in n.sources()))[:EXPERT_SOURCES],
    }
    rest = [
        p for n in notes if not n.ok and not n.out for p in list(n.pieces.values())[:REST_PIECES]
    ]
    if rest:
        data["hits"] = [
            {
                "title": p.title,
                "section": p.section,
                "source": p.kind,
                "text": policy.data(p.text, limit=GROUND_CHARS),
            }
            for p in rest
        ]
    if any(n.needs_calc for n in ok):
        data["note"] = CALC_NOTE
    return data


async def _v2_answer(tc: ToolCtx, question: str) -> ToolOut:
    """v2 답(저장 없음). 집 사실(평 · 지역 · 사는 중)은 세션이 정한 공사에서 코드가 읽어 넘긴다."""
    from app.v2 import ask

    pyeong, region, living = None, "", ""
    if tc.project_id is not None:
        async with SessionLocal() as s:
            _, home = await cards.home(s, tc.user, tc.project_id)
        pyeong, region = home.get("pyeong"), home.get("region") or ""
        living = "살면서 공사" if home.get("occupied") else "빈 집"
    out = await ask.answer_only(
        str(tc.user.id),
        question,
        tc.today,
        pyeong=pyeong,
        region=region,
        living=living,
        mode=tc.mode,
    )
    text = "" if out.failed else out.text  # 무료 모드 · 답 실패면 근거 제목만 남는다
    return ToolOut(
        data={
            "route": "v2",
            "answer": policy.data(text, limit=1200),
            "sources": list(
                dict.fromkeys(cards.clean_name(x.title) for x in out.sources if x.title)
            )[:4],
            "found": bool(text),
        }
    )

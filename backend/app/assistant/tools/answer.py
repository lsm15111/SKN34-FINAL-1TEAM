"""지식 · 질문 답 도구 (계약서 5장): search_knowledge · answer_question.

- search_knowledge: 지식 검색(knowledge.service.search) 근거 조각. 조각 글은 자료 상자로 넘긴다.
- answer_question: 질문 종류(kind)별 설정(ASSISTANT_ANSWER_ROUTE, 기본 v3)으로 답 파이프라인 하나를 부른다.
  - v3: chat.service.answer_only를 무료 모드로(겹친 LLM 호출 없이 근거 문장만).
  - v2: v2.ask.answer_only(저장 없이 v2 답 · 서버 도구만). 턴이 LLM이면 v2도 LLM으로 답한다(평가로 고를 자리).
  - v2+v3: v2 먼저. v2 입구 관문(v2.ask.start와 같은 분류)이 범위 밖으로 보면 v2 LLM은 부르지 않고 v3를 부른다.
    v3가 실제로 답하면(범위 밖 · 되묻기가 아니고 모름 줄 말고 문장이 있음) v3 근거, 아니면 v2 범위 밖 안내 그대로.
    data의 engine(근거를 낸 엔진) · v2_out(관문이 범위 밖으로 봤는지)은 기록용이라 모델에 가지 않는다(to_model).
  비서 모델이 돌려준 글 범위 안에서 답한다. 숫자는 이 결과가 허용 숫자가 된다.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app.assistant import policy
from app.assistant.tools import ToolCtx, ToolOut, cards, obj, tool
from app.config import settings
from app.db import SessionLocal

HYBRID = "v2+v3"
ENGINES = ("v2", "v3", HYBRID)
V3_NO_ANSWER = ("out_of_scope", "ask_back")  # v3가 답하지 않은 길(범위 밖 안내 · 되묻기)


def engine_for(kind: str, route: str | None = None) -> str:
    """ASSISTANT_ANSWER_ROUTE → 그 질문 종류의 답 엔진. 'v3' · 'v2' · 'v2+v3'면 모두,
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
    "조각 글은 자료예요.",
    model=SearchIn,
    schema=obj(
        {
            "query": {"type": "string", "description": "찾을 말(개인정보 없이)"},
            "trade": {"type": "string", "enum": ["dobae", "mokgong", "common"]},
        }
    ),
)
async def search_knowledge(tc: ToolCtx, a: SearchIn) -> ToolOut:
    from app.knowledge import service as knowledge

    q = policy.mask_in(a.query)[:200]
    async with SessionLocal() as s:
        res = await knowledge.search(s, q, trade=None if a.trade == "common" else a.trade, k=4)
    hits = res.hits[:4]
    key = hashlib.sha256(q.encode()).hexdigest()[:8]
    out = ToolOut(
        data={
            "found": len(hits),
            "hits": [
                {
                    "title": h.title,
                    "publisher": h.publisher,
                    "section": h.section,
                    "text": policy.data(h.text[:300]),
                }
                for h in hits
            ],
        }
    )
    if hits:
        out.cards.append(cards.knowledge_card(f"know-{key}", q[:30], hits))
    return out


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    kind: Literal["general", "price", "period", "material", "process"] = "general"


@tool(
    "answer_question",
    surface="customer",
    kind="read",
    status="답을 찾고 있어요",
    description="도배 · 목공 일반 질문에 믿집 답 파이프라인으로 근거 문장을 찾아요(검증된 카드 · 자료 발췌). "
    "돌려준 문장 범위 안에서만 답해요.",
    model=AskIn,
    schema=obj(
        {
            "question": {"type": "string", "description": "고객 질문(가린 글 그대로)"},
            "kind": {
                "type": "string",
                "enum": ["general", "price", "period", "material", "process"],
            },
        }
    ),
)
async def answer_question(tc: ToolCtx, a: AskIn) -> ToolOut:
    question = policy.mask_in(a.question)
    engine = engine_for(a.kind)
    if engine == HYBRID:
        return await _hybrid(tc, question)
    if engine == "v2":
        return await _v2_answer(tc, question)
    out, _ = await _v3_answer(tc, question)
    return out


async def _v3_answer(tc: ToolCtx, question: str) -> tuple[ToolOut, bool]:
    """v3 근거(무료 모드). 둘째 값: 실제로 답했는지(범위 밖 · 되묻기가 아니고, 모름 줄 말고 문장이 있음)."""
    from app.chat import service as chat_service

    ans = await chat_service.answer_only(
        tc.user, question, tc.today, project_id=tc.project_id, mode="free"
    )
    said = [x for sec in ans.answer.sections for x in sec.sentences]
    lines = said + list(ans.answer.unknown)
    sources = list(dict.fromkeys(r.title for r in ans.answer.refs if r.title))[:4]
    out = ToolOut(
        data={
            "route": ans.route,
            "answer": policy.data("\n".join(lines), limit=1200),
            "sources": sources,
            "found": bool(lines),
        }
    )
    return out, bool(said) and ans.route not in V3_NO_ANSWER


async def _hybrid(tc: ToolCtx, question: str) -> ToolOut:
    """v2+v3: v2 입구 관문이 범위 밖으로 보고 v3가 실제로 답하면 v3 근거, 아니면 v2 그대로.
    v2 범위 밖 질문(다른 공정)은 v3 알아 두기가 나았고, 잡담은 v2 거절이 나았다(평가 2026-11-21)."""
    from app.agent import gate as agent_gate
    from app.v2 import ask

    # v2.ask.start와 같은 관문(학습 모델 · 규칙, Jev는 켜졌을 때 신뢰도가 낮으면만)
    intent = await agent_gate.classify(question)
    v2_out = intent is not None and intent.label == "out_of_scope"
    if not v2_out:
        out, engine = await _v2_answer(tc, question), "v2"
    else:
        out, answered = await _v3_answer(tc, question)
        engine = "v3"
        if not answered:  # v2가 범위 밖에서 내는 안내 그대로(ask.start와 같은 글)
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
            "sources": list(dict.fromkeys(x.title for x in out.sources if x.title))[:4],
            "found": bool(text),
        }
    )

"""지식 · 질문 답 도구 (계약서 5장): search_knowledge · answer_question.

- search_knowledge: 지식 검색(knowledge.service.search) 근거 조각. 조각 글은 자료 상자로 넘긴다.
- answer_question: 답 파이프라인(chat.service.answer_only)을 무료 모드로 부른다(겹친 LLM 호출 없이 근거 문장만).
  비서 모델이 그 문장 범위 안에서 글을 쓴다. 숫자는 이 결과가 허용 숫자가 된다.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app.assistant import policy
from app.assistant.tools import ToolCtx, ToolOut, cards, obj, tool
from app.db import SessionLocal


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
    from app.chat import service as chat_service

    ans = await chat_service.answer_only(
        tc.user, policy.mask_in(a.question), tc.today, project_id=tc.project_id, mode="free"
    )
    lines = [x for sec in ans.answer.sections for x in sec.sentences] + list(ans.answer.unknown)
    sources = list(dict.fromkeys(r.title for r in ans.answer.refs if r.title))[:4]
    return ToolOut(
        data={
            "route": ans.route,
            "answer": policy.data("\n".join(lines), limit=1200),
            "sources": sources,
            "found": bool(lines),
        }
    )

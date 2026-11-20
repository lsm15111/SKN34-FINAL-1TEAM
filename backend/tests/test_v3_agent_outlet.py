"""범위 밖 '어떻게' 카드(agent-context.md 4.2): 방법 표 · 업체에 물을 말 표(복사) · '알아 두기' 제목.
무료 모드와 작성기 스텁만 써서 유료 호출 0회."""

import asyncio
import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3.composer import CItem, Composed
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn
from app.knowledge.cards import CardVendorAsk

Q = "콘센트 위치는 어떻게 옮겨? 업체에 물어볼 거 뭐 있어?"


def turn(q: str, mode: str = "free"):
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 20), mode=mode)  # type: ignore[arg-type]
    return asyncio.run(run_turn(q, ctx, kb=repo_kb()))


def by_title(a) -> dict:
    return {s.title: s for s in a.sections}


def test_outlet_how_and_ask_question_gets_methods_and_copyable_ask_table():
    a = turn(Q).answer
    secs = by_title(a)
    assert a.trace.cards == ["card:electric.method.outlet-move@1"]
    assert "[전기 · 알아 두기]" in secs  # 믿집이 견적을 내지 않는 공종은 '알아 두기'
    assert len(secs["[방법]"].table) >= 2 and not secs["[방법]"].copyable
    ask = secs["[업체에 물을 말]"]
    assert ask.copyable and len(ask.table) >= 3 and all(r[0].endswith("?") for r in ask.table)
    # 모름 줄도, 전기 질문에 딴말인 '기본 정보 넣기 · 표준견적서 보기'도 붙지 않아요
    assert not a.unknown and not [c for c in a.cards if c.kind == "next_step"]
    plain = a.plain()  # 이어 보기에 남는 글에도 표 줄이 들어가요
    assert "업체가 쓰는 방법은 이래요." in plain and "· 전선은 CD관으로 감싸 주나요?" in plain


def test_how_only_question_shows_methods_and_offers_the_ask_question():
    a = turn("콘센트를 새로 더 달 수 있어요?").answer
    secs = by_title(a)
    assert "[방법]" in secs and "[업체에 물을 말]" not in secs
    assert a.suggest[0] == "콘센트 옮길 때 업체에 뭘 물어봐요?"  # 누르면 물을 말 표가 나와요


def test_composer_answer_keeps_card_tables_below(monkeypatch):
    monkeypatch.setattr(llm, "_stubs", {})
    free = turn(Q).answer
    k = next(c for s in free.sections for x in s.sentences for c in x.cites if c.startswith("K"))
    lead = CItem(
        text="콘센트 신설과 이설은 가전 필요 용량을 확인하고 전기 공사 때 해요.", cites=[k]
    )
    llm.set_stub("composer", Composed(verdict="answer", lead=lead, blocks=[], follow=[]))
    a = turn(Q, "llm").answer
    assert a.trace.prompts == ["composer_v7"]
    assert [s.title for s in a.sections][-2:] == [
        "[방법]",
        "[업체에 물을 말]",
    ]  # 작성기 답 아래에 그대로


def test_card_rows_need_chunk_refs():
    with pytest.raises(ValidationError):
        CardVendorAsk(q="전선은 어디로 지나가나요?", why="배선 경로를 봐요", cites=["없는번호"])

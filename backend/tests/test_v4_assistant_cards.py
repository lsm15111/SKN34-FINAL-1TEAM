"""v4 비서 카드 값 · 무료 모드 답: 견적서 받은 날은 서울 날짜 · 업체 이름을 공종 낱말로 읽지 않음 · 공사 날짜 카드의
제안 이름표와 [이 날짜로 수락] · 기억을 어디서 보고 지우는지 정해 둔 안내 · 실측 반나절 후보마다 다른 사실 이유 ·
업체 견적서 체크리스트 줄 이름(고객 화면과 같은 말) · 공사 단계에 맞는 칩. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import uuid
from datetime import datetime, time

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.shared.clock import SEOUL, today_seoul
from tests.conftest import query
from tests.test_deal import setup as deal_setup
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_free import cards_of
from tests.test_v4_assistant_turns import ask, ok


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def proposed(ev) -> list[dict]:
    return [a for a in acts(ev) if a["status"] == "proposed"]


# ---- 견적서 받은 날 ----


def test_compare_received_on_is_the_seoul_day(api):
    """서울 08:44에 보낸 견적서는 UTC로는 전날이에요. 카드의 받은 날은 서울 날짜예요."""
    _token, pid, va, _vb, _ = deal_setup(api)
    sent = datetime.combine(today_seoul(), time(8, 44), SEOUL)
    query("update vendor_quotes set sent_at = $1 where visit_id = $2", sent, uuid.UUID(va))
    ev = ok(ask(api, pid, "견적서 비교해 줘"))
    (card,) = cards_of(ev, "quote_compare")
    col = next(c for c in card["data"]["cols"] if c["visit_id"] == va)
    assert col["received_on"] == today_seoul().isoformat()

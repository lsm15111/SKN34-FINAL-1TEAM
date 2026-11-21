"""v4 비서 카드 값 · 무료 모드 답: 견적서 받은 날은 서울 날짜 · 업체 이름을 공종 낱말로 읽지 않음 · 공사 날짜 카드의
제안 이름표와 [이 날짜로 수락] · 기억을 어디서 보고 지우는지 정해 둔 안내 · 실측 반나절 후보마다 다른 사실 이유 ·
업체 견적서 체크리스트 줄 이름(고객 화면과 같은 말) · 공사 단계에 맞는 칩. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import uuid
from datetime import datetime, time

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from app.shared.clock import SEOUL, today_seoul
from tests.conftest import query
from tests.test_deal import setup as deal_setup
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_free import cards_of, said
from tests.test_v4_assistant_turns import ask, home, ok


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


# ---- 업체 이름은 공종 낱말이 아니에요 ----


def test_vendor_name_is_not_read_as_a_trade(api):
    """'마루와벽으로 확정할게요'의 '마루'는 바닥 공사가 아니라 업체 이름이에요."""
    _token, pid, _va, _vb, _ = deal_setup(api)
    ev = ok(ask(api, pid, "마루와벽으로 확정할게요"))
    assert "아직 도배 업체만" not in said(ev)
    assert cards_of(ev, "quote_compare") and said(ev).startswith("실측 견적서가 2곳 왔어요")
    # 업체 이름이 아닌 다른 공사 말은 그대로 '아직 도배 업체만'
    ev = ok(ask(api, pid, "바닥 업체 추천해 줘"))
    assert said(ev).startswith(free.OTHER_TRADE)


# ---- 기억은 어디서 보고 지워요 ----


def test_where_to_see_and_forget_memory_is_a_fixed_guide(api):
    _, pid = home(api)
    for text in ("기억한 건 어디서 보고 지워요?", "비서가 기억한 거 지우고 싶어요"):
        got = said(ok(ask(api, pid, text)))
        assert "내 정보" in got and "비서가 기억한 것" in got, got
        assert "확인하지 못했어요" not in got
    # 기억해 달라는 말은 안내가 아니다
    assert "내 정보" not in said(ok(ask(api, pid, "평일 오전이 편한 거 기억해 줘")))

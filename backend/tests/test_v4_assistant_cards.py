"""v4 비서 카드 값 · 무료 모드 답: 견적서 받은 날은 서울 날짜 · 업체 이름을 공종 낱말로 읽지 않음 · 공사 날짜 카드의
제안 이름표와 [이 날짜로 수락] · 기억을 어디서 보고 지우는지 정해 둔 안내 · 실측 반나절 후보마다 다른 사실 이유 ·
업체 견적서 체크리스트 줄 이름(고객 화면과 같은 말) · 공사 단계에 맞는 칩. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import re
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from app.calc import slots
from app.shared.clock import SEOUL, today_seoul
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose
from tests.test_dates import ready as dates_ready
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import offered
from tests.test_v4_assistant_actions import acts, approve
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


# ---- 공사 날짜 카드 제안 이름표 · 수락 단추 ----


def test_schedule_card_has_proposal_ref_and_accept_choice(api):
    customer_token, pid, did, _ = dates_ready(api)
    start, end = days(10)
    assert propose(api, did, start, end).status_code == 200
    use(api, customer_token)
    ev = ok(ask(api, pid, "공사 날짜 보여 줘"))
    (card,) = cards_of(ev, "schedule")
    d = card["data"]
    assert d["phase"] == "dates" and d["proposal_kind"] == "dates_accept"
    assert re.fullmatch(r"p\d+", d["proposal_ref"])
    choice = f"{d['proposal_kind']}:{d['proposal_ref']}"
    ev = ok(
        ask(
            api, pid, "이 날짜로 수락할래요", context={"card_id": card["card_id"], "choice": choice}
        )
    )
    (a,) = proposed(ev)
    assert a["kind"] == "dates_accept"
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    assert query("select status from deals")[0]["status"] == "scheduled"
    # 확정 공정표 카드는 수락할 날짜가 없어 이름표도 없다
    ev = ok(ask(api, pid, "공사 날짜 보여 줘"))
    (card,) = cards_of(ev, "schedule")
    assert card["data"]["phase"] == "final"
    assert card["data"]["proposal_ref"] is None and card["data"]["proposal_kind"] is None


# ---- 기억은 어디서 보고 지워요 ----


def test_where_to_see_and_forget_memory_is_a_fixed_guide(api):
    _, pid = home(api)
    for text in ("기억한 건 어디서 보고 지워요?", "비서가 기억한 거 지우고 싶어요"):
        got = said(ok(ask(api, pid, text)))
        assert "내 정보" in got and "비서가 기억한 것" in got, got
        assert "확인하지 못했어요" not in got
    # 기억해 달라는 말은 안내가 아니다
    assert "내 정보" not in said(ok(ask(api, pid, "평일 오전이 편한 거 기억해 줘")))


# ---- 실측 반나절 후보 이유 ----


def test_slot_reasons_are_facts_of_each_candidate():
    today = date(2026, 12, 1)  # 화
    open_days = [slots.DayOpen(today + timedelta(days=n), 1, 1) for n in range(1, 8)]  # 12.2 ~ 12.8
    got = slots.candidates(open_days, None, today)
    assert [c.day for c in got] == [date(2026, 12, 2), date(2026, 12, 3), date(2026, 12, 4)]
    assert "earliest" in got[0].why and all("earliest" not in c.why for c in got[1:])
    for c in got:
        weekend = c.day.weekday() >= 5
        assert ("weekend" in c.why) == weekend and ("weekday" in c.why) == (not weekend)
    # 공사 시작 − 20일(12.5 토)에 가장 가까운 한 곳만 그 이유를 단다
    got = slots.candidates(open_days, date(2026, 12, 25), today)
    assert got[0].day == date(2026, 12, 5) and "start_minus_20" in got[0].why
    assert sum("start_minus_20" in c.why for c in got) == 1
    assert sum("earliest" in c.why for c in got) <= 1
    # 기억한 편한 반나절 · 요일이 맞으면 그 이유(요일이 말한 것과 맞으면 평일 · 주말을 따로 달지 않는다)
    got = slots.candidates(open_days, None, today, prefer="pm", day_prefer="weekend")
    assert got[0].day.weekday() >= 5 and {"prefer_half", "prefer_day"} <= set(got[0].why)
    assert "weekend" not in got[0].why


def test_slot_card_reasons_are_words_and_differ(api):
    f = offered(api)
    ev = ok(ask(api, f["pid"], "실측은 언제 할 수 있어요?"))
    (card,) = cards_of(ev, "visit_slots")
    whys = [c["why"] for c in card["data"]["candidates"]]
    assert len(whys) == 3 and all(whys)
    flat = [w for ws in whys for w in ws]
    assert all(re.search("[가-힣]", w) for w in flat), flat  # 코드가 아니라 화면 말
    assert flat.count("가장 빠른 날이에요") <= 1
    assert len({tuple(w) for w in whys}) > 1

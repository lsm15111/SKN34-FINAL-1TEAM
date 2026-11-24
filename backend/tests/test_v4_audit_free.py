"""점검 고침 X1 무료 모드 낱말(보고 R1b #3~#7 · #18~#20). 행동 낱말(미루기 · 취소 · 못 받아요 · 카드 의도)을 부정하거나
묻는 말이면 승인 카드를 만들거나 거두지 않고 되묻는 한 줄(free.doubt), 조사 '이 주' · 없는 날짜 · '토요일은 안 돼요' ·
'철거 포함이에요?'. 고객 · 업체가 분명히 바라는 말('2주 미뤄 주세요' · '취소해 줘' · '못 받아요')은 그대로 카드를
만든다. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import json
from datetime import date, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from app.calc.schedule import workdays
from app.refprice.holidays import days_off
from app.shared.clock import today_seoul
from tests.conftest import query
from tests.test_v3_visit_kit import offered, requested
from tests.test_v4_assistant_actions import action_row, acts
from tests.test_v4_assistant_free import vendor_turn
from tests.test_v4_assistant_free_qa import turn, two_quotes, two_vendors
from tests.test_v4_assistant_offers import scheduled
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_copy_style import sl
from tests.test_visit_inbox import login

TODAY = today_seoul()
VENDOR = dict(free.VENDOR)
CUSTOMER = dict(free.CUSTOMER)


@pytest.fixture(autouse=True)
def free_mode(monkeypatch):
    from app.assistant import service
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(service, "TURNS_PER_HOUR", 100_000)
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def proposed(ev, kind: str | None = None) -> list[dict]:
    return [x for x in acts(ev) if x["status"] == "proposed" and kind in (None, x["kind"])]


def said(ev) -> str:
    return [d for e, d, _ in ev if e == "card" and d["kind"] == "answer"][-1]["data"]["text"]


def status(a: dict) -> str:
    return action_row(a["action_id"])["status"]


# ---- 낱말 거르기(DB 없음) ----


@pytest.mark.parametrize(
    ("rx", "text", "want"),
    [
        # 날짜 바꾸기: 바라는 말은 그대로(앞 문장의 부정 · 부탁하는 물음 포함)
        (free.CHANGE, "공사를 2주 미루고 싶어요", None),
        (free.CHANGE, "이사 날짜가 안 맞아서 공사 2주 미뤄 주세요", None),
        (free.CHANGE, "공사 미뤄 주세요, 그날은 안 돼요", None),
        (free.CHANGE, "공사 2주 미뤄 주실 수 있어요?", None),
        (free.CHANGE, "12월 10일부터로 당겨 주세요", None),
        (free.CHANGE, "꼭 미뤄야 해요", None),
        (free.CHANGE, "공사 미루고 싶지 않아요", "not"),
        (free.CHANGE, "공사 연기하고 싶지 않아요. 예정대로 해 주세요", "not"),
        (free.CHANGE, "절대 공사 미루지 말아 주세요", "not"),
        (free.CHANGE, "공사 안 미뤄도 돼요", "not"),
        (free.CHANGE, "미룰 필요 없어요", "not"),
        (free.CHANGE, "공사를 미뤄야 할까요?", "ask"),
        (free.CHANGE, "공사 일정 바꿔야 하나요?", "ask"),
        (free.CHANGE, "공사 연기해야 하나 고민이에요", "ask"),
        # 취소
        (free.CANCEL, "취소해 줘", None),
        (free.CANCEL, "음 아니다, 그 카드 취소해 줘", None),
        (free.CANCEL, "결도배는 남기고 나머지 취소해 줘", None),
        (free.CANCEL, "날짜 바꾸기 카드 취소하지 마세요. 조금 있다 누를게요", "not"),
        (free.CANCEL, "취소 안 할게요", "not"),
        (free.CANCEL, "그 카드 거두지 말아 주세요", "not"),
        (free.CANCEL, "취소 말고 2주 미뤄 주세요", "other"),
        (free.CANCEL, "실측 요청 취소하면 위약금 있어요?", "ask"),
        # 업체 못 받아요('거절 안 해요'의 '안 해'는 따로 세지 않아요)
        (VENDOR["decline"], "거절 처리해", None),
        (VENDOR["decline"], "일정이 꽉 차서 이번 요청은 못 받아요", None),
        (VENDOR["decline"], "못 받아요 시간이 없어요", None),
        (VENDOR["decline"], "네 받을게요, 거절 안 해요", "not"),
        (VENDOR["decline"], "어렵지 않아요. 이 기간에 갈게요", "not"),
        (VENDOR["decline"], "힘들지 않아요 갈 수 있어요", "not"),
        (VENDOR["decline"], "못 받는 거 아니에요. 기간 답할게요", "not"),
        (VENDOR["decline"], "거절 말고 기간 답할게요", "other"),
        (VENDOR["decline"], "못 받으면 불이익 있어요?", "ask"),
        (VENDOR["window"], "기간 답할게요", None),
        (VENDOR["window"], "기간 답하지 않을게요", "not"),
        # 카드 의도
        (CUSTOMER["vendors"], "업체 추천은 필요 없어요", "not"),
        (CUSTOMER["compare"], "견적서 비교는 안 해도 돼요", "not"),
        (CUSTOMER["schedule"], "공정표 보여 주지 마세요", "not"),
        (CUSTOMER["today"], "오늘 할 일 없어요?", "ask"),
        (CUSTOMER["standard"], "표준견적서 안 보여요", None),
    ],
)
def test_doubt_reads_each_action_word(rx, text, want):
    assert free.doubt(text, rx) == want


def test_cancel_and_vendor_words_skip_negations():
    assert free.cancel_said("아까 그 카드 취소해 줘")
    for text in ("취소하지 마세요", "취소 안 할게요", "그 카드 거두지 말아 주세요"):
        assert not free.cancel_said(text), text
    assert free.vendor_next("네 받을게요, 거절 안 해요", "decline") == "window"
    assert free.vendor_next("힘들지 않아요 갈 수 있어요", "decline") is None
    assert free.customer_wished("업체 추천은 필요 없어요", "vendors") is None
    assert free.customer_wished("업체 추천 말고 견적서 비교해 줘", "vendors") == "compare"
    assert free.customer_wished("업체 추천해 주세요", "vendors") == "vendors"


def test_days_said_reads_like_memory():
    """#7: '토요일은 안 돼요'는 주말이 아니라 평일(memory.prefs와 같은 뜻)."""
    for text in (
        "토요일은 안 돼요",
        "일요일엔 못 해요",
        "토요일이나 일요일은 안 돼요",
        "주말엔 안 돼요",
    ):
        assert free.days_said(text) == "weekday", text
    assert free.days_said("평일엔 회사라 주말에 돼요?") == "weekend"
    assert free.days_said("주말은 안 되고 평일 오전이 좋아요") == "weekday"
    assert free.days_said("토요일은 안 되고 일요일은 돼요") == "weekend"
    assert free.days_said("주말이나 평일 다 돼요") is None
    assert free.days_said("실측은 언제 할 수 있어요?") is None


def test_change_wish_reads_two_weeks_only_as_a_word():
    """#6: 조사 '이' 뒤 '주말'은 2주가 아니에요. #18: 달력에 없는 날짜는 일주일로 넘기지 않고 날짜를 물어요."""
    for text in (
        "공사 좀 미뤄 주세요. 남편이 주말에만 시간이 돼요",
        "공사 날짜 바꿔 주세요, 아이 주말 학원 때문에요",
        "이사한 달이라 좀 미뤄 주세요",
        "이 주말에 미뤄 주세요",
    ):
        assert free.change_wish(text, TODAY) == (7, None), text
    for text, days in (
        ("이주일 미뤄 주세요", 14),
        ("두 주 미뤄 주세요", 14),
        ("한 달 미뤄 주세요", 30),
    ):
        assert free.change_wish(text, TODAY) == (days, None), text
    assert free.change_wish("11월 31일부터로 미뤄 주세요", TODAY) == (None, None)
    assert free.change_wish("2월 30일로 미뤄 주세요", TODAY) == (None, None)


def test_demolish_question_route():
    """#19: '철거 포함이에요?'는 폐기물처럼 받은 견적서 포함 칸 길(다른 공사 철거 · 집 정보 말은 아니에요)."""
    for text in ("철거 포함이에요?", "기존 벽지 철거는 따로예요?", "견적서에 철거 포함돼 있어요?"):
        assert free.route_of(text) == "demolish", text
    for text in ("욕실 철거 포함이에요?", "철거 포함해 주세요", "철거 범위 바꿔 주세요"):
        assert free.route_of(text) is None, text


def test_new_texts_pass_style_lint():
    texts = [
        free.CHANGE_KEEP, free.CHANGE_NO_DAY, free.NOT_WANTED, free.VENDOR_KEEP, free.CANCEL_KEEP,
    ]  # fmt: skip
    rules = {"R2", "R3", "R4", "R6", "R11", "R13", "R14"}
    bad = [(t, [h.rule for h in sl.check(t, "answer") if h.rule in rules]) for t in texts]
    assert not [b for b in bad if b[1]], bad


# ---- 고객: 날짜 바꾸기 · 취소(#4 · #5 · #6 · #18) ----


def start_of(pid: str) -> date:
    return query("select start_date from deals where project_id = $1::uuid", pid)[0]["start_date"]


def test_negated_or_asked_postpone_makes_no_card(api):
    """#5: '미루고 싶지 않아요' · '미뤄야 할까요?'는 카드를 만들지 않고, 열린 카드를 바꾸지도 않는다."""
    _t, pid, _d = scheduled(api)
    for text in ("공사 미루고 싶지 않아요", "절대 공사 미루지 말아 주세요"):
        ev = ok(ask(api, pid, text))
        assert not proposed(ev), text
        assert said(ev) == free.CHANGE_KEEP, text
    for text in ("공사를 미뤄야 할까요?", "공사 일정 바꿔야 하나요?"):
        ev = ok(ask(api, pid, text))
        assert not proposed(ev), text
        assert said(ev) in (free.CHANGE_HOW, free.AGAIN[free.CHANGE_HOW]), text
    assert query("select count(*) n from assistant_actions")[0]["n"] == 0
    # 열린 카드 A 뒤 '아 잠깐, 미루고 싶지 않아요': A는 그대로, 새 카드 없음, 같은 말로 A를 다시 볼 수 있다
    (a,) = proposed(ok(ask(api, pid, "공사를 2주 미루고 싶어요")), "date_change")
    ev = ok(ask(api, pid, "아 잠깐, 공사 미루고 싶지 않아요"))
    assert not proposed(ev) and said(ev) == free.CHANGE_KEEP
    assert status(a) == "proposed"
    ev = ok(ask(api, pid, "공사를 2주 미루고 싶어요"))
    assert [x["action_id"] for x in proposed(ev)] == [a["action_id"]]
    assert said(ev) == free.CHANGE_SAME


def test_negated_cancel_keeps_the_open_card(api):
    """#4: '취소하지 마세요'는 열린 카드를 거두지 않는다. '날짜 바꾸기 카드 취소해 줘'는 지금처럼 거둔다."""
    _t, pid, _d = scheduled(api)
    (a,) = proposed(ok(ask(api, pid, "공사를 2주 미루고 싶어요")), "date_change")
    for text in (
        "날짜 바꾸기 카드 취소하지 마세요. 조금 있다 누를게요",
        "그 카드 거두지 말아 주세요",
        "취소 안 할게요",
    ):
        ev = ok(ask(api, pid, text))
        assert said(ev) == free.CANCEL_KEEP, text
        assert status(a) == "proposed", text
    ev = ok(ask(api, pid, "날짜 바꾸기 카드 취소해 줘"))
    assert status(a) == "rejected" and said(ev).startswith("네, ")


def test_postpone_reads_days_from_words(api):
    """#6: '남편이 주말에만'의 '이 주'는 2주가 아니라 기본 일주일. #18: 없는 날짜면 카드 없이 다시 묻는다."""
    _t, pid, _d = scheduled(api)
    start = start_of(pid)
    off = days_off(TODAY, TODAY + timedelta(days=400))
    (a,) = proposed(
        ok(ask(api, pid, "공사 좀 미뤄 주세요. 남편이 주말에만 시간이 돼요")), "date_change"
    )
    wish = json.loads(action_row(a["action_id"])["payload"])["wish_dates"]
    assert wish[0] == workdays(start + timedelta(days=7), 1, off)[0].isoformat()
    ev = ok(ask(api, pid, "11월 31일부터로 미뤄 주세요"))
    assert not proposed(ev) and said(ev) == free.CHANGE_NO_DAY
    assert status(a) == "proposed"  # 열린 카드를 일주일 카드로 바꾸지 않는다


# ---- 고객: 요일 · 철거 · 카드 의도(#7 · #19 · #20) ----


def test_saturday_no_shows_weekdays_first(api):
    """#7: '토요일은 안 돼요'에 주말 반나절을 먼저 보이지 않는다(평일 먼저)."""
    f = offered(api)
    ev = ok(ask(api, f["pid"], "실측 날짜 잡고 싶은데 토요일은 안 돼요"))
    slots = [d for e, d, _ in ev if e == "card" and d["kind"] == "visit_slots"]
    days = [date.fromisoformat(c["day"]) for s in slots for c in s["data"]["candidates"]]
    assert days and days[0].weekday() < 5
    assert said(ev) == free.SLOTS_DAY.format(day="평일")


def test_demolish_question_answers_from_received_quotes(api):
    """#19: '철거 포함이에요?'는 표준견적서 합계가 아니라 받은 견적서의 철거 포함 칸으로 답한다."""
    pid = two_quotes(api)
    text, kinds = turn(api, pid, "철거 포함이에요?")
    assert text.startswith(
        "결도배는 기존 벽지 철거가 포함이고, 마루와벽은 견적서에 적혀 있지 않아요."
    )
    assert "집 정보는 철거 안 함이라 서로 달라요." in text and kinds == ["quote_compare"]


def test_unwanted_card_intent_asks_back(api):
    """#20: '업체 추천은 필요 없어요'에 추천 카드를 보이지 않고 되묻는다. 바라는 말은 그대로 카드."""
    pid = two_vendors(api)
    assert turn(api, pid, "업체 추천은 필요 없어요") == (free.NOT_WANTED, [])
    text, kinds = turn(api, pid, "업체 추천해 주세요")
    assert "vendor_picks" in kinds and text != free.NOT_WANTED


# ---- 업체: 못 받아요 부정(#3) ----


def test_vendor_negated_decline_keeps_the_window_card(api):
    """#3: '네 받을게요, 거절 안 해요'에 못 받아요 카드를 만들지 않고 열린 기간 답하기 카드를 그대로 둔다(받는다는
    말이라 그 카드를 다시 보인다). 다른 할 일 말이 없으면 되묻는다. '못 받아요'는 지금처럼 못 받아요 카드."""
    f = requested(api)
    login(api, f["email"])
    (w,) = proposed(ok(vendor_turn(api, f["visit"], "기간 답할게요")), "window_answer")
    ev = ok(vendor_turn(api, f["visit"], "네 받을게요, 거절 안 해요"))
    assert not proposed(ev, "decline")
    assert [x["action_id"] for x in proposed(ev, "window_answer")] == [w["action_id"]]
    for text in ("힘들지 않아요 갈 수 있어요", "못 받는 거 아니에요"):
        ev = ok(vendor_turn(api, f["visit"], text))
        assert not proposed(ev) and said(ev) == free.VENDOR_KEEP, text
    assert not query("select 1 from assistant_actions where kind = 'decline'")
    assert status(w) == "proposed"
    (d,) = proposed(ok(vendor_turn(api, f["visit"], "못 받아요")), "decline")
    assert status(w) == "expired" and status(d) == "proposed"

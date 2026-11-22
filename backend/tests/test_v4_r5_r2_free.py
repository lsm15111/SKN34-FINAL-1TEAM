"""고침 5차 R2(QA r5 D 무료 모드 새 문제 1~3): 무료 모드 취소는 LLM 길과 같은 풀기(업체 이름 · '둘 다 · 모두' ·
'…는 남기고 · … 빼고')로 요청마다 카드를 만들고 못 풀면 '둘 다 취소' 칩, 알림 부탁('업체 답 오면 알려 줘')은 업체 추천
앞에서 믿집이 먼저 알리는 일만 약속(밤이면 아침에 간다는 말, 바로 앞과 같은 글은 짧게), 견적서 전 '빠진 거 없어요?'는
표준견적서 줄의 포함 상태(실측 후 · 선택 · 안 함)로 답한다. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import re
from datetime import datetime

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from app.shared.clock import SEOUL
from tests.conftest import query
from tests.helpers import use
from tests.test_extras import scheduled
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_free_qa import turn, two_quotes, two_vendors
from tests.test_v4_assistant_new_tools import cards_of, said, two_requests
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_copy_style import sl

RULES = {"R2", "R3", "R4", "R6", "R11", "R13", "R14"}


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


def cancels(ev) -> dict[str, dict]:
    """이 턴에 보낸 열린 실측 요청 취소 승인 카드(요청 id → 카드)."""
    return {
        x["target_id"]: x
        for x in acts(ev)
        if x["kind"] == "visit_cancel" and x["status"] == "proposed"
    }


def free_ok(api, pid: str, text: str) -> list:
    ev = ok(ask(api, pid, text))
    assert ev[-1][1]["mode"] == "free"
    return ev


def lint(*texts: str) -> None:
    bad = [(t, [h.rule for h in sl.check(t, "answer") if h.rule in RULES]) for t in texts]
    assert not [x for x in bad if x[1]], bad


def statuses() -> set[str]:
    return {r["status"] for r in query("select status from visits")}


# ---- 1. 취소(D f1 5 · 6): 업체 이름 · '둘 다' · '…는 남기고'로 풀고, 못 풀면 '둘 다 취소' 칩 ----


def test_named_vendor_cancels_only_that_request(api):
    w = two_requests(api)
    ev = free_ok(api, w["pid"], "마루와벽 취소해 줘")
    assert set(cancels(ev)) == {w["visits"]["마루와벽"]} and not cards_of(ev, "options")
    assert said(ev) == free.CANCEL_MADE.format(vendor="마루와벽")


def test_both_makes_a_cancel_card_for_each_request_and_again_keeps_them(api):
    """D f1 6: '보낸 실측 요청 둘 다 취소해 줘'에 같은 고르기만 되풀이 · 승인 카드 0."""
    w = two_requests(api)
    ev = free_ok(api, w["pid"], "보낸 실측 요청 둘 다 취소해 줘")
    assert set(cancels(ev)) == set(w["visits"].values()) and not cards_of(ev, "options")
    first = said(ev)
    assert first in {
        free.CANCEL_MANY_MADE.format(names=n) for n in ("결도배 · 마루와벽", "마루와벽 · 결도배")
    }
    assert statuses() == {"requested"}  # 말로는 실행하지 않아요(카드를 눌러야 취소)
    # 같은 말을 또 하면(열린 취소 카드를 고를 거리로 세지 않고) 같은 카드를 다시 보여요
    ev = free_ok(api, w["pid"], "둘 다 취소해 줘")
    assert set(cancels(ev)) == set(w["visits"].values()) and not cards_of(ev, "options")
    assert said(ev) == free.CANCEL_MANY_SAME
    lint(first, free.CANCEL_MANY_SAME)


def test_unnamed_cancel_offers_the_both_chip_and_a_repeat_is_short(api):
    """D f1 5: 고르기 칩에 '둘 다 취소'가 없었어요."""
    w = two_requests(api)
    ev = free_ok(api, w["pid"], "실측 요청 취소해 줘")
    assert not acts(ev)
    (pick,) = cards_of(ev, "options")
    options = {o["label"]: o for o in pick["data"]["options"]}
    assert set(options) == {"결도배에 보낸 실측 요청", "마루와벽에 보낸 실측 요청", "둘 다 취소"}
    assert options["둘 다 취소"]["say"] == "보낸 실측 요청 둘 다 취소해 줘"  # LLM 길 칩과 같은 말
    assert said(ev) == free.CANCEL_PICK
    # 같은 고르기 글을 바로 되풀이하지 않아요(AGAIN)
    ev = free_ok(api, w["pid"], "취소해 줘")
    assert cards_of(ev, "options") and said(ev) == free.AGAIN[free.CANCEL_PICK]
    # '둘 다 취소' 칩을 누르면(그 글이 와요) 요청마다 카드
    ev = free_ok(api, w["pid"], options["둘 다 취소"]["say"])
    assert set(cancels(ev)) == set(w["visits"].values())
    lint(free.CANCEL_PICK, free.AGAIN[free.CANCEL_PICK])


@pytest.mark.parametrize(
    "text",
    [
        "결도배 빼고 다 취소해 줘",  # 업체 이름만 걸러 결도배 요청 카드를 만들던 말
        "결도배는 남기고 마루와벽 취소해 줘",
        "결도배는 그대로 두고 나머지 취소해 줘",
    ],
)
def test_keep_words_cancel_the_other_request(api, text):
    w = two_requests(api)
    ev = free_ok(api, w["pid"], text)
    assert set(cancels(ev)) == {w["visits"]["마루와벽"]}, said(ev)


def test_keeping_the_only_live_request_cancels_nothing(api):
    """살아 있는 요청이 남길 업체 하나뿐이면 그 요청 카드를 만들지 않아요(업체 이름만 걸러 만들던 것)."""
    w = two_requests(api)
    r = api.post(
        f"/projects/{w['pid']}/visits/{w['visits']['마루와벽']}/cancel", json={"code": "other"}
    )
    assert r.status_code == 200, r.text
    for text in ("결도배는 남기고 취소해 줘", "마루와벽 취소해 줘"):  # 마루와벽은 이미 취소
        ev = free_ok(api, w["pid"], text)
        assert not cancels(ev) and said(ev).startswith(free.CANCEL_NONE), (text, said(ev))


# ---- 2. 알림 부탁(D f1 3 · 4): 업체 추천 앞에서 받아 먼저 알리는 일만 약속 ----


def test_notify_ask_promises_the_vendor_answer_by_day_and_is_short_when_repeated(api, monkeypatch):
    monkeypatch.setattr(free, "is_night", lambda _now: False)
    w = two_requests(api)
    first, kinds = turn(api, w["pid"], "업체 답 오면 알려 줘")
    assert first in {
        free.NOTIFY_SAID.format(when=f"{n} 답하면")
        for n in ("결도배 · 마루와벽이", "마루와벽 · 결도배가")
    }, first
    assert "vendor_picks" not in kinds and not re.search(r"밤|아침", first)  # 낮엔 밤 얘기 없음
    again, _ = turn(api, w["pid"], "업체 답 오면 알려 줘")
    assert again == free.NOTIFY_AGAIN.format(when="답이 오면")
    third, _ = turn(api, w["pid"], "답 오면 알려 주세요")
    assert third == first  # 짧게 한 다음 턴은 원래 글(이어서 같은 글 없음)
    lint(first, again)


def test_notify_ask_at_night_says_it_goes_in_the_morning(api, monkeypatch):
    monkeypatch.setattr(free, "is_night", lambda _now: True)
    w = two_requests(api)
    first, _ = turn(api, w["pid"], "연락 오면 말해 줘")
    assert first.startswith(("결도배 · 마루와벽이 답하면 ", "마루와벽 · 결도배가 답하면 ")), first
    assert first.endswith("밤 알림은 아침 9시에 가요."), first
    again, _ = turn(api, w["pid"], "연락 오면 말해 줘")
    assert again == free.join(
        free.NOTIFY_AGAIN.format(when="답이 오면"), "밤 알림은 아침 9시에 가요."
    )
    lint(first, again)


def test_notify_ask_promises_only_what_mitjip_sends_first(api, monkeypatch):
    monkeypatch.setattr(free, "is_night", lambda _now: False)
    pid = two_vendors(api)  # 요청 전
    said_, _ = turn(api, pid, "견적서 나오면 바로 알려 줘")
    assert said_ == free.NOTIFY_SAID.format(when="실측 견적서가 오면")
    said_, _ = turn(api, pid, "업체 답 오면 알려 줘")  # 답 기다리는 업체가 없으면 '업체가'
    assert said_ == free.NOTIFY_SAID.format(when="업체가 답하면")
    # 믿집이 먼저 알리지 않는 일은 약속하지 않아요
    said_, _ = turn(api, pid, "가격 떨어지면 알려 줘")
    assert said_ == free.NOTIFY_LIST
    said_, _ = turn(api, pid, "답 오면 문자로 알려 줘")  # 문자 · 메일은 보내지 않아요
    assert said_ == free.join(free.NOTIFY_SAID.format(when="업체가 답하면"), free.NOTIFY_APP)
    lint(free.NOTIFY_LIST, free.NOTIFY_LIST_AGAIN, said_)


def test_notify_ask_about_a_delay_makes_no_date_change_card(api, monkeypatch):
    """'공사가 미뤄지면 알려 주세요'는 날짜 바꾸기 길(일주일 뒤로 미루는 승인 카드)로 가지 않아요."""
    monkeypatch.setattr(free, "is_night", lambda _now: False)
    customer, pid, _did = scheduled(api)  # 공사 날짜까지 수락한 집
    use(api, customer)
    ev = free_ok(api, pid, "공사가 미뤄지면 알려 주세요")
    assert not [x for x in acts(ev) if x["kind"] == "date_change"]
    want = free.NOTIFY_SAID.format(when=free.NOTIFY_WHEN["dates"][0])
    assert said(ev) == want
    lint(want, free.NOTIFY_AGAIN.format(when=free.NOTIFY_WHEN["dates"][1]))


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("업체 답 오면 알려 줘", "reply"),
        ("답 오면 알려 주세요", "reply"),
        ("연락 오면 말해 줘", "reply"),
        ("업체가 답하면 저한테 알려 줄래요?", "reply"),
        ("실측 날짜 잡히면 알려 줘", "reply"),
        ("견적서 나오면 바로 알려 줘", "quote"),
        ("실측 끝나면 알려 주세요", "quote"),
        ("업체가 공사 날짜 올리면 알려 주세요", "dates"),
        ("공사가 미뤄지면 알려 주세요", "dates"),
        ("공사 연기되면 알려 줘", "dates"),
        ("추가 금액 생기면 알려 줘", "extra"),
        ("공사 다 끝나면 알려 줘", "done"),
        ("조사 끝나면 알려 줘", "research"),
        ("공사 일주일 남으면 알려 줘", "week"),
        ("공사 전날 되면 알려 줘", "eve"),
        ("오면 알려 줘", None),
    ],
)
def test_notify_words(text, kind):
    assert free.notify_asked(text) and free.notify_kind(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "오늘 할 일 알려 줘",
        "업체 추천해 줘",
        "표준견적서 알려 줘",
        "답 오면 알려 주지 마세요",
        "실측 끝나면 연락해 줘요?",  # 업체가 연락하는지 묻는 말
        "견적서 오면 어떻게 해요?",
        "공사 끝나면 뭘 확인해요?",
    ],
)
def test_not_notify_words(text):
    assert not free.notify_asked(text)


def test_is_night_reads_the_nudge_rules():
    from app.assistant import proactive

    assert free.is_night(datetime(2026, 11, 22, 22, 0, tzinfo=SEOUL))
    assert free.is_night(datetime(2026, 11, 22, 8, 59, tzinfo=SEOUL))
    assert not free.is_night(datetime(2026, 11, 22, 16, 39, tzinfo=SEOUL))
    assert free.morning_at() == "아침 9시" and proactive.RULES.night_to == 9


# ---- 3. 견적서 전 '빠진 거 없어요?'(D f1 2): 표준견적서 줄 포함 상태 ----


def out_names(api, pid: str, state: str) -> list[str]:
    std = api.get(f"/projects/{pid}/standard").json()
    names = (free.line_name(ln["name"]) for t in std["trades"] for ln in t["lines"])
    states = (ln["state"] for t in std["trades"] for ln in t["lines"])
    return list(dict.fromkeys(n for n, st in zip(names, states, strict=True) if st == state))


def test_missing_before_quotes_says_the_lines_outside_the_total(api):
    w = two_requests(api)  # 실측 요청만 보냄(받은 견적서 없음)
    after = out_names(api, w["pid"], "after_visit")
    assert after  # 기존 벽지 철거 · 폐기물 처리는 실측 후 줄(계산 엔진이 저장한 상태)
    seen = []
    for text in ("빠진 거 없어요?", "빠진 건 없죠?", "누락된 거 있어요?"):
        got, kinds = turn(api, w["pid"], text)
        assert got.startswith(f"표준견적서에서 '실측 후'로 둔 {' · '.join(after)}"), got
        assert "합계에 없어요." in got and got.endswith(free.MISSING_NEXT), got
        # 금액을 새로 만들지 않아요
        assert kinds == ["standard_quote"] and not re.search(r"\d", got)
        seen.append(got)
    assert free.FREE_ASK not in seen
    lint(*seen)


def test_missing_said_names_each_state_with_its_screen_word():
    groups = [
        ("'실측 후'로 둔", ["기존 벽지 철거", "폐기물 처리"]),
        ("'안 함'인", ["천장 도배 시공"]),
    ]
    assert free.missing_said(groups) == (
        "표준견적서에서 '실측 후'로 둔 기존 벽지 철거 · 폐기물 처리와 '안 함'인 천장 도배 시공은 "
        f"합계에 없어요. {free.MISSING_NEXT}"
    )
    assert free.missing_said([]) == free.join(free.MISSING_ALL, free.MISSING_NEXT)


def test_missing_after_quotes_keeps_the_quote_path(api):
    pid = two_quotes(api)  # 마루와벽 폐기물 포함 · 결도배 폐기물 빠짐
    waste = "마루와벽은 폐기물 처리가 포함이고, 결도배는 포함 항목에 없어요."
    got, kinds = turn(api, pid, "빠진 거 없어요?")
    assert got == f"{waste} {free.INCL_NO}" and kinds == ["quote_compare"]


@pytest.mark.parametrize(
    "text",
    [
        "빠진 거 없어요?",
        "빠진 건 없죠?",
        "누락된 거 있어요?",
        "뭐가 빠진 거 아니에요?",
        "빠진 게 있나요?",
    ],
)
def test_missing_words_take_the_missing_route(text):
    assert free.route_of(text) == "missing"


@pytest.mark.parametrize(
    "text",
    [
        "업체가 빠졌어요",
        "직접 할 일 중에 빠진 거 없어요?",
        "준비물 빠진 거 없죠?",
        "빠진 업체 있어요?",
    ],
)
def test_other_missing_words_do_not(text):
    assert free.route_of(text) is None

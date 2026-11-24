"""고침 3차 A1(QA r3): 턴 사실에 업체마다 지금 상태 · 채팅 · 실제 단계 · 확정/예상 공정표 · 공급 평형 · 열린 카드가
무엇에 대한 것인지, 지난 글 24줄(오래된 비서 글은 앞부분만)과 '지난 대화' 줄. 유료 호출 0회(Claude 대본).

- c4 #33 · #34 · #37: 먼저 '견적서가 왔어요'라고 알린 1분 뒤 '견적서가 오면'이라고 답함 · 확정 때 닫힌 실측을
  '잡혀 있었어요'라고 답함(단계 줄이 '실측 요청 뒤' 하나뿐).
- c2 12턴: 확정 공정표인데 '지금 예상 공정표 기준'. c4b: 전용 59㎡ 집을 '21평'.
- c1 16 · 17턴: 공사 날짜 수락 카드가 열려 있는데 수락 카드를 또 만들까 물음.
- c5 17턴: 지난 글 12줄 밖에서 한 말을 '처음 나왔다'고 고침.
"""

import json
import uuid
from datetime import date, timedelta
from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as S
from app.shared import kdate
from app.shared.clock import today_seoul
from tests.helpers import use
from tests.test_deal import confirm
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import add, booked, day, vendor
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login

TODAY = date(2026, 11, 22)  # 일요일


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def row(status: str, name: str = "결도배", **kw):
    """실측 일정 상태판 줄(visit.service.board_now)과 같은 칸."""
    base = {
        "status": status,
        "vendor_name": name,
        "vendor_id": uuid.uuid4(),
        "visit_id": uuid.uuid4(),
        "booked": None,
        "quote": None,
        "cancel_code": None,
        "expired_reason": None,
        "next": NS(kind="none", who="none"),
    }
    return NS(**{**base, **kw})


def deal(status: str = "confirmed", **kw):
    base = {
        "id": uuid.uuid4(),
        "status": status,
        "vendor_id": uuid.uuid4(),
        "vendor_name": "마루와벽",
        "visit_id": uuid.uuid4(),
        "grand_total": 2_992_000,
        "start_date": None,
        "end_date": None,
    }
    return NS(**{**base, **kw})


SAT = NS(day=date(2026, 11, 28), half="am")


# ---- 업체마다 지금 상태(화면 말) ----


@pytest.mark.parametrize(
    ("r", "chosen", "want"),
    [
        (row("requested"), False, "실측 요청함(업체 답 기다림)"),
        (row("offered"), False, "실측 기간 답 옴(날짜 고를 차례)"),
        (row("picked", booked=SAT), False, "실측 날짜 고름(11월 28일(토) 오전 · 업체 수락 기다림)"),
        (row("booked", booked=SAT), False, "실측 날짜 정해짐(11월 28일(토) 오전)"),
        (
            row("booked", booked=SAT, next=NS(kind="change", who="vendor")),
            False,
            "실측 날짜 바꾸기를 요청함(업체 답 기다림)",
        ),
        (row("visited"), False, "실측 받음(견적서 기다림)"),
        (
            row("quoted", quote=NS(version=2, total=3_300_000)),
            False,
            "견적서 옴(2판 · 부가세 포함 3,300,000원)",
        ),
        (row("closed"), True, "닫힘(다른 업체 확정 때)"),
        (row("cancelled", cancel_code="other"), False, "닫힘(고객 취소)"),
        (row("cancelled", cancel_code="late_quote"), False, "닫힘(견적서가 늦어 취소)"),
        (row("declined"), False, "닫힘(업체가 못 받음)"),
        (row("expired", expired_reason="reply"), False, "닫힘(업체 답 기한 지남)"),
    ],
)
def test_visit_words_name_each_state(r, chosen, want):
    assert S.visit_words(r, chosen, TODAY) == want


def test_vendor_line_puts_the_deal_and_the_closed_one_together():
    d = deal(
        "scheduled", start_date=date(2026, 12, 14), end_date=date(2026, 12, 16)
    )  # 수락한 공사 날
    rows = [row("chosen", "마루와벽", visit_id=d.visit_id), row("closed", "결도배")]
    assert S.vendors_line(rows, d, "scheduled", TODAY) == (
        "업체: 마루와벽 확정 · 공사 금액 부가세 포함 2,992,000원 · 업체 공사 날 12월 14일(월)~16일(수)"
        " / 결도배 닫힘(다른 업체 확정 때)"
    )
    waiting = deal()
    assert S.deal_words(waiting, "waiting", TODAY) == (
        "확정 · 공사 금액 부가세 포함 2,992,000원 · 업체가 공사 날짜를 정하는 중"
    )
    assert S.deal_words(waiting, "proposed", TODAY).endswith("업체가 올린 공사 날짜를 수락할 차례")
    assert S.vendors_line([], None, None, TODAY) is None


def test_chat_line_only_names_open_chats():
    open_one = row("booked", "결도배", booked=SAT)
    rows = [open_one, row("requested", "마루와벽"), row("declined", "한결")]
    assert S.chat_line(rows, None, {open_one.vendor_id}) == (
        "채팅: 결도배 열림 / 마루와벽 아직 안 열림(실측 날짜가 정해지면 열려요)"
    )
    assert S.chat_line([row("declined")], None, set()) == (
        "채팅: 열린 채팅 없음(실측 날짜가 정해지면 열려요)"
    )


@pytest.mark.parametrize(
    ("rows", "d", "dates", "want"),
    [
        ([], None, None, ("업체 고르기(실측 요청 전)", "pick")),
        (
            [row("cancelled"), row("declined")],
            None,
            None,
            ("업체 고르기(보낸 실측 요청이 모두 닫힘)", "pick"),
        ),
        (
            [row("requested"), row("offered")],
            None,
            None,
            ("실측(요청한 업체 2곳 · 견적서 전)", "visit"),
        ),
        (
            [row("quoted", quote=NS(version=1, total=1)), row("booked", booked=SAT)],
            None,
            None,
            ("견적 견주기(받은 견적서 1곳 · 견적서 기다리는 업체 1곳)", "deal"),
        ),
        ([], deal(), "waiting", ("확정(공사 날짜 정하기)", "dates")),
        (
            [],
            deal("scheduled", start_date=TODAY + timedelta(days=1)),
            "scheduled",
            ("확정(공사 날짜 수락함 · 공사 전)", "eve"),
        ),
        (
            [],
            deal("scheduled", start_date=TODAY + timedelta(days=9)),
            "scheduled",
            ("확정(공사 날짜 수락함 · 공사 전)", "prep"),
        ),
        (
            [],
            deal("scheduled", start_date=TODAY + timedelta(days=9)),
            "change_requested",
            ("확정(공사 날짜 바꾸는 중)", None),
        ),
        ([], deal("scheduled", start_date=TODAY), "scheduled", ("공사(공사 날짜가 됐어요)", None)),
        ([], deal("checking"), "scheduled", ("공사(업체가 끝냈다고 함 · 끝 확인할 차례)", "check")),
        ([], deal("done"), "scheduled", ("끝(공사를 마쳤어요)", None)),
    ],
)
def test_stage_comes_from_vendor_states(rows, d, dates, want):
    assert S.stage_of(rows, d, dates, TODAY) == want


# ---- 카드 이름 · 집 줄 · 공정표 줄 ----


def test_card_name_says_what_the_card_is_for():
    def act(kind: str, title: str, **summary):
        return NS(kind=kind, summary={"title": title, **summary})

    accept = act(
        "dates_accept",
        "도배 12월 14일(월)~16일(수) 수락",
        rows=[{"label": "업체", "value": "결도배"}],
    )
    assert S.card_name(accept) == "공사 날짜 수락: 도배 12월 14일(월)~16일(수) 수락 · 결도배"
    same = act("visit_request", "결도배 · 마루와벽에 실측 요청 보내기")
    assert S.card_name(same) == "결도배 · 마루와벽에 실측 요청 보내기"
    assert S.card_name(act("home_info", "집 정보 저장")) == "집 정보 저장"  # 옛 시험과 같은 글
    no = act("decline", "이번 요청 못 받아요")
    assert S.card_name(no, "노원구 34평 도배") == "이번 요청 못 받아요 · 노원구 34평 도배"
    assert S.card_name(act("window_answer", "이 기간으로 답하기"), "노원구 32평 도배") == (
        "이 기간으로 답하기 · 노원구 32평 도배"
    )


def test_home_line_keeps_supply_pyeong_and_drops_the_guess_from_exclusive_area():
    supply = {"facts": ["서울 노원구", "공급 105.8㎡", "32평", "빈 집"], "locked": False}
    assert S.home_facts({**supply, "area_basis": "supply"}) == [
        "서울 노원구",
        "공급 105.8㎡",
        "32평형(공급)",
        "빈 집",
    ]
    excl = {"facts": ["서울 송파구", "전용 59.0㎡", "21.4평", "빈 집"], "locked": False}
    assert S.home_facts({**excl, "area_basis": "exclusive"}) == [
        "서울 송파구",
        "전용 59.0㎡",
        "빈 집",
    ]


# ---- 지난 글 24줄 · 오래된 비서 글은 앞부분만 ----


def test_clip_keeps_whole_sentences_within_the_limit():
    short = "짧은 답이에요."
    assert S.clip(short) == short
    text = ("가" * 120 + "요. ") + ("나" * 100 + "요. ") + "끝이에요."
    got = S.clip(text)
    assert got == "가" * 120 + "요.…" and len(got) <= S.HISTORY_CUT + 1
    assert S.clip("다" * 300).endswith("…") and len(S.clip("다" * 300)) == S.HISTORY_CUT


def test_history_clips_only_old_assistant_lines():
    rows = []
    for i in range(S.HISTORY // 2):
        rows.append(NS(role="user", text=f"고객 말 {i}" + "요" * 50, turn=i + 1))
        rows.append(NS(role="assistant", text="답" * 400 + f" {i}", turn=i + 1))
    got = S._history(rows)
    assert len(got) == S.HISTORY
    old, recent = got[: S.HISTORY - S.HISTORY_FULL], got[S.HISTORY - S.HISTORY_FULL :]
    assert all(len(m["content"]) <= S.HISTORY_CUT for m in old if m["role"] == "assistant")
    assert all(m["content"] == r.text for m, r in zip(old, rows) if m["role"] == "user")
    assert [m["content"] for m in recent] == [r.text for r in rows[-S.HISTORY_FULL :]]


# ---- 실제 턴: 업체 상태가 바뀔 때마다 사실이 따라온다 ----


def turn_facts(api, script, pid: str, text: str = "지금 어디까지 왔어요?") -> str:
    log = script([{"text": "네, 알려 드릴게요."}])
    ok(ask(api, pid, text))
    return facts_of(log[0])


def test_turn_facts_follow_each_vendor_from_booked_to_deal(api, script):
    f = booked(api)  # 마루와벽: 바로 확정으로 오늘 + 6일 오전 실측
    gyeol = vendor(api, "gyeol@mitjip.test", "결도배")
    use(api, f["token"])
    assert add(api, f["pid"], gyeol).status_code == 201
    assert ask_visits(api, f["pid"], [gyeol]).status_code == 201
    slot = f"{kdate.md_long(day(6), today_seoul())} 오전"
    facts = turn_facts(api, script, f["pid"])
    # 고침 4차 V(QA r4 s1 · s6): 살아 있는 요청 업체 이름 뒤에 대화 이름표(m…)가 붙어요(요청한 순으로 m1 · m2)
    assert (
        f"업체: 마루와벽(m1) 실측 날짜 정해짐({slot}) / 결도배(m2) 실측 요청함(업체 답 기다림)"
        in facts
    )
    assert "채팅: 마루와벽 열림 / 결도배 아직 안 열림(실측 날짜가 정해지면 열려요)" in facts
    assert "단계: 실측(요청한 업체 2곳 · 견적서 전)" in facts
    # 견적서가 오면 판 · 금액(부가세 포함)과 견적 견주기 단계
    login(api, f["email"])
    total = quote(api, f["visit"], 2_300_000)["sent"][0]["total"]
    use(api, f["token"])
    facts = turn_facts(api, script, f["pid"], "견적서 왔어요?")
    assert f"마루와벽(m1) 견적서 옴(1판 · 부가세 포함 {total:,}원)" in facts
    assert "단계: 견적 견주기(받은 견적서 1곳 · 견적서 기다리는 업체 1곳)" in facts
    # 확정하면 다른 업체 요청은 확정 때 닫힘(c4 #37 '잡혀 있었어요' 오답)
    assert confirm(api, f["pid"], f["visit"]).status_code == 200
    facts = turn_facts(api, script, f["pid"], "결도배도 실측하러 와요?")
    assert (
        f"업체: 마루와벽 확정 · 공사 금액 부가세 포함 {total:,}원 · 업체가 공사 날짜를 정하는 중"
        " / 결도배 닫힘(다른 업체 확정 때)"
    ) in facts
    assert "단계: 확정(공사 날짜 정하기)" in facts
    assert "채팅: 마루와벽 열림" in facts and "결도배 아직" not in facts


def test_cancelled_request_turns_the_stage_back_to_picking(api, script):
    from tests.test_v3_visit_kit import requested

    f = requested(api)
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/cancel", json={"code": "other"})
    assert r.status_code == 200, r.text
    facts = turn_facts(api, script, f["pid"])
    assert "업체: 마루와벽 닫힘(고객 취소)" in facts
    assert "단계: 업체 고르기(보낸 실측 요청이 모두 닫힘)" in facts
    assert "채팅: 열린 채팅 없음(실측 날짜가 정해지면 열려요)" in facts


def test_turn_facts_before_any_request_and_open_card_names(api, script):
    from tests.test_v3_visit_kit import customer
    from tests.test_v4_assistant_actions import propose_home

    _, pid = customer(api)
    assert api.get(f"/projects/{pid}/standard").status_code == 200  # 표준견적서(평)를 만든다
    facts = turn_facts(api, script, pid)
    assert "단계: 업체 고르기(실측 요청 전)" in facts and "집 정보 잠김" not in facts
    assert "공급 105.8㎡ · 32평형(공급)" in facts  # 공급 면적 집은 평형으로
    assert "업체:" not in facts
    assert "채팅: 열린 채팅 없음(실측 날짜가 정해지면 열려요)" in facts
    _, pid = home(api, "card@mitjip.test")  # 집 정보를 저장한 공사(방 수 고치기 카드가 열린다)
    a = propose_home(api, script, pid, {"rooms": 3})
    facts = turn_facts(api, script, pid, "카드 아직 있어요?")
    assert f"승인 기다리는 카드: {a['summary']['title']}" in facts


def test_turn_still_runs_when_vendor_states_cannot_be_read(api, script, monkeypatch):
    from sqlalchemy import text

    from app.visit import service as visit_service

    _, pid = home(api, "broken@mitjip.test")

    async def broken(s, *_a, **_k):  # DB 오류(트랜잭션이 깨지는 꼴): 세이브포인트가 턴 행을 지킨다
        await s.execute(text("select * from no_such_table_a1"))

    monkeypatch.setattr(visit_service, "board_now", broken)
    facts = turn_facts(api, script, pid)
    assert f"단계: {S.UNKNOWN_STAGE}" in facts and "업체:" not in facts


def test_history_window_says_older_turns_are_hidden_and_measures_the_prompt(api, script):
    from tests.test_v3_visit_kit import customer

    _, pid = customer(api)
    words = [
        "사과",
        "배",
        "감",
        "귤",
        "포도",
        "자두",
        "수박",
        "참외",
        "딸기",
        "키위",
        "망고",
        "앵두",
        "살구",
    ]
    for w in words:  # 13턴: 비서 글은 다섯 문장 · 250~300자(QA r3 가운데 241자)
        said = " ".join(
            [
                f"{w} 이야기를 먼저 해 볼게요, 오늘 고른 과일은 {w}이고 맛이 아주 좋아서 자주 먹어요.",
                f"{w}는 껍질 색이 고와서 보기만 해도 기분이 좋아지고 식탁에 올리면 분위기가 살아요.",
                f"{w}를 살 때는 향이 진하고 단단한 것을 찾으면 냉장고에 오래 두고 먹을 수 있어요.",
                f"{w}는 차갑게 두었다가 먹으면 더 시원하고 단맛이 살아나서 여름에 특히 좋아요.",
                f"다음에는 {w} 말고 다른 과일 이야기도 이어서 천천히 해 볼게요.",
            ]
        )
        script([{"text": said}])
        ok(ask(api, pid, f"{w} 이야기 해 줘요"))
    log = script([{"text": "네, 사과 이야기는 처음에 했어요."}])
    ok(ask(api, pid, "아까 사과 얘기 기억나요?"))
    req = log[0]
    facts = facts_of(req)
    assert "지난 대화: 앞부분은 안 보이고 최근 12턴만 보여요" in facts
    history = [m for m in req["messages"] if m["role"] in ("user", "assistant")][:-1]
    assert len(history) == S.HISTORY
    said = [m["content"] for m in history if m["role"] == "assistant"]
    assert all(len(x) <= S.HISTORY_CUT for x in said[: (S.HISTORY - S.HISTORY_FULL) // 2])
    assert all(len(x) > S.HISTORY_CUT for x in said[(S.HISTORY - S.HISTORY_FULL) // 2 :])
    # 보고서용 길이(글자, JSON): 지금 24줄(앞 비서 글 200자) · 옛 12줄(최근 12줄과 같음)
    size = len(json.dumps(history, ensure_ascii=False))
    recent = len(json.dumps(history[S.HISTORY - S.HISTORY_FULL :], ensure_ascii=False))
    print(f"\n[A1 길이] 지난 글 24줄(줄임) {size}자 · 옛 12줄 {recent}자 · 턴 사실 {len(facts)}자")
    assert size < recent * 2  # 앞 비서 글을 줄여 24줄이 12줄의 두 배보다 작다

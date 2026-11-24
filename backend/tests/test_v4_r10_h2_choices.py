"""QA 10차 H2(카드 단추 길 · 턴 사실). 유료 호출 0회(Claude 대본 · LLM 꺼짐).

- 1: 업체 추천 카드 단추로 만든 실측 요청 카드가 이 대화에서 고객이 말한 희망 기간을 써요(없을 때만 믿집 초안).
- 2: 단추로 만든 승인 카드도 제안 도구 결과처럼 누르면 무엇이 되는지(note · 요약 줄)를 모델에 넘겨요.
- 3: 턴 사실 업체 줄에 요청 때 고정한 가견적(견적서 오기 전).
- 4: 업체가 다른 날을 낸 뒤 다시 고르는 후보에서 업체가 어렵다고 한 때는 뒤로 · 표시, 끝난 제안 소식은 새 소식에서 빼요.
"""

import json
import uuid
from datetime import date
from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as S
from app.assistant.tools import cards, propose
from app.calc import slots
from tests.conftest import query
from tests.helpers import use
from tests.test_v3_visit_kit import WISH, answer, choose, d, day, requested
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_free import two_vendors
from tests.test_v4_assistant_new_tools import call, results, two_requests
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_r3_a1_facts import facts_of
from tests.test_v4_r9_f2_visit import SLOTS, proposed
from tests.test_visit_inbox import login


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


def payload(aid: str) -> dict:
    (row,) = query("select payload from assistant_actions where id = $1", uuid.UUID(aid))
    got = row["payload"]
    return json.loads(got) if isinstance(got, str) else got


def rows_of(action: dict) -> dict[str, str]:
    return {r["label"]: r["value"] for r in action["summary"]["rows"]}


def press(api, script, pid: str, text: str, card_id: str, choice: str) -> tuple[list, list]:
    """카드 단추 한 번(LLM 모드, 모델은 글만). (이벤트, 보낸 요청 기록)."""
    log = script([{"text": "카드를 확인해 주세요."}])
    ev = ok(ask(api, pid, text, context={"card_id": card_id, "choice": choice}))
    return ev, log


def user_text(req: dict) -> str:
    """모델에 보낸 마지막 고객 글(카드에서 고름 · 코드가 처리한 줄 포함)."""
    m = next(m for m in reversed(req["messages"]) if m["role"] == "user")
    c = m["content"]
    return c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c)


def proposed_one(ev) -> dict:
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    return a


# ---- 1: 단추로 만든 실측 요청 카드의 희망 기간 ----


def test_button_request_uses_the_wish_the_customer_said(api, script):
    """QA r10 c1 T4 · T5: '실측은 26~28일' 뒤 업체 추천 카드 단추 → 11.26 하루(믿집 초안) 카드가 생김."""
    pid, _ = two_vendors(api)
    _ev, log = call(
        script,
        api,
        pid,
        "업체 추천해 주세요. 실측은 닷새 뒤부터 이레 뒤 사이에 와 주면 좋겠어요",
        ("recommend_vendors", {"trade": "dobae", "wish": {"start": d(5), "end": d(7)}}),
    )
    got = results(log)[0]
    assert got["wish"] == {"start": d(5), "end": d(7)}  # 담은 기간을 모델도 알아요
    refs = [p["ref"] for p in got["picks"]]
    ev, log = press(
        api, script, pid, "두 곳에 요청할래요", "picks-dobae", "visit_request:" + ",".join(refs)
    )
    a = proposed_one(ev)
    assert rows_of(a)["희망 기간"] == cards.md_range(day(5), day(7))
    p = payload(a["action_id"])
    assert (p["wish_start"], p["wish_end"]) == (d(5), d(7))
    assert cards.md_range(day(5), day(7)) in user_text(log[0])  # 모델도 카드의 희망 기간을 봐요


def test_wish_said_to_the_request_tool_carries_to_the_next_button(api, script):
    """모델이 고객 말로 wish를 넣어 만든 카드 뒤, 다른 업체를 단추로 고르면 같은 기간이에요(초안으로 바뀌지 않음)."""
    pid, _ = two_vendors(api)
    _ev, log = call(
        script, api, pid, "업체 추천해 주세요", ("recommend_vendors", {"trade": "dobae"})
    )
    first, second = [p["ref"] for p in results(log)[0]["picks"]]
    ev, _log = call(
        script,
        api,
        pid,
        f"{first}에 요청해 줘요. 실측은 닷새 뒤부터 이레 뒤 사이요",
        (
            "propose_visit_request",
            {"trade": "dobae", "vendor_refs": [first], "wish": {"start": d(5), "end": d(7)}},
        ),
    )
    assert rows_of(proposed_one(ev))["희망 기간"] == cards.md_range(day(5), day(7))
    ev, _log = press(api, script, pid, "여기도요", "picks-dobae", f"visit_request:{first},{second}")
    a = proposed_one(ev)
    assert len(a["summary"]["amounts"]) == 2
    assert rows_of(a)["희망 기간"] == cards.md_range(day(5), day(7))


def test_button_request_without_a_said_wish_keeps_the_draft(api, script):
    pid, _ = two_vendors(api)
    _ev, log = call(
        script, api, pid, "업체 추천해 주세요", ("recommend_vendors", {"trade": "dobae"})
    )
    got = results(log)[0]
    assert "wish" not in got
    ev, log = press(
        api, script, pid, "여기로요", "picks-dobae", f"visit_request:{got['picks'][0]['ref']}"
    )
    a = proposed_one(ev)
    assert rows_of(a)["희망 기간"] == cards.md_range(day(WISH[0]), day(WISH[1]))  # 믿집 초안
    # 모델에는 초안이라는 사실과 고객이 말한 기간이 있으면 바꾸는 길이 가요
    assert propose.WISH_DRAFT in user_text(log[0])


def test_recommend_keeps_only_a_wish_that_fits_the_request_rules(api, script):
    pid, _ = two_vendors(api)
    _ev, log = call(
        script,
        api,
        pid,
        "업체 추천해 주세요. 실측은 오늘 와 주세요",
        ("recommend_vendors", {"trade": "dobae", "wish": {"start": d(0), "end": d(0)}}),
    )
    got = results(log)[0]
    assert "wish" not in got and propose.WISH_SAID["past"] in got["note"]
    ev, _log = press(
        api, script, pid, "여기로요", "picks-dobae", f"visit_request:{got['picks'][0]['ref']}"
    )
    assert rows_of(proposed_one(ev))["희망 기간"] == cards.md_range(day(WISH[0]), day(WISH[1]))


# ---- 2: 단추로 만든 승인 카드의 누른 뒤 일 ----


def test_button_made_card_tells_the_model_what_pressing_does(api, script):
    """QA r10 c1 T10: 다시 고르기 카드를 단추로 만든 턴에 '누르면 실측 날짜가 바로 정해져요'(카드는 업체 수락 뒤 확정)."""
    f = proposed(api)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "처음 기간에서 다시 고를래요",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS, "more": True}),
    )
    first = results(log, 2)[0]["candidates"][0]
    ev, log = press(
        api, script, f["pid"], "그 날로 할래요", f"slots-{f['visit']}", f"visit_slot:{first['ref']}"
    )
    a = proposed_one(ev)
    assert a["summary"]["approve_label"] == "이 날짜로 다시 고르기"
    said = user_text(log[0])
    # 제안 도구 결과와 같은 값: 새로 만듦 · 누른 뒤 일(업체가 낸 날은 닫히고 업체가 수락하면 정해져요) · 카드 줄
    assert propose.REPICK_THEN in said and propose.REPICK_ACCEPT in said
    assert "업체가 낸 날은 닫히고 업체가 수락하면 확정돼요" in said
    assert '"state": "new"' in said


# ---- 3: 턴 사실 업체 줄의 가견적 ----


def test_vendor_line_shows_the_fixed_estimate_before_the_quote():
    def row(status: str, name: str, won: int | None, **kw):
        base = {
            "status": status,
            "vendor_name": name,
            "vendor_id": uuid.uuid4(),
            "visit_id": uuid.uuid4(),
            "booked": None,
            "quote": None,
            "cancel_code": None,
            "expired_reason": None,
            "estimate_total": won,
            "next": NS(kind="none", who="none"),
        }
        return NS(**{**base, **kw})

    today = date(2026, 11, 25)
    rows = [
        row("offered", "우리집벽지", 2_575_738),
        row("requested", "솜씨공방", 2_684_044),
        row("quoted", "옛집도배", 3_099_844, quote=NS(version=1, total=3_250_000)),
        row("cancelled", "정담도배", 3_208_150, cancel_code="other"),
    ]
    assert S.vendors_line(rows, None, None, today) == (
        "업체: 우리집벽지 실측 기간 답 옴(날짜 고를 차례) · 가견적 부가세 포함 2,575,738원"
        " / 솜씨공방 실측 요청함(업체 답 기다림) · 가견적 부가세 포함 2,684,044원"
        " / 옛집도배 견적서 옴(1판 · 부가세 포함 3,250,000원) / 정담도배 닫힘(고객 취소)"
    )


def test_turn_facts_give_the_requested_vendors_fixed_estimates(api, script):
    """QA r10 c2 T27: 요청 뒤 '요청한 두 업체는 예산 안에 될까요?'에 보드의 가견적을 못 써 '알 수 없어요'."""
    w = two_requests(api)
    log = script([{"text": "네, 알려 드릴게요."}])
    ok(ask(api, w["pid"], "그럼 요청한 두 업체는 예산 안에 될까요?"))
    facts = facts_of(log[0])
    line = next(x for x in facts.split("\n") if x.startswith("업체: "))
    for r in query("select vendor_name, estimate_total from visits"):
        assert r["estimate_total"] is not None
        assert f"실측 요청함(업체 답 기다림) · 가견적 부가세 포함 {r['estimate_total']:,}원" in line
        assert r["vendor_name"] in line


# ---- 4: 업체가 어렵다고 한 때 · 끝난 제안 소식 ----


def test_candidates_put_the_declined_half_last_and_mark_it():
    today = date(2026, 11, 25)
    work = date(2026, 12, 21)  # − 20일 = 12.1
    days = [slots.DayOpen(date(2026, 12, 1), 1, 1), slots.DayOpen(date(2026, 12, 2), 1, 0)]
    hard = (date(2026, 12, 1), "am")
    got = slots.candidates(days, work, today, later={hard})
    assert (got[-1].day, got[-1].half) == hard
    assert "vendor_declined" in got[-1].why
    assert not {"earliest", "start_minus_20"} & set(got[-1].why)  # 권하는 까닭은 달지 않아요
    assert all("vendor_declined" not in x.why for x in got[:-1])
    assert (got[0].day, got[0].half) != hard
    # 뒤로 미룬 때 말고도 n개가 차면 그 때는 빠져요
    assert hard not in {
        (x.day, x.half) for x in slots.candidates(days, work, today, n=2, later={hard})
    }


def declined_after_pick(api) -> dict:
    """바로 확정 끔 · 업체 기간 오늘 + 9 ~ 10일 → 고객이 10일 오전을 고름 → 업체가 9일 오전 · 오후를 냄."""
    f = requested(api)
    login(api, f["email"])
    assert answer(api, f["visit"], start=9, end=10, instant=False).status_code == 200
    use(api, f["token"])
    assert choose(api, f["pid"], f["visit"], n=10, half="am").json()["status"] == "picked"
    login(api, f["email"])
    body = {
        "reason_code": "other_site",
        "note": "10일 오전은 앞 현장이 늦게 끝나요",
        "slots": [{"day": d(9), "half": "am"}, {"day": d(9), "half": "pm"}],
    }
    r = api.post(f"/vendor/visits/{f['visit']}/propose", json=body)
    assert r.status_code == 200, r.text
    use(api, f["token"])
    return f


def test_repick_puts_the_half_the_vendor_declined_last(api, script):
    """QA r10 c1 T9: 다시 고르기 후보 맨 앞이 업체가 어렵다고 한 26일 오후('가장 빠른 날이에요')."""
    f = declined_after_pick(api)
    _ev, log = call(
        script,
        api,
        f["pid"],
        "9일은 안 돼요. 처음 기간에서 다시 고를래요",
        ("today_tasks", {}),
        ("vendor_free_slots", {"ref": "m1", **SLOTS, "more": True}),
    )
    got = [(c["day"], c["half"], c["why"]) for c in results(log, 2)[0]["candidates"]]
    assert [(x, h) for x, h, _ in got] == [(d(10), "오후"), (d(10), "오전")]
    assert cards.WHY["vendor_declined"] in got[-1][2]
    assert cards.WHY["vendor_declined"] not in got[0][2]


def test_today_drops_the_proposal_news_once_the_customer_picks_again(api):
    """QA r10 c1 3: 다시 골라 실측이 잡힌 뒤에도 오늘 정할 일에 '다른 날을 제안했어요' 새 소식이 남음."""
    f = proposed(api)
    (note,) = query("select id from notifications where kind = 'visit_proposed'")
    news = api.get("/assistant/today", params={"project_id": f["pid"]}).json()["news"]
    assert f"n-{note['id']}" in [x["id"] for x in news]
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/repick")
    assert r.status_code == 200, r.text
    assert choose(api, f["pid"], f["visit"], n=9, half="am").json()["status"] == "picked"
    news = api.get("/assistant/today", params={"project_id": f["pid"]}).json()["news"]
    assert f"n-{note['id']}" not in [x["id"] for x in news]

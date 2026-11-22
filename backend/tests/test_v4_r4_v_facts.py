"""고침 4차 V(QA r4 s1 · s6 · s4 · c2): 턴 사실 업체 줄의 살아 있는 요청 이름표(m…) · 바로 확정 · 직접 할 일 날짜와
업체 사본 줄 · 확정 뒤 직접 할 일 카드 말 · 업체 종 알림의 공사 이름. 유료 호출 0회(Claude 대본).

- s1 · s6: 보낸 요청이 둘일 때 지난 턴 도구 결과의 이름표가 다음 턴 기록에 없어 취소 도구를 이름표 없이 6번씩 부름.
- s4 3턴: 승인 직후 이름표 표에 m이 없어 반나절 도구가 0ms로 실패 · 7턴: 바로 확정 업체에 '업체가 수락해야 정해져요'.
- c2 12 · 15턴: 도구 없이 답한 턴이 직접 할 일 날짜를 몰라 날짜 문장이 빠지고, 업체 사본에 이미 간 것을 모름.
  확정 뒤 승인 카드 메모 · 결과가 '실측을 요청한 업체', 업체 종 visit_diy_changed에 어느 요청인지 없음.
"""

import re
from datetime import date
from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as S
from app.assistant.tools import diy as diy_tools
from app.calc import diy as calc_diy
from app.visit.flow import DIY_DEALT_NOTE, DiyReach
from tests.helpers import use
from tests.test_dates import notes
from tests.test_deal import confirm
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import add, answer, choose, offered, vendor, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_new_tools import call, results, two_requests
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_r3_a1_facts import facts_of, row
from tests.test_visit_inbox import login

TODAY = date(2026, 11, 22)
LABEL = re.compile(r"(\S+)\((m\d+)\) ")


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


def line_of(facts: str, head: str) -> str:
    return next(x for x in facts.split("\n") if x.startswith(head))


def labels(facts: str) -> dict[str, str]:
    """턴 사실 '업체:' 줄의 업체 이름 → 이름표."""
    return dict(LABEL.findall(line_of(facts, "업체: ")))


def turn_facts(api, script, pid: str, text: str = "지금 어디까지 왔어요?") -> str:
    log = script([{"text": "네, 알려 드릴게요."}])
    ok(ask(api, pid, text))
    return facts_of(log[0])


# ---- 업체 줄 이름표(s1 · s6 · s4) ----


def test_vendor_line_labels_live_requests_and_the_next_turn_can_use_them(api, script):
    w = two_requests(api)
    pid = w["pid"]
    facts = turn_facts(api, script, pid)
    got = labels(facts)
    assert set(got) == {"결도배", "마루와벽"} and len(set(got.values())) == 2
    assert f"마루와벽({got['마루와벽']}) 실측 요청함(업체 답 기다림)" in facts
    # 같은 요청은 다음 턴에도 같은 이름표(표가 턴마다 늘지 않아요)
    assert labels(turn_facts(api, script, pid, "그대로예요?")) == got
    # 지난 턴 도구 결과 없이 턴 사실의 이름표만으로 취소 카드(이름표 없이 6번 부르던 것)
    ev, _log = call(
        script,
        api,
        pid,
        "그 요청 취소해 줘",
        ("propose_visit_cancel", {"visit_ref": got["마루와벽"], "code": "other"}),
    )
    (a,) = [x for x in acts(ev) if x["kind"] == "visit_cancel"]
    assert a["target_id"] == w["visits"]["마루와벽"]
    # 닫힌 요청에는 이름표를 붙이지 않아요
    r = api.post(f"/projects/{pid}/visits/{w['visits']['결도배']}/cancel", json={"code": "other"})
    assert r.status_code == 200, r.text
    facts = turn_facts(api, script, pid, "결도배는요?")
    assert "결도배 닫힘(고객 취소)" in facts and set(labels(facts)) == {"마루와벽"}


def test_slot_tool_works_with_the_label_from_facts_right_after_the_vendor_answers(api, script):
    """s4 3턴: 업체가 기간을 답한 직후 today_tasks 없이 반나절 도구를 부르면 표에 m이 없어 0ms로 실패했어요."""
    f = offered(api)  # 마루와벽 바로 확정 기간
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "s",
                        "name": "vendor_free_slots",
                        "input": {"ref": "m1", "prefer": "any", "days": "any"},
                    }
                ]
            },
            {"text": "가장 빠른 반나절을 골라 두었어요."},
        ]
    )
    ok(ask(api, f["pid"], "실측은 제일 빠른 날로 잡아 줘"))
    facts = facts_of(log[0])
    assert labels(facts) == {"마루와벽": "m1"}
    (got,) = results(log)
    assert "error" not in got and got["candidates"], got


def test_instant_vendor_says_picking_sets_it_without_the_vendor_accepting(api, script):
    f = offered(api)  # 바로 확정
    facts = turn_facts(api, script, f["pid"])
    assert f"마루와벽(m1) {S.OFFERED_INSTANT}" in facts
    assert f"채팅: 마루와벽 아직 안 열림({S.CHAT_PICK})" in facts
    g = offered(
        api, instant=False, email="gyeol@mitjip.test", name="결도배", customer_email="b@mitjip.test"
    )
    facts = turn_facts(api, script, g["pid"])
    assert "결도배(m1) 실측 기간 답 옴(반나절 고를 차례)" in facts and "바로 확정" not in facts
    assert f"채팅: 결도배 아직 안 열림({S.CHAT_WAIT})" in facts


def test_words_and_chat_line_for_instant_and_proposed_rows():
    win = NS(instant=True)
    fast = row("offered", "마루와벽", window=win)
    slow = row("offered", "결도배", window=NS(instant=False))
    other = row("proposed", "한결")
    assert S.visit_words(fast, False, TODAY) == S.OFFERED_INSTANT
    assert S.visit_words(slow, False, TODAY) == "실측 기간 답 옴(반나절 고를 차례)"
    assert S.visit_words(other, False, TODAY).endswith("고르면 바로 정해짐)")
    assert S.chat_line([fast, slow, other], None, set()) == (
        f"채팅: 결도배 아직 안 열림({S.CHAT_WAIT}) / 마루와벽 · 한결 아직 안 열림({S.CHAT_PICK})"
    )
    refs = {fast.visit_id: "m3"}
    assert S.vendors_line([fast, slow], None, None, TODAY, refs) == (
        f"업체: 마루와벽(m3) {S.OFFERED_INSTANT} / 결도배 실측 기간 답 옴(반나절 고를 차례)"
    )


# ---- 직접 할 일 날짜 · 업체 사본(c2) ----


def _requested_home(api, email: str = "home@mitjip.test") -> tuple[str, str, str]:
    """집 정보(노원구 상계동)가 있는 공사에 마루와벽 실측 요청까지(고객으로 로그인한 채). (공사, 요청, 고객 토큰)"""
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    token, pid = home(api, email)
    assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [vid]).status_code == 201
    return pid, visit_of(pid, vid), token


def test_diy_line_has_calc_dates_and_the_vendor_copy(api, script):
    pid, _visit, _token = _requested_home(api)
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["paint", "silicone"]})
    assert r.status_code == 200 and r.json()["told"] == ["마루와벽"], r.text
    log = script(
        [
            {"tool_calls": [{"id": "d", "name": "diy_plan", "input": {"item": "all"}}]},
            {"text": "직접 할 일 날짜예요."},
        ]
    )
    ok(ask(api, pid, "실리콘도 제가 한다고 업체에 알려 주세요"))
    facts = facts_of(log[0])
    line = line_of(facts, "직접 할 일")
    # 날짜는 직접 할 일 도구 · 카드와 같은 말(계산 엔진, 공정표 '고객이 직접' 줄과 같은 값)
    items = results(log)[0]["items"]
    head, body = line.split(": ", 1)
    assert head == "직접 할 일(예상 공정표 기준)"
    assert body.split(" / ") == [
        *(f"{x['title']} {x['text']}" for x in items),
        "업체 사본: 들어감(마루와벽)",
    ]
    # 집 줄의 고른 일(집 카드와 같은 글)은 그대로 두고, 날짜 · 사본은 다음 줄에(집 줄 바로 뒤)
    rows = facts.split("\n")
    home_at = next(i for i, x in enumerate(rows) if x.startswith("집: "))
    assert "직접 할 일 페인트(문틀 · 몰딩), 실리콘 · 줄눈" in rows[home_at]
    assert rows[home_at + 1] == line
    # 도구 없이 답하는 턴도 그 날짜를 말할 수 있어요(날짜 문장이 숫자 검사로 빠지던 것)
    when = f"페인트는 {items[0]['text']}."
    script([{"text": when}])
    ev = ok(ask(api, pid, "페인트는 언제 칠해요?"))
    said = "".join(d["text"] for e, d, _ in ev if e == "token")
    assert when in said


def test_diy_line_before_any_request_and_without_chips(api, script):
    _token, pid = home(api)
    facts = turn_facts(api, script, pid)  # 고른 일이 없으면 줄 없음
    assert not any(x.startswith("직접 할 일") for x in facts.split("\n"))
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["light"]}).status_code == 200
    line = line_of(turn_facts(api, script, pid, "조명은요?"), "직접 할 일")
    assert line.startswith("직접 할 일(예상 공정표 기준): 조명 교체 ")
    assert line.endswith(S.COPY_NONE)


def test_diy_line_names_a_started_deal_to_tell_separately():
    tasks = calc_diy.plan(["paint"], {"dobae": (date(2026, 12, 14), date(2026, 12, 16))}, TODAY)
    g = diy_tools.Got(keys=["paint"], src="chips", phase="final", tasks=tasks)
    reach = DiyReach(live=[], dealt=["마루와벽"], missing=["마루와벽"], synced=True)
    line = S.diy_line(g, reach)
    assert line.startswith("직접 할 일(확정 공정표 기준): 페인트(문틀 · 몰딩) 칠하기 ")
    assert line.endswith(f"따로 알릴 업체: 마루와벽({DIY_DEALT_NOTE})")
    same = DiyReach(live=[], dealt=["마루와벽"], missing=[], synced=True)
    assert S.diy_line(g, same).endswith("업체 사본: 들어감(마루와벽)")
    assert S.diy_line(diy_tools.Got(keys=[], src="none", phase="none"), same) is None


def dealt_home(api) -> str:
    """집 정보(노원구 상계동)가 있는 공사에서 마루와벽(바로 확정 실측 · 견적서)을 확정까지(고객으로 로그인한 채)."""
    pid, visit, token = _requested_home(api)
    login(api, "maru@mitjip.test")
    assert answer(api, visit, instant=True).status_code == 200
    use(api, token)
    assert choose(api, pid, visit).json()["status"] == "booked"
    login(api, "maru@mitjip.test")
    quote(api, visit, 2_300_000)
    use(api, token)
    assert confirm(api, pid, visit).status_code == 200
    return pid


def test_after_the_deal_the_diy_card_says_the_confirmed_vendor_and_the_bell_names_the_job(
    api, script
):
    pid = dealt_home(api)
    ev, _log = call(
        script,
        api,
        pid,
        "실리콘도 제가 할래요",
        ("propose_home_info", {"fields": {"diy": ["silicone"]}}),
    )
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["summary"]["note"] == (
        "저장하면 공정표에 직접 할 일 날짜가 들어가요. 확정한 업체에도 바뀐 직접 할 일을 알려요"
    )
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200, r.text
    assert r.json()["result"]["text"] == "집 정보를 저장했어요 · 확정한 업체(마루와벽)에도 알렸어요"
    (n,) = notes("maru@mitjip.test", "visit_diy_changed")
    assert n["body"] == "고객이 직접 할 일을 바꿨어요: 실리콘 · 줄눈 · 노원구 상계동 도배"
    facts = turn_facts(api, script, pid, "업체에 갔어요?")
    assert line_of(facts, "직접 할 일").endswith("업체 사본: 들어감(마루와벽)")


def test_told_whom_and_home_note_words():
    from app.assistant.tools.propose import CHOSEN, REQUESTED, home_note, told_whom

    assert told_whom(["마루와벽"], {"마루와벽"}) == CHOSEN
    assert told_whom(["마루와벽", "결도배"], {"마루와벽"}) == REQUESTED
    assert told_whom([], set()) == REQUESTED
    base = "저장하면 공정표에 직접 할 일 날짜가 들어가요"
    assert home_note({"diy": ["paint"]}, True, [], live=True, who=CHOSEN) == (
        f"{base}. 확정한 업체에도 바뀐 직접 할 일을 알려요"
    )


def test_label_values_match_the_tool_requests(api, script):
    """턴 사실의 이름표 값은 취소 도구 결과(requests)와 같은 칸이라 같은 이름표예요."""
    w = two_requests(api)
    got = labels(turn_facts(api, script, w["pid"]))
    _ev, log = call(script, api, w["pid"], "취소해 줘", ("propose_visit_cancel", {"code": "other"}))
    (res,) = results(log)
    assert {x["vendor_name"]: x["ref"] for x in res["requests"]} == got
    assert all("id" not in x for x in res["requests"])  # 요청 id는 모델에 가지 않아요(이름표만)

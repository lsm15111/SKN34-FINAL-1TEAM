"""QA 2차에서 넘어온 반셀프 직접 할 일(갈래 C).

- c2: 실측을 요청한 뒤 직접 할 일 칩을 바꾸면 살아 있는 요청(요청함 ~ 견적서 옴 · 공사 시작 전 확정, QA r3 c6 리드
  결정)의 '업체에 알릴 것' 사본을 같이 고치고 업체에 앱 안 알림을 한 번 보내요. 공사가 시작된 확정만 고치지 않고
  '공사가 시작된 뒤라 업체에 따로 알려야 해요'를 돌려줘요(test_v4_r3_b1_diy).
  벽지 직접 구매(paper_buy)도 같은 길이에요(화면 PUT /diy · 비서 승인 카드 둘 다).
- c3 2 · 5번: 직접 할 일 도구 날짜는 공정표 '고객이 직접' 줄과 같은 값이고, 주말에만 되는 고객에게는 주말 날을 근거와
  같이 더해요. 사는 집이면 뒤에 할 일 마감이 공사 뒤 첫 주말까지예요(calc.diy diy_v3).
유료 호출 0회(무료 모드 · Claude 대본)."""

import json
import uuid
from datetime import date, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import diy as diy_tools
from app.assistant.tools.propose import home_note
from app.calc import diy as calc_diy
from app.refprice.holidays import HOLIDAYS
from app.visit.flow import DIY_DEALT_NOTE
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import TODAY, notes
from tests.test_deal import confirm, setup
from tests.test_v3_visit_kit import add, vendor
from tests.test_v3_visit_kit import ask as request_visit
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_diy import as_owner, block, chips, plan, remember
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login

D = date.fromisoformat
VENDORS = ("maru@mitjip.test", "gyeol@mitjip.test", "hangyeol@mitjip.test")


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


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


# ---- c2: 확정 전 요청 사본 · 업체 알림 ----


def test_chips_before_deal_update_live_requests_and_tell_each_vendor_once(api):
    _customer, pid, va, _vb, _vc = setup(api)  # 견적서 옴 둘 · 요청함 하나
    assert {x["diy"] == [] for x in query("select diy from visits")} == {True}
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["paper_buy", "light"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["diy"] == ["light", "paper_buy"] and out["notice"] is None
    assert sorted(out["told"]) == sorted(["마루와벽", "결도배", "한결인테리어"])
    assert {tuple(x["diy"]) for x in query("select diy from visits")} == {("light", "paper_buy")}
    for email in VENDORS:
        (n,) = notes(email, "visit_diy_changed")
        assert n["body"] == "고객이 직접 할 일을 바꿨어요: 조명 교체 · 벽지 직접 구매"
        assert n["link"].startswith("/vendor/requests/")
    # 같은 칩을 다시 저장하면 사본이 같아 알림이 더 가지 않아요
    again = api.put(f"/projects/{pid}/diy", json={"diy": ["light", "paper_buy"]}).json()
    assert again["told"] == [] and again["notice"] is None
    assert all(len(notes(e, "visit_diy_changed")) == 1 for e in VENDORS)
    # '없어요'로 바꾸면 사본도 비고, 알림은 바뀐 만큼 한 번 더
    assert api.put(f"/projects/{pid}/diy", json={"diy": []}).json()["told"]
    assert {tuple(x["diy"]) for x in query("select diy from visits")} == {()}
    bodies = [n["body"] for n in notes(VENDORS[0], "visit_diy_changed")]
    assert bodies[-1] == "고객이 직접 할 일을 바꿨어요: 없어요" and len(bodies) == 2
    # 업체 브리핑은 바뀐 사본을 봐요
    api.put(f"/projects/{pid}/diy", json={"diy": ["silicone"]})
    login(api, VENDORS[0])
    r = api.get(f"/vendor/assistant/briefs/{va}")
    assert r.status_code == 200, r.text
    assert r.json()["diy"] == ["실리콘 · 줄눈"]


def test_chips_after_deal_update_the_deal_copy_before_work_starts(api, script):
    """QA 3차 c6 리드 결정(11-22): 확정 뒤에도 공사 시작 전까지는 확정 업체 사본을 고치고 종 알림을 보내요(예전 기대:
    사본 그대로 · '확정 뒤라 따로 알려야 해요'). 공사가 시작된 뒤는 test_v4_r3_b1_diy가 봐요."""
    customer, pid, va, _vb, _vc = setup(api)
    assert confirm(api, pid, va).status_code == 200
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["silicone"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["told"] == ["마루와벽"] and out["notice"] is None
    rows = {str(x["id"]): x for x in query("select id, status, diy from visits")}
    assert (rows[va]["status"], rows[va]["diy"]) == ("chosen", ["silicone"])  # 확정 사본도 고쳐요
    (n,) = notes(VENDORS[0], "visit_diy_changed")
    assert n["body"] == "고객이 직접 할 일을 바꿨어요: 실리콘 · 줄눈"
    assert all(not notes(e, "visit_diy_changed") for e in VENDORS[1:])  # 닫힌 요청엔 안 가요
    login(api, VENDORS[0])
    assert api.get(f"/vendor/assistant/briefs/{va}").json()["diy"] == ["실리콘 · 줄눈"]
    # 직접 할 일 도구 결과: 업체 사본에 이미 들어 있어 따로 알리라고 하지 않아요(QA r3 c2 21턴 · c3)
    use(api, customer)
    log = script(
        [
            {"tool_calls": [{"id": "d", "name": "diy_plan", "input": {"item": "all"}}]},
            {"text": "실리콘은 공사 뒤에 하시면 돼요."},
        ]
    )
    ok(ask(api, pid, "직접 할 일 정리해 줘"))
    got = tool_result(log, 1)
    assert got["vendors"] == {
        "requests": ["마루와벽"],
        "notes": [diy_tools.REACH_LIVE, diy_tools.REACH_SYNCED],
    }
    assert DIY_DEALT_NOTE not in json.dumps(got, ensure_ascii=False)


def test_home_info_card_after_request_tells_live_vendors(api, script):
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    _token, pid = home(api)  # v3 집 정보가 있는 공사
    assert add(api, pid, vid).status_code == 201
    assert request_visit(api, pid, [vid]).status_code == 201
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"diy": ["paint"]}},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "문틀 페인트는 제가 칠할게요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["summary"]["note"] == (
        "저장하면 공정표에 직접 할 일 날짜가 들어가요. 실측을 요청한 업체에도 바뀐 직접 할 일을 알려요"
    )
    assert tool_result(log, 1)["vendors"] == {
        "requests": ["마루와벽"],
        "notes": [diy_tools.REACH_LIVE],
    }
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "executed"
    assert (
        done["result"]["text"] == "집 정보를 저장했어요 · 실측을 요청한 업체(마루와벽)에도 알렸어요"
    )
    assert query("select diy from visits")[0]["diy"] == ["paint"]
    (n,) = notes("maru@mitjip.test", "visit_diy_changed")
    assert n["body"] == "고객이 직접 할 일을 바꿨어요: 페인트(문틀 · 몰딩)"


def test_home_note_follows_where_the_change_reaches():
    base = "저장하면 공정표에 직접 할 일 날짜가 들어가요"
    paint, buy = {"diy": ["paint"]}, {"diy": ["paper_buy"]}
    assert home_note(paint, False, []) == f"{base}. 표준견적서는 그대로예요"
    assert home_note(buy, False, []) == f"{base}. 표준견적서에서 벽지 값을 빼요(고객 구매)"
    assert (
        home_note({"diy": []}, False, ["paper_buy"])
        == f"{base}. 표준견적서에 벽지 값을 다시 넣어요"
    )
    live = f"{base}. 실측을 요청한 업체에도 바뀐 직접 할 일을 알려요"
    assert home_note(paint, True, [], live=True) == live
    assert (
        home_note(paint, True, [], dealt=True)
        == f"{base}. 확정한 업체에는 채팅으로 따로 알려 주세요"
    )
    assert home_note(buy, True, [], live=True, dealt=True) == (
        f"{base}. 표준견적서에서 벽지 값을 빼요(고객 구매). 실측을 요청한 업체에도 바뀐 직접 할 일을 알려요. "
        "확정한 업체에는 채팅으로 따로 알려 주세요"
    )
    # 요청이 모두 닫혀 알릴 업체가 없으면 업체 말은 하지 않아요
    assert home_note(paint, True, []) == f"{base}. 표준견적서는 그대로예요"


# ---- c3: 공정표와 같은 날 · 주말 날 · 사는 집 ----

QA_WORK = {"dobae": (D("2026-12-14"), D("2026-12-16"))}  # 월 ~ 수(c3 확정 공정표)
QA_KW = {"dry": (D("2026-12-17"), D("2026-12-18")), "clean": (D("2026-12-19"), D("2026-12-19"))}


def _got(occupied: bool, free_src: str = "memory") -> diy_tools.Got:
    keys = ["light", "silicone"]
    today = D("2026-12-01")
    tasks = calc_diy.plan(keys, QA_WORK, today, occupied=occupied, **QA_KW)
    alt = calc_diy.plan(keys, QA_WORK, today, free="weekend", occupied=occupied, **QA_KW)
    return diy_tools.Got(
        keys=keys,
        src="chips",
        phase="final",
        tasks=tasks,
        occupied=occupied,
        free="weekend",
        free_src=free_src,
        alt={(t.key, t.step): t for t in alt},
    )


def test_weekend_customer_gets_plan_day_and_weekend_day_qa_c3():
    g = _got(occupied=True)
    pid = uuid.uuid4()
    card = diy_tools.list_card(pid, g).data
    # 공정표 날(12.17 목, 할 수 있는 첫날)이 앞이고, 주말에만 되면 12.19(토)도 같이(같은 사실을 두 값으로 말하지 않음)
    assert [x["label"] for x in card["checklist"]] == [
        "조명 교체 · 12월 17일(목) ~ 12월 20일(일) 사이에 해요 · 주말이면 12월 19일(토)도 돼요",
        "실리콘 · 줄눈 · 12월 17일(목) ~ 12월 20일(일) 사이에 해요 · 주말이면 12월 19일(토)도 돼요",
    ]
    assert card["lines"][0] == (
        "날짜는 확정 공정표 기준이에요. 주말에만 된다고 하셔서 주말 날도 같이 적었어요."
    )
    assert not any(
        "주말 · 공휴일이 없어요" in x for x in card["lines"]
    )  # 평일 하루를 비우라고 하지 않아요
    model = diy_tools.model_of(g)
    assert model["days"] == "weekend"
    assert model["basis"] == [diy_tools.DATES_NOTE, diy_tools.DAYS_NOTE["memory"]]
    light = model["items"][0]
    assert (light["start"], light["end"], light["day"]) == (
        D("2026-12-17"),
        D("2026-12-20"),
        D("2026-12-17"),
    )
    assert light["weekend"] == {
        "start": D("2026-12-19"),
        "end": D("2026-12-20"),
        "day": D("2026-12-19"),
        "fit": True,
        "note": None,
    }
    assert [f"{x['title']} · {x['text']}" for x in model["items"]] == [
        x["label"] for x in card["checklist"]
    ]  # 카드 말 = 모델 말
    # 이번 말로 주말이라고 했으면 근거 말이 달라요
    asked = diy_tools.list_card(pid, _got(occupied=True, free_src="asked")).data
    assert asked["lines"][0].endswith(diy_tools.WEEKEND_LINE["asked"])


def test_vacant_home_weekend_customer_hears_no_weekend_for_silicone():
    g = _got(occupied=False)
    card = diy_tools.list_card(uuid.uuid4(), g).data
    assert [x["label"] for x in card["checklist"]] == [
        "조명 교체 · 12월 17일(목) ~ 12월 19일(토) 사이에 해요 · 주말이면 12월 19일(토)도 돼요",
        "실리콘 · 줄눈 · 12월 17일(목) ~ 12월 18일(금) 사이에 해요 · 그 사이에 주말 · 공휴일이 없어요",
    ]
    assert f"실리콘 · 줄눈: {diy_tools.WHY_NOTE['no_free_day']}" in card["lines"]
    # 공정표 날이 이미 주말이면 주말 말을 붙이지 않아요
    (t,) = calc_diy.plan(["light"], {"dobae": (D("2026-12-15"), D("2026-12-18"))}, D("2026-12-01"))
    assert t.day == D("2026-12-19") and diy_tools.alt_text(t, t) is None
    assert diy_tools.when_text(t, t) == diy_tools.when_text(t)


def test_tool_dates_match_the_final_plan_for_a_lived_home(api):
    """확정 공정표(사는 집) · 기억 '주말에만': 도구 날짜 = 공정표 '고객이 직접' 줄, 주말 날은 따로."""
    from tests.test_v4_assistant_diy import dobae_in

    monday = 7 + (7 - (TODAY + timedelta(days=7)).weekday()) % 7  # 일주일 뒤 이후 첫 월요일
    _token, pid, _did = dobae_in(api, monday)
    query("update projects set occupied = true where id = $1", uuid.UUID(pid))
    chips(api, pid, ["light", "silicone"])
    remember(api, pid, "avail_days", "맞벌이라 주말에만 시간이 돼요")
    p = plan(api, pid)
    assert p["kind"] == "final"
    rows = {b["label"]: b for b in p["blocks"] if b["kind"] == "diy"}
    end = D(block(p, "work", "dobae")["end"])

    async def go(s, u):
        g = await diy_tools.gather(s, u, uuid.UUID(pid), TODAY)
        return diy_tools.model_of(g), diy_tools.list_card(uuid.UUID(pid), g).data

    model, card = as_owner(api, pid, go)
    assert model["days"] == "weekend" and diy_tools.DAYS_NOTE["memory"] in model["basis"]
    items = {x["kind"]: x for x in model["items"]}
    for key, label in (("light", "조명 교체"), ("silicone", "실리콘 · 줄눈")):
        x, row = items[key], rows[label]
        assert (str(x["start"]), str(x["end"])) == (row["start"], row["end"])  # 공정표 줄과 같은 값
        wk = x["weekend"]
        assert wk["fit"] and wk["note"] is None  # 사는 집: 공사 뒤 첫 주말도 돼요
        assert wk["day"].weekday() >= 5 or wk["day"] in HOLIDAYS
        assert x["start"] <= wk["day"] <= x["end"]
    assert items["silicone"]["end"] >= calc_diy.first_sunday(end + timedelta(days=1))
    assert [x["label"] for x in card["checklist"]] == [
        f"{x['title']} · {x['text']}" for x in model["items"]
    ]

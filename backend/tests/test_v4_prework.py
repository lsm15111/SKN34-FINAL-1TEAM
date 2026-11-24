"""갈래 P2 도배 전 점검: 앞 공사 답(모은 조건 prework.*: 단추 값만 · DB CHECK · 남의 공사 404) · 점검 카드 단추 →
승인 카드(prework) → 사람이 누르면 저장 · prework_brief 도구(Claude 대본, 롤 수는 표준견적서와 같은 계산 엔진 값).
유료 호출 0회."""

import json
import uuid
from decimal import Decimal

import asyncpg
import pytest

from app.agent import llm
from app.assistant import policy, tools
from app.assistant.tools import diy as diy_tools
from app.assistant.tools import prework as prework_tools
from app.auth.models import User
from app.db import SessionLocal
from app.project import prework
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import signup
from tests.test_project import body as project_body
from tests.test_v3_visit_kit import customer
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_diy import as_owner, chips
from tests.test_v4_assistant_free import cards_of, said
from tests.test_v4_assistant_new_tools import call, results
from tests.test_v4_assistant_nudges import run
from tests.test_v4_assistant_turns import ask, home, ok

D = Decimal
Check = asyncpg.exceptions.CheckViolationError
ROW_SQL = (
    "insert into project_conditions (id, project_id, trade, key, value)"
    " values ($1, $2::uuid, 'prework', $3, $4)"
)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def saved(pid: str) -> dict[str, str]:
    rows = query(
        "select key, value, trade from project_conditions"
        " where project_id = $1::uuid and key like 'prework.%'",
        pid,
    )
    assert all(r["trade"] == "prework" for r in rows)
    return {r["key"].removeprefix("prework."): r["value"] for r in rows}


def press(api, pid: str, *choice: str, text: str = "앞 공사 답을 골랐어요") -> list:
    """점검 카드 단추 꼴(context.choice 'prework.<공정>:<값>', 여럿)로 턴을 보낸다."""
    ctx = {"card_id": prework_tools.card_id(uuid.UUID(pid)), "choice": list(choice)}
    return ok(ask(api, pid, text, context=ctx))


def proposed(ev) -> list[dict]:
    return [a for a in acts(ev) if a["status"] == "proposed"]


def brief_of(api, pid: str):
    async def go(s, u):
        return await prework_tools.brief(s, u, uuid.UUID(pid), today_seoul())

    return as_owner(api, pid, go)


# ---- 약속 · DB CHECK(단추 값만) ----


def test_contract_and_db_check_take_button_values_only(api):
    _, pid = customer(api)
    assert list(prework.PREWORK) == ["mokgong", "electric", "film", "floor"]
    assert prework.STATES == {"done": "끝났어요", "todo": "아직이에요", "none": "안 해요"}
    query(ROW_SQL, uuid.uuid4(), pid, "prework.mokgong", "done")
    bad = [
        ("prework.electric", "yes"),
        ("prework.film", "끝났어요"),  # 화면 말이 아니라 단추 값만
        ("prework.roof", "done"),  # 모르는 공정
        ("prework.", "done"),
    ]
    for key, value in bad:
        with pytest.raises(Check):
            query(ROW_SQL, uuid.uuid4(), pid, key, value)
    query(ROW_SQL, uuid.uuid4(), pid, "mokgong.doors", "문틀까지")  # 다른 칸은 그대로 받아요
    assert saved(pid) == {"mokgong": "done"}
    # 지문: 공정 순서 번호 + 값 첫 글자
    assert prework.prework_ver({}) == "p"
    assert prework.prework_ver({"floor": "none", "mokgong": "done"}) == "p0d3n"
    for answers in ({"mokgong": "yes"}, {"roof": "done"}):
        with pytest.raises(ValueError):
            prework.clean(answers)


def test_set_prework_overwrites_only_given_trades_and_shows_chips(api):
    _, pid = customer(api)

    async def go(s, _user):
        a = await prework.set_prework(s, uuid.UUID(pid), {"film": "none", "mokgong": "todo"})
        b = await prework.set_prework(s, uuid.UUID(pid), {"mokgong": "done"})
        await s.commit()
        return a, b

    a, b = as_owner(api, pid, go)
    assert list(a.items()) == [("mokgong", "todo"), ("film", "none")]  # 공정 순서
    assert b == {"mokgong": "done", "film": "none"} == saved(pid)
    # 모은 조건 화면 칩은 화면 말(코드 값 아님)
    r = api.get(f"/projects/{pid}/conditions")
    assert r.status_code == 200, r.text
    got = {(c["label"], c["value"]) for c in r.json() if c["key"].startswith("prework.")}
    assert got == {("앞 공사 · 목공", "끝났어요"), ("앞 공사 · 필름", "안 해요")}


# ---- 카드 단추 → 승인 카드 → 사람이 누르면 저장(고정 선 1) ----


def test_buttons_make_one_approval_card_and_save_only_on_approve(api):
    _, pid = customer(api)
    ev = press(api, pid, "prework.mokgong:done", "prework.film:none", "prework.floor:todo")
    assert ev[-1][1]["mode"] == "free"
    (a,) = proposed(ev)
    assert (a["kind"], a["summary"]["title"]) == ("prework", "앞 공사 답 저장")
    assert a["summary"]["rows"] == [
        {"label": "목공", "value": "끝났어요", "sub": "지금 고르지 않음"},
        {"label": "필름", "value": "안 해요", "sub": "지금 고르지 않음"},
        {"label": "바닥", "value": "아직이에요", "sub": "지금 고르지 않음"},
    ]
    assert a["summary"]["note"] == prework_tools.PROPOSE_NOTE
    assert "승인 카드" in said(ev)
    assert saved(pid) == {}  # 누르기 전에는 저장하지 않아요
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert r.json()["result"]["text"] == "앞 공사 답을 저장했어요"
    assert saved(pid) == {"mokgong": "done", "film": "none", "floor": "todo"}
    # 같은 답을 다시 누르면 새 카드가 없어요
    ev = press(api, pid, "prework.mokgong:done")
    assert not proposed(ev) and prework_tools.NO_CHANGE in said(ev)
    # 하나만 바꾸면 바뀐 줄만 싣고 지금 값을 같이 보여요
    (b,) = proposed(press(api, pid, "prework.mokgong:done", "prework.floor:done"))
    assert b["summary"]["rows"] == [
        {"label": "바닥", "value": "끝났어요", "sub": "지금 아직이에요"}
    ]
    # 거절하면 저장하지 않아요
    r = api.post(f"/assistant/actions/{b['action_id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert saved(pid)["floor"] == "todo"


def test_unknown_button_values_are_dropped_and_words_are_not_saved(api, script):
    _, pid = customer(api)
    ev = press(api, pid, "prework.mokgong:yes", "prework.roof:done", text="목공 끝났어요")
    assert not proposed(ev) and saved(pid) == {}
    # 앞 공사 답을 만드는 LLM 제안 도구는 없어요(단추로 고른 값만 저장)
    assert not [n for n, t in tools.REGISTRY.items() if t.kind == "propose" and "prework" in n]
    # 켜짐(대본): 코드가 승인 카드를 먼저 만들고 모델에는 화면 말로 알려요. 모르는 값은 버려요
    log = script([{"text": "카드를 확인하고 눌러 주세요."}])
    ev = press(api, pid, "prework.electric:done", "prework.mokgong:yes")
    (a,) = proposed(ev)
    assert a["summary"]["rows"] == [
        {"label": "전기", "value": "끝났어요", "sub": "지금 고르지 않음"}
    ]
    sent = json.dumps(log[0]["messages"], ensure_ascii=False)
    assert "(카드에서 고름: 앞 공사 전기: 끝났어요)" in sent and "prework.mokgong:yes" not in sent
    assert "승인 카드를 만들었어요" in sent


def test_pressed_turn_gives_the_model_the_card_why_for_pending_trades(api, script):
    # QA r10 c3 T2: 단추 턴 모델은 카드 근거를 못 받아 '바닥 공사는 도배 전에 마쳐야 해요'로 단정했어요
    why = prework_tools.WHY["floor"]
    assert "마루는 도배 전" in why and "장판은 도배 뒤" in why and "\n" not in why
    _, pid = customer(api)
    log = script([{"text": "카드를 확인하고 눌러 주세요."}])
    press(api, pid, "prework.mokgong:done", "prework.floor:todo")
    sent = json.dumps(log[0]["messages"], ensure_ascii=False)
    assert why in sent  # 아직인 공정은 카드 근거 그대로
    assert prework_tools.WHY["mokgong"] not in sent  # 끝난 공정은 고른 값만


def test_old_card_is_stale_when_answers_changed_on_screen(api):
    _, pid = customer(api)
    (a,) = proposed(press(api, pid, "prework.mokgong:todo"))
    assert approve(api, a["action_id"]).status_code == 200
    (b,) = proposed(press(api, pid, "prework.mokgong:done"))
    # 모은 조건 화면에서 칩을 지웠어요(앞 공사 답이 바뀜): 옛 카드는 저장하지 않아요
    assert api.delete(f"/projects/{pid}/conditions/prework.mokgong").status_code == 200
    r = approve(api, b["action_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale", r.text
    assert saved(pid) == {}


def test_other_customers_get_404(api):
    _, pid = customer(api)
    (a,) = proposed(press(api, pid, "prework.film:done"))
    signup(api, "other@mitjip.test")
    assert approve(api, a["action_id"]).status_code == 404
    r = ask(api, pid, "필름 끝났어요", context={"choice": ["prework.film:done"]})
    assert r.status_code == 404
    uid = query("select id from users where email = 'other@mitjip.test'")[0]["id"]

    async def go():
        async with SessionLocal() as s:
            await prework_tools.brief(s, await s.get(User, uid), uuid.UUID(pid), today_seoul())

    with pytest.raises(AppError) as e:
        run(api, go)
    assert e.value.status == 404
    assert saved(pid) == {}


def test_answers_save_after_the_visit_request_lock(api):
    _, pid = customer(api)
    query("update projects set locked_at = now() where id = $1::uuid", pid)
    (a,) = proposed(press(api, pid, "prework.mokgong:none"))
    assert approve(api, a["action_id"]).status_code == 200
    assert saved(pid) == {"mokgong": "none"}
    card, model = brief_of(api, pid)
    assert card.data["next"] == prework_tools.NEXT_LOCKED and card.data["next_say"] is None
    assert model["rows"][0] == {
        "trade": "목공",
        "state": "안 해요",
        "why": prework_tools.WHY["mokgong"],
        "note": None,
    }


# ---- prework_brief 도구 · 점검 카드 ----


def test_brief_tool_card_rows_tasks_paper_and_model_values(api, script):
    _, pid = customer(api)
    chips(api, pid, ["paint", "light", "paper_buy"])
    (a,) = proposed(press(api, pid, "prework.electric:done", "prework.floor:todo"))
    assert approve(api, a["action_id"]).status_code == 200
    ev, log = call(script, api, pid, "실측 요청 전에 뭐 점검해요?", ("prework_brief", {}))
    (card,) = cards_of(ev, "prework_check")
    d = card["data"]
    assert card["card_id"] == f"prework-{pid}" and card["say"] == prework_tools.SAY
    assert [(r["key"], r["label"], r["state"]) for r in d["rows"]] == [
        ("mokgong", "목공", None),
        ("electric", "전기", "done"),
        ("film", "필름", None),
        ("floor", "바닥", "todo"),
    ]
    assert all(r["why"] == prework_tools.WHY[r["key"]] for r in d["rows"])

    # 도배 전에 끝낼 직접 할 일만(조명 교체는 도배 뒤), 날짜 말은 공정표 '고객이 직접' 줄과 같은 값
    async def got_tasks(s, u):
        g = await diy_tools.gather(s, u, uuid.UUID(pid), today_seoul())
        return [(t.name, g.when(t)) for t in g.tasks if t.kind == "before"]

    want = as_owner(api, pid, got_tasks)
    assert [(t["label"], t["when"]) for t in d["tasks"]] == want
    assert {x for x, _ in want} == {"페인트(문틀 · 몰딩) 칠하기", "벽지 사서 받아 두기"}
    # 벽지 직접 구매: 롤 수는 표준견적서 화면 롤 수와 같은 계산 엔진 값
    std = api.get(f"/projects/{pid}/standard").json()
    t = next(x for x in std["trades"] if x["trade"] == "dobae")
    lines = {ln["key"]: ln for ln in t["lines"]}
    p = d["paper"]
    assert (p["name"], p["size"], p["count"]) == (
        t["rolls"]["name"],
        t["rolls"]["size"],
        t["rolls"]["count"],
    )
    assert D(p["area_m2"]) == D(lines["wall"]["qty"]) + D(lines["ceiling"]["qty"])
    assert p["loss"] == p["count"] - p["base"] > 0 and (p["spare_min"], p["spare_max"]) == (1, 2)
    mats = {m["name"]: m for m in p["materials"]}
    assert mats["풀"]["state"] == mats["부직포"]["state"] == "included"
    assert mats["풀"]["line"] == lines["material"]["name"]
    assert mats["초배지"]["state"] is None  # 표준견적서에 초배지 줄이 없어 업체 확인
    assert mats["부직포"]["amount"] is None and mats["풀"]["amount"].startswith("약 ")
    # 아직인 앞 공사가 있어 다음 걸음 앞에 알릴 말이 붙어요
    assert d["next"] == f"{prework_tools.NEXT_TODO} {prework_tools.NEXT_VISIT}"
    assert (d["next_label"], d["next_say"]) == (prework_tools.NEXT_LABEL, prework_tools.NEXT_SAY)
    # 모델 값(허용 칸만): 답 · 롤 수 · 단추로만 저장된다는 안내
    (got,) = results(log)
    assert got == json.loads(json.dumps(policy.to_model(got), default=str))
    assert [(r["trade"], r["state"]) for r in got["rows"]] == [
        ("목공", "모름"),
        ("전기", "끝났어요"),
        ("필름", "모름"),
        ("바닥", "아직이에요"),
    ]
    assert got["paper"]["count"] == p["count"] and got["note"] == prework_tools.BRIEF_NOTE
    labels = {r["label"]: r for r in got["paper"]["rows"]}
    assert labels["면적만 덮는 롤"]["count"] == p["base"]
    assert labels["자투리 몫(필요 롤에 포함)"]["count"] == p["loss"]
    assert {m["name"]: m["state"] for m in got["paper"]["items"]} == {
        "풀": "포함",
        "초배지": prework_tools.CHECK_STATE,
        "부직포": "포함",
    }
    assert [x["title"] for x in got["items"]] == [x for x, _ in want]


def test_paper_rolls_show_before_paper_buy_is_saved(api, script):
    # QA r10 c3 T1: '벽지는 제가 사요' 턴의 점검 카드에 롤 수가 없었어요(벽지 직접 구매 승인 전)
    _, pid = home(api)  # 집 정보가 있는 공사(직접 할 일 승인 카드를 만들 수 있어요)
    std = api.get(f"/projects/{pid}/standard").json()
    rolls = next(x for x in std["trades"] if x["trade"] == "dobae")["rolls"]["count"]
    ev, log = call(
        script,
        api,
        pid,
        "실측 요청하기 전에 뭘 챙겨야 해요? 벽지는 제가 사요",
        ("prework_brief", {}),
    )
    (card,) = cards_of(ev, "prework_check")
    assert card["data"]["paper"]["count"] == rolls  # 계산 엔진 값(표준견적서 롤 수와 같음)
    assert results(log)[0]["paper"]["count"] == rolls
    # 벽지를 직접 산다는 말이 없으면 그대로 없어요
    ev, _ = call(script, api, pid, "도배 전 점검 보여 줘", ("prework_brief", {}))
    assert cards_of(ev, "prework_check")[0]["data"]["paper"] is None
    # 벽지 직접 구매를 넣는 집 정보 승인 카드가 열려 있으면 보여요(저장 전)
    diy = {"fields": {"diy": ["paper_buy"]}}
    call(script, api, pid, "벽지 직접 구매로 넣어 주세요", ("propose_home_info", diy))
    ev, _ = call(script, api, pid, "도배 전 점검 보여 줘", ("prework_brief", {}))
    assert cards_of(ev, "prework_check")[0]["data"]["paper"]["count"] == rolls
    got = query("select status from assistant_actions where kind = 'home_info'")
    assert [r["status"] for r in got] == ["proposed"]


def test_brief_without_chips_mokgong_project_and_no_dobae(api, script):
    signup(api, "mok@mitjip.test")
    both = api.post("/projects", json=project_body()).json()["id"]  # 도배 + 목공
    card, model = brief_of(api, both)
    assert card.data["tasks"] == [] and card.data["paper"] is None  # 직접 할 일을 고르지 않음
    assert card.data["rows"][0]["note"] == prework_tools.MOKGONG_PICKED
    assert all(r["state"] == prework_tools.NOT_ASKED for r in model["rows"])
    assert card.data["next"] == prework_tools.NEXT_VISIT and "items" not in model
    mok = {"mokgong": {"spaces": ["a"], "items": ["molding", "base"]}}
    only = api.post("/projects", json=project_body(trades=mok)).json()["id"]
    ev, log = call(script, api, only, "도배 전 점검", ("prework_brief", {}))
    assert not cards_of(ev, "prework_check") and results(log)[0]["error"] == "no_dobae"

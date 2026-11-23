"""v4 반셀프 직접 할 일: 칩(project.diy, 시험은 set_diy로 넣어요) → 공정표 '고객이 직접' 줄 · 오늘 할 일(7일 안 마감) ·
공사 1주 전 · 공사 전날 · 실측 요청 '업체에 알릴 것'(승인하면 요청에 고정) · 업체 브리핑(자료) · diy_plan 도구 ·
무료 모드('직접 할 일 알려 줘' · '페인트 언제 칠해요?'). 원본은 칩뿐이에요(기억 diy 글은 쓰지 않아요, QA r3 s6).
유료 호출 0회(Claude 대본)."""

import json
import re
import uuid
from datetime import date, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant.runtime import RefTable
from app.assistant.tools import cards
from app.assistant.tools import diy as diy_tools
from app.assistant.tools import vendor as vendor_tools
from app.auth.models import User
from app.calc import diy as calc_diy
from app.db import SessionLocal
from app.knowledge import diy as know
from app.project.diy import DIY, set_diy
from app.shared.clock import now_utc, today_seoul
from app.visit.models import DIY_KEYS
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import SEEN0, days, propose, ready
from tests.test_v3_visit_kit import customer
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_free import cards_of, said, two_vendors
from tests.test_v4_assistant_nudges import run
from tests.test_v4_assistant_turns import ask, ok
from tests.test_visit_inbox import login

TODAY = today_seoul()
D = date.fromisoformat
SELF = "고객이 직접"


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


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def chips(api, pid: str, keys: list[str]) -> list[str]:
    """칩 저장 약속(project.diy.set_diy)으로 직접 할 일을 넣는다(기본 정보 갈래의 화면 대신)."""

    async def go():
        async with SessionLocal() as s:
            got = await set_diy(s, uuid.UUID(pid), keys)
            await s.commit()
            return got

    return run(api, go)


def as_owner(api, pid: str, fn):
    """그 공사 고객으로 새 세션에서 fn(s, user)를 부른다(앱 루프)."""
    uid = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]

    async def go():
        async with SessionLocal() as s:
            return await fn(s, await s.get(User, uid))

    return run(api, go)


def plan(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/plan")
    assert r.status_code == 200, r.text
    return r.json()


def block(p: dict, kind: str, trade: str | None = None) -> dict:
    (b,) = [x for x in p["blocks"] if x["kind"] == kind and (trade is None or x["trade"] == trade)]
    return b


def day_of(p: dict, d: date) -> dict:
    (x,) = [x for x in p["days"] if x["day"] == d.isoformat()]
    return x


def dobae_in(api, after: int) -> tuple[str, str, str]:
    """도배를 마루와벽으로 확정하고 오늘 + after일 뒤 첫 일하는 날부터 3일을 수락한 집(확정 공정표).
    (고객 토큰, 공사 id, 확정 id). 고객으로 로그인해 있다."""
    token, pid, did, _ = ready(api)
    x = propose(api, did, *days(after)).json()["proposal"]["id"]
    use(api, token)
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0)
    assert r.status_code == 200, r.text
    return token, pid, did


def remember(api, pid: str, key: str, value: str) -> None:
    """기억 한 줄(근거는 이 공사 대화의 고객 메시지). 무료 턴으로 메시지를 만든 뒤 넣는다."""
    ok(ask(api, pid, value))
    (msg,) = query(
        "select id, chat_id from chat_messages where role = 'user' order by created_at desc limit 1"
    )
    uid = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    query(
        "insert into assistant_memory (id, user_id, key, value, evidence_message_id, evidence_quote)"
        " values ($1, $2, $3, $4, $5, $4)",
        uuid.uuid4(),
        uid,
        key,
        value,
        msg["id"],
    )


# ---- 지식 묶음 · 약속 ----


def test_knowledge_bundle_matches_chip_contract():
    assert (
        list(DIY) == list(calc_diy.KEYS) == list(DIY_KEYS)
    )  # 칩 · 계산 엔진 · 요청 사본 키가 같다
    for k, label in DIY.items():
        it = know.item(k)
        assert it.label == label and it.when and it.tools and it.cautions
        texts = [it.when, it.why, *it.how, *it.tools, *it.cautions, *it.living, *it.pet]
        assert not any(re.search(r"\d", x) for x in texts), k  # 정해 둔 글에 숫자 · 금액 없음
        assert all(x.endswith("요.") for x in [it.when, *it.how, *it.cautions]), k
        assert any(src.kind in ("public", "maker") for src in it.sources), k
        # 벽지 직접 구매(diy_know_v2)의 제조사 자료는 2026-11-22에 확인했어요
        assert all(
            src.checked in ("2026-11-21", "2026-11-22") and src.url.startswith("https://")
            for src in it.sources
        )
    assert "차단기" in " ".join(know.item("outlet").cautions)  # 전기는 차단기부터
    assert know.book().version == "diy_know_v2"


# ---- 공정표 '고객이 직접' 줄 ----


def test_expected_plan_gets_self_rows_without_duplicate_clean(api):
    _, pid = customer(api)
    before = plan(api, pid)
    assert before["kind"] == "expected" and not [b for b in before["blocks"] if b["kind"] == "diy"]
    assert chips(api, pid, ["clean", "outlet", "paint"]) == ["paint", "outlet", "clean"]
    p = plan(api, pid)
    dobae = block(p, "work", "dobae")
    start, end = D(dobae["start"]), D(dobae["end"])
    diy = [b for b in p["blocks"] if b["kind"] == "diy"]
    # 도배만 맡긴 집은 목공 날짜가 없어 페인트 시작이 '목공이 끝난 뒤'(calc.diy diy_v4)라 줄은 마감 날 하루예요
    assert [b["label"] for b in diy] == [
        "페인트(문틀 · 몰딩) 칠하기 · 목공이 끝난 뒤 · 마감", "콘센트 · 스위치 덮개 떼기",
        "콘센트 · 스위치 새 커버 달기",
    ]  # fmt: skip
    paint, off, on = diy
    # 칠하고 사흘을 비우게 도배 나흘 전까지(calc.diy diy_v2)
    assert (
        D(paint["start"]) == D(paint["end"]) == start - timedelta(days=calc_diy.PAINT_DRY_DAYS + 1)
    )
    assert (D(off["start"]), D(off["end"])) == (
        start - timedelta(days=3),
        start - timedelta(days=1),
    )
    assert D(on["start"]) == end + timedelta(days=1)
    # 날 칸: 페인트 마감 날(공정표 앞)은 diy 날로 더하고, 새 커버 날은 자연 건조 날에 이름만 더한다
    d = day_of(p, D(paint["end"]))
    assert d["kind"] == "diy" and d["names"] == [f"페인트(문틀 · 몰딩) 칠하기 · {SELF}"]
    d = day_of(p, end + timedelta(days=1))
    assert d["kind"] == "dry" and d["names"][-1] == f"콘센트 · 스위치 새 커버 달기 · {SELF}"
    # 입주 청소는 원래 '고객이 직접' 줄 하나뿐이고, 업체 공사 · 기간은 그대로
    assert sum("입주 청소" in n for x in p["days"] for n in x["names"]) == 1
    assert [b for b in p["blocks"] if b["kind"] != "diy"] == before["blocks"]
    assert (p["start"], p["end"], p["work_days"]) == (
        before["start"],
        before["end"],
        before["work_days"],
    )
    # '없어요'면 줄이 없다
    chips(api, pid, [])
    assert not [b for b in plan(api, pid)["blocks"] if b["kind"] == "diy"]


def test_final_plan_card_today_rows_and_prep_lists(api):
    _, pid, did = dobae_in(api, 5)
    chips(api, pid, ["paint", "outlet", "light"])
    p = plan(api, pid)
    assert p["kind"] == "final"
    start = D(block(p, "work", "dobae")["start"])
    paint_end, off_end = start - timedelta(days=4), start - timedelta(days=1)  # diy_v2: 사흘 비움
    # 비서 공정표 카드(확정)에 같은 꼴 줄이 보여요
    ev = ok(ask(api, pid, "공정표 보여 줘"))
    (card,) = cards_of(ev, "schedule")
    cells = {x["day"]: x["am"] for x in card["data"]["days"]}
    assert cells[paint_end.isoformat()] == f"페인트(문틀 · 몰딩) 칠하기 · {SELF}"
    assert cells[off_end.isoformat()] == f"콘센트 · 스위치 덮개 떼기 · {SELF}"
    # 오늘 할 일: 마감이 7일 안인 직접 할 일(페인트 · 덮개 떼기), 단추는 방법 묻기
    today = api.get("/assistant/today", params={"project_id": pid}).json()
    rows = {x["id"]: x for x in today["todo"]}
    assert rows["diy-paint"]["title"] == f"페인트(문틀 · 몰딩) 칠하기 · {SELF}"
    assert rows["diy-paint"]["sub"].startswith(f"{paint_end.month:02d}.{paint_end.day:02d}(")
    assert rows["diy-outlet-off"]["action"]["say"] == "콘센트 · 스위치 커버 언제 · 어떻게 해요?"
    assert "diy-light" not in rows  # 도배 뒤 일은 아직 마감이 멀어요
    # 공사 1주 전 할 일(prep_week 카드) · 공사 전 할 일 도구가 같은 체크 칸을 더해요
    from app.assistant.tools import aftercare as aftercare_tools

    prep = as_owner(api, pid, lambda s, u: aftercare_tools.prep_card(s, u, uuid.UUID(pid), TODAY))
    labels = [x["label"] for x in prep.data["checklist"]]
    # 목공 날짜가 없는 집이라 시작은 '목공이 끝난 뒤'(calc.diy diy_v4)예요
    assert (
        f"페인트(문틀 · 몰딩) 칠하기 · 목공이 끝난 뒤 ~ {diy_tools.ko_day(paint_end)} 사이에 해요 · {SELF}"
        in labels
    )
    assert any(x.startswith("조명 교체 · ") and x.endswith(SELF) for x in labels)
    assert any("관리사무소" in x for x in labels)  # 원래 공사 전 할 일은 그대로
    # 공사 전날(시작 하루 전): 덮개 떼기는 오늘까지, 페인트는 끝냈는지 확인, 조명은 공사 뒤
    eve = start - timedelta(days=1)

    async def eve_card(s, u):
        base = cards.prep_card(f"prep-{did}", ["dobae"])
        return await diy_tools.eve_card(s, u, uuid.UUID(pid), eve, base)

    got = as_owner(api, pid, eve_card)
    labels = [x["label"] for x in got.data["checklist"]]
    assert f"콘센트 · 스위치 덮개 떼기 · 오늘까지 해요 · {SELF}" in labels
    assert f"페인트(문틀 · 몰딩) 칠하기 · 끝냈는지 확인해요 · {SELF}" in labels
    assert any(x.startswith("조명 교체 · ") for x in labels)
    assert diy_tools.SAFETY in got.data["lines"]
    assert "벽 앞 가구 옮기기" in labels  # 공정 준비물은 그대로


def test_reminders_need_final_plan(api):
    _, pid = customer(api)
    chips(api, pid, ["paint"])
    today = api.get("/assistant/today", params={"project_id": pid}).json()
    assert not [
        x for x in today["todo"] if x["id"].startswith("diy-")
    ]  # 예상 공정표로는 챙기지 않아요


# ---- 업체에 알리기 ----


def test_visit_request_tells_vendor_and_fixes_list_on_request(api):
    pid, _ = two_vendors(api)
    chips(api, pid, ["outlet", "paint"])
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    ref = picks["data"]["picks"][0]["ref"]
    ev = ok(ask(api, pid, "여기에 요청할래요", context={"choice": f"visit_request:{ref}"}))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    row = {
        "label": "업체에 알릴 것",
        "value": "고객이 직접 해요 — 페인트(문틀 · 몰딩) · 콘센트 · 스위치 커버",
    }
    assert {k: v for k, v in a["summary"]["rows"][-1].items() if k in row} == row
    (pl,) = query("select payload from assistant_actions where id = $1", uuid.UUID(a["action_id"]))
    payload = json.loads(pl["payload"]) if isinstance(pl["payload"], str) else pl["payload"]
    assert payload["diy"] == ["paint", "outlet"]
    # 승인하면 고객이 본 목록이 요청에 고정돼요. 승인 전에 칩을 바꾸면 보내지 않고 새 판 카드를 만들어요(QA r3 s6
    # 리드 결정 11-22, 예전 기대는 '옛 목록 그대로 보냄' → test_v4_r3_b1_diy가 봐요)
    r = approve(api, a["action_id"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (v,) = query("select id, vendor_id, diy from visits")
    assert v["diy"] == ["paint", "outlet"]
    # 업체 브리핑: 카드 칸 · 모델 값(자료 상자)
    email = query("select email from users where id = $1", v["vendor_id"])[0]["email"]
    login(api, email)
    r = api.get(f"/vendor/assistant/briefs/{v['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["diy"] == ["페인트(문틀 · 몰딩)", "콘센트 · 스위치 커버"]

    async def brief(s, _u):
        vendor = await s.get(User, v["vendor_id"])
        refs = RefTable(uuid.uuid4())
        _card, model, *_ = await vendor_tools.brief(
            s, vendor, v["id"], TODAY, now_utc(), refs, propose_window=False
        )
        return model

    model = as_owner(api, pid, brief)
    sent = policy.to_model(model)
    assert sent["diy"] == {
        policy.DATA_KEY: "고객이 직접 할 일: 페인트(문틀 · 몰딩) · 콘센트 · 스위치 커버"
    }


def test_visit_request_without_chips_has_no_row(api):
    pid, _ = two_vendors(api)
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    ref = picks["data"]["picks"][0]["ref"]
    ev = ok(ask(api, pid, "여기에 요청할래요", context={"choice": f"visit_request:{ref}"}))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert all(x["label"] != "업체에 알릴 것" for x in a["summary"]["rows"])
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    assert query("select diy from visits")[0]["diy"] == []


# ---- 무료 모드 · 도구 ----


def test_free_mode_list_and_paint_when(api):
    _, pid = customer(api)
    chips(api, pid, ["paint", "outlet"])
    p = plan(api, pid)
    paint_end = D(next(b for b in p["blocks"] if b["label"].startswith("페인트"))["end"])
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    (card,) = [c for c in cards_of(ev, "knowledge") if c["data"]["title"] == "직접 할 일"]
    labels = [x["label"] for x in card["data"]["checklist"]]
    assert labels[0].startswith("페인트(문틀 · 몰딩) 칠하기 · ")
    assert labels[0].endswith(f"{diy_tools.ko_day(paint_end)} 사이에 해요")
    assert said(ev).startswith("고르신 직접 할 일이에요. 날짜는 예상 공정표 기준이에요.")
    assert "차단기" in " ".join(card["data"]["lines"])
    # 문틀 페인트 시기(L18): 때 · 날짜 · 방법 · 준비물 카드
    ev = ok(ask(api, pid, "문틀 페인트는 제가 칠하려는데 언제 하면 돼요?"))
    (card,) = cards_of(ev, "knowledge")
    assert card["data"]["title"] == "페인트(문틀 · 몰딩) · 직접 할 때"
    assert card["data"]["lines"][0] == "목공이 끝난 뒤, 도배 전에 칠하고 다 말려요."
    assert [x["label"] for x in card["data"]["checklist"]][:2] == ["사포", "마스킹 테이프 · 비닐"]
    assert "KCC" in card["data"]["source"]
    text = said(ev)
    assert (
        "도배 전에" in text
        and diy_tools.ko_day(paint_end) in text
        and "확인하지 못했어요" not in text
    )
    # 콘센트 '옮기기'는 직접 할 일(커버)이 아니라 원래 길잡이로
    ev = ok(ask(api, pid, "콘센트 옮기는 건 제가 따로 전기 기사를 부르려고요. 언제 해야 해요?"))
    assert not [c for c in cards_of(ev, "knowledge") if "직접 할 때" in c["data"]["title"]]


def test_free_mode_not_asked_none_memory_and_chips_first(api):
    _, pid = customer(api)
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    assert said(ev) == diy_tools.FREE_NOT_ASKED
    (card,) = cards_of(ev, "knowledge")
    assert len(
        card["data"]["checklist"]
    ) == 6 and all(  # 날짜 없이 때만(입주 청소 빼고 5가지, 콘센트 두 걸음)
        x["label"].endswith("공사 날짜가 정해지면 날짜를 알려 드려요")
        for x in card["data"]["checklist"]
    )
    # 준비물만 물으면(직접 할 일이 없으면) 원래 길잡이로
    ev = ok(ask(api, pid, "준비물 알려 주세요"))
    assert not [c for c in cards_of(ev, "knowledge") if c["data"]["title"] == "직접 할 일 준비물"]
    # 기억 diy 글(칩 전)은 원본이 아니라 고른 일로 채우지 않아요(QA r3 s6 리드 결정 11-22, 예전 기대: 그 글의 일로)
    remember(api, pid, "diy", "페인트는 제가 직접 칠할게요")
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    assert said(ev) == diy_tools.FREE_NOT_ASKED
    # 칩이 원본이에요
    chips(api, pid, ["light"])
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    (card,) = [c for c in cards_of(ev, "knowledge") if c["data"]["title"] == "직접 할 일"]
    (only,) = card["data"]["checklist"]
    assert only["label"].startswith("조명 교체 · ")
    ev = ok(ask(api, pid, "직접 할 일 준비물 알려 주세요"))
    titles = [c["data"]["title"] for c in cards_of(ev, "knowledge")]
    assert titles == ["직접 할 일"]  # '직접 할 일'을 물으면 목록, 준비물만 물으면 아래
    ev = ok(ask(api, pid, "준비물 알려 주세요"))
    titles = [c["data"]["title"] for c in cards_of(ev, "knowledge")]
    assert titles == ["직접 할 일 준비물", "공사 전날 준비물"]
    # '없어요'
    chips(api, pid, [])
    ev = ok(ask(api, pid, "직접 할 일 알려 줘"))
    assert said(ev) == diy_tools.FREE_NONE


def test_diy_plan_tool_weekend_and_model_values(api, script):
    _, pid = customer(api)
    chips(api, pid, ["paint", "silicone"])
    call = {"id": "d", "name": "diy_plan", "input": {"item": "paint", "days": "weekend"}}
    log = script([{"tool_calls": [call]}, {"text": "페인트는 도배 전에 주말에 칠하면 돼요."}])
    ev = ok(ask(api, pid, "페인트는 주말에만 칠할 수 있어요. 언제 해요?"))
    (card,) = cards_of(ev, "knowledge")
    assert card["data"]["title"] == "페인트(문틀 · 몰딩) · 직접 할 때"
    result = log[1]["messages"][-1]["content"][0]
    assert not result.get("is_error")
    got = json.loads(result["content"])
    assert (got["state"], got["phase"]) == ("chips", "expected")
    (item,) = got["items"]
    assert item["kind"] == "paint" and "사포" in item["prep"] and item["when"].startswith("목공이")
    # 날짜는 공정표 '고객이 직접' 줄과 같은 값이고(QA r2 c3), 주말 · 공휴일 값은 weekend에 따로 와요. 도배만 맡긴
    # 집이라 시작은 '목공이 끝난 뒤'(빈 칸, calc.diy diy_v4)이고 공정표 줄은 마감 날 하루예요
    p = plan(api, pid)
    (row,) = [b for b in p["blocks"] if b["kind"] == "diy" and b["label"].startswith("페인트")]
    assert "start" not in item and item["end"] == row["start"] == row["end"]
    assert item["note"] == diy_tools.AFTER_NOTE["mokgong"]
    assert "start" not in item["weekend"]
    end = D(item["weekend"]["end"])
    assert end.weekday() >= 5 and D(item["weekend"]["day"]) == end  # 주말만
    dobae = block(p, "work", "dobae")
    assert end <= D(dobae["start"]) - timedelta(days=calc_diy.PAINT_DRY_DAYS)
    assert got["days"] == "weekend" and diy_tools.DAYS_NOTE["asked"] in got["basis"]
    assert (
        f"페인트(문틀 · 몰딩) 칠하기: {item['text']}" in card["data"]["lines"]
    )  # 카드 말 = 모델 말

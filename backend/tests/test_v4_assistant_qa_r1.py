"""v4 비서 QA 1차(카드 · 도구 값 · 보드 갈래)에서 고친 것: 확정 공정표 모델 값의 날짜별 이름 · 승인한 추가 금액이 든
공사 금액(보드 · 도구) · 보드 업체 줄 · 잠긴 공사의 직접 할 일 제안 · 빠진 업체를 뺀 추천 · 끝난 일 안내 · 오늘 할 일
새 소식 · 연락처 대신 채팅 · 공사 전 할 일 집 맞춤 · 업체 쪽(날짜 바꾸기 다른 날 제안 · 서울 시각 · 틀 문장 · 고른
반나절 · 공사 날 후보 시작일 · 견적서 칸). 유료 호출 0회(Claude 대본 · LLM 꺼짐)."""

import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import aftercare
from app.assistant import service as assistant_service
from app.assistant.tools import aftercare as aftercare_tools
from app.assistant.tools import cards
from app.assistant.tools import vendor as vendor_tools
from app.refprice.holidays import HOLIDAYS
from app.shared.clock import now_utc, today_seoul
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, ready
from tests.test_extras import scheduled
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import booked, picked, quiet, requested, vendor
from tests.test_v3_work_deal import post_days
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_aftercare import action, post_extra, tick
from tests.test_v4_assistant_free import cards_of, vendor_turn
from tests.test_v4_assistant_nudges import nudges, offered_nudge, run
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_vendor_jobs import dates_row, first_block
from tests.test_visit_inbox import login

TODAY = today_seoul()


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
    """대본 log의 call번째 LLM 호출이 받은 마지막 도구 결과(모델에 간 값)."""
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


# ---- 고객: 확정 공정표 모델 값 · 공사 금액 · 보드 업체 줄 ----


def test_schedule_model_reads_plan_rows_days_and_state(api, script):
    """c1 #1: 카드에 보이는 날짜별 이름(건조 · 입주 청소)을 비서도 읽어요."""
    customer, pid, _did = scheduled(api)
    use(api, customer)
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {"text": "확정 공정표예요."},
        ]
    )
    ok(ask(api, pid, "공사는 언제 끝나요? 화면에는 더 길게 나와서 헷갈려요"))
    got = tool_result(log, 1)
    (deal,) = got["deals"]
    assert deal["state"] == "공사 날짜를 수락했어요"
    period = got["period"]
    labels = [r["label"] for r in period["rows"]]
    assert labels[0] == "도배 공사" and "자연 건조" in labels
    assert "입주 청소 · 고객이 직접" in labels
    work = period["rows"][0]
    assert (work["start"], work["end"], work["vendor_name"]) == (
        deal["start_date"],
        deal["end_date"],
        "마루와벽",
    )
    names = [n for d in period["days"] for n in d["names"]]
    assert "창문을 닫고 자연 건조" in names and "입주 청소 · 고객이 직접" in names
    assert period["end"] > deal["end_date"]  # 건조 · 입주 청소까지가 공정표 끝


def test_approved_extra_counts_in_board_and_tool_money(api, script):
    """c4 #1: 추가 금액을 승인하면 지금 공사 금액(확정 + 승인한 추가 금액)이 보드 · 도구 값에 들어가요."""
    customer, pid, did = scheduled(api)
    x = post_extra(api, did, 220_000)  # 부가세 별도로 적음
    use(api, customer)
    r = api.post(f"/projects/{pid}/deals/{did}/extras/{x['id']}/answer", json={"answer": "approve"})
    assert r.status_code == 200, r.text
    ex = api.get(f"/projects/{pid}/schedule").json()["trades"][0]["extras"]
    grand, base, extra = ex["grand_total"], ex["deal_total"], ex["ok"]["total"]
    assert extra > 0 and grand == base + extra  # 계산 엔진 값
    board = api.get("/assistant/board", params={"project_id": pid}).json()
    assert board["money"] == {
        "label": "공사 금액 · 부가세 포함",
        "won": grand,
        "range": None,
        "extra_won": extra,
    }
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "e", "name": "get_extras", "input": {}},
                    {"id": "g", "name": "get_schedule", "input": {}},
                ]
            },
            {"text": "지금 공사 금액을 카드로 보여 드려요."},
        ]
    )
    ok(ask(api, pid, "추가 금액까지 해서 지금 공사 금액이 전부 얼마예요?"))
    content = log[1]["messages"][-1]["content"]
    got, sch = (json.loads(c["content"]) for c in content)
    assert got["count"] == 0 and got["note"]  # 답을 기다리는 추가 금액은 없어요
    (d,) = got["deals"]
    assert (
        d["money"]["total"] == grand
        and {"label": "승인한 추가 금액", "won": extra} in (d["money"]["rows"])
    )
    assert sch["deals"][0]["money"]["total"] == grand


def test_board_vendor_rows_follow_deal_stage_and_closed_reason(api):
    """c1 · c3 · c4: 공사 전 확정 업체를 '끝났어요'로, 고르지 않은 업체를 '끝'으로 보이지 않아요."""
    customer, pid, _did = scheduled(api)
    use(api, customer)
    rows = {
        r["name"]: r
        for r in api.get("/assistant/board", params={"project_id": pid}).json()["vendors"]["rows"]
    }
    start = query("select start_date from deals")[0]["start_date"]
    assert rows["마루와벽"]["text"] == f"{cards.md_week(start)} 공사 시작"
    assert (rows["결도배"]["text"], rows["결도배"]["state"]) == ("고르지 않음", "cancelled")
    assert all(r["text"] != "끝났어요" for r in rows.values())


# ---- 고객: 잠긴 공사의 직접 할 일 · 빠진 업체 · 끝난 일 ----


def test_locked_project_diy_proposal_survives_sweep(api, script):
    """c1 #3 · c3 #1: 실측 요청 뒤(잠김) 직접 할 일만 바꾸는 승인 카드를 정리가 닫지 않아요."""
    _, pid = home(api)  # v3 집 정보가 있는 공사
    query("update projects set locked_at = now() where id = $1", uuid.UUID(pid))  # 요청 뒤처럼 잠김
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"diy": ["clean"]}},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "입주 청소는 제가 직접 할게요"))
    got = [x for x in acts(ev) if x["kind"] == "home_info" and x["status"] == "proposed"]
    assert len(got) == 1, len(log) > 1 and tool_result(log, 1)
    (a,) = got
    assert a["summary"]["title"] == "직접 할 일 저장"
    # 직접 할 일만 바꾸면 다시 계산하지 않아요. QA r2 c2부터 확정 전 요청은 믿집이 알리고 확정한 업체만
    # 채팅으로 알리라고 해요. 이 공사는 잠기기만 하고 요청이 없어 업체 말이 없어요(test_v4_qa_r2_diy)
    note = a["summary"]["note"]
    assert "표준견적서를 새로" not in note and "업체" not in note
    run(api, assistant_service.sweep, now_utc())
    r = approve(api, a["action_id"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    keys = query("select key from project_conditions where key like 'diy.%'")
    assert [x["key"] for x in keys] == ["diy.clean"]


def test_out_vendor_left_out_of_picks_and_open_card_pointed(api, monkeypatch, script):
    """c4 #5: 못 받은 업체는 추천에서 빼고, 이미 열린 실측 요청 승인 카드를 가리켜요."""
    quiet(monkeypatch)
    vendor(api, "gyeol@mitjip.test", "결도배")
    f = requested(api)
    login(api, f["email"])
    assert (
        api.post(f"/vendor/visits/{f['visit']}/decline", json={"code": "full"}).status_code == 200
    )
    use(api, f["token"])
    tick(api)  # 먼저 말 걸기: 결도배 실측 요청 승인 카드
    (n,) = nudges(trigger="vendor_out")
    assert action(n["action_id"])["summary"]["title"] == "결도배에 실측 요청 보내기"
    log = script(
        [
            {"tool_calls": [{"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}]},
            {"text": "결도배가 남았어요."},
        ]
    )
    ev = ok(ask(api, f["pid"], "마루와벽이 못 한대요. 다른 업체는 없어요?"))
    got = tool_result(log, 1)
    assert [p["name"] for p in got["picks"]] == ["결도배"]
    assert got["picks"][0]["proposed"] is True and "이미 열려 있어요" in got["note"]
    (card,) = cards_of(ev, "vendor_picks")
    assert [p["name"] for p in card["data"]["picks"]] == ["결도배"]


def test_confirm_again_says_the_dates_are_accepted(api, script):
    """c4 #2: 날짜까지 수락한 뒤 확정을 다시 누르면 '업체가 날짜를 올리면 수락'이 아니라 지금 상태를 말해요."""
    customer, pid, _did = scheduled(api)
    use(api, customer)
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "compare_quotes", "input": {"trade": "dobae"}}]},
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_vendor_confirm", "input": {"visit_ref": "m1"}}
                ]
            },
            {"text": "이미 확정했어요."},
        ]
    )
    ev = ok(ask(api, pid, "마루와벽으로 확정해 줘"))
    err = tool_result(log, 2)
    assert err["error"] == "already_chosen" and "도 수락했어요" in err["message"]
    assert "올리면" not in err["message"]
    (card,) = cards_of(ev, "quote_compare")
    assert card["data"]["decided"] is True  # 확정한 뒤에는 '확정' 단추를 두지 않아요


def test_today_hides_settled_news_and_contact_button(api, monkeypatch):
    """c5 · c2: 시간을 고른 뒤 '날짜를 골라 주세요' 새 소식을 빼고, 실측 요청 뒤 [연락처 보기] 줄을 두지 않아요."""
    f, n = offered_nudge(api, monkeypatch)
    (note,) = query("select id from notifications where kind = 'visit_offered'")
    today = api.get("/assistant/today", params={"project_id": f["pid"]}).json()
    assert f"n-{note['id']}" in [x["id"] for x in today["news"]]
    rows = today["todo"] + today["waiting"]
    assert all((x.get("action") or {}).get("label") != "연락처 보기" for x in rows)
    assert all("연락할 차례" not in x["title"] for x in rows)
    assert approve(api, str(n["action_id"])).json()["status"] == "executed"
    today = api.get("/assistant/today", params={"project_id": f["pid"]}).json()
    assert f"n-{note['id']}" not in [x["id"] for x in today["news"]]


def test_suggest_vendor_picks_before_any_shortlist(api):
    """c1 · c2 · c5: 담은 업체가 없는데 '담은 업체에 실측 요청할 차례'를 권하지 않아요."""
    _, pid = home(api)
    ev = ok(ask(api, pid, "집 정보 확인해 줘"))
    says = [x["say"] for x in ev[-1][1]["suggest"]]
    assert "실측 시간 찾아 줘" not in says and "업체 추천해 줘" in says


# ---- 고객: 공사 전 할 일 집 맞춤 · 채팅 링크 ----


def test_prep_lists_fit_the_home():
    """c2 #5 · c3 #4: 빈 집은 가구 줄을 빼고, 평일에 비우는 집 · 반려동물 · 콘센트 직접은 그 줄을 더해요."""
    empty = cards.HomeCtx(occupied=False)
    card = aftercare_tools.check_card("b", "before", ["dobae"], [], None, empty)
    labels = [x["label"] for x in card.data["checklist"]]
    assert not any("가구" in x or "짐" in x for x in labels)
    # 공통 '콘센트 옮기기 등' 줄은 안 써요
    assert not any(x.startswith("직접 할 일(") for x in labels)
    busy = cards.HomeCtx(
        occupied=True, pet=True, away_weekdays=True, weekday_work=True, diy=("outlet",)
    )
    card = aftercare_tools.check_card("b", "before", ["dobae"], [], None, busy)
    labels = [x["label"] for x in card.data["checklist"]]
    assert cards.PET_ITEM in labels and any("덮개 떼기" in x for x in labels)
    assert cards.AWAY_LINE in card.data["lines"] and cards.PET_LINE in card.data["lines"]
    eve = cards.prep_card("p", ["dobae"], empty)
    eve_labels = [x["label"] for x in eve.data["checklist"]]
    assert not any("가구" in x for x in eve_labels) and cards.ENTRY_ITEM in eve_labels
    lived = cards.prep_card("p", ["dobae"], cards.HomeCtx(occupied=True, pet=True))
    assert cards.PET_ITEM in [x["label"] for x in lived.data["checklist"]]


def test_compare_card_links_open_chat_and_hides_confirm_after_deal(api):
    """c1 #5: 실측이 확정된 업체는 카드 · 모델 값에 믿집 채팅(누를 곳)이 있어요."""
    f = booked(api)
    login(api, f["email"])
    quote(api, f["visit"], 3_080_000)
    use(api, f["token"])
    ev = ok(ask(api, f["pid"], "견적서 비교해 줘"))
    (card,) = cards_of(ev, "quote_compare")
    (col,) = card["data"]["cols"]
    (thread,) = query("select id from threads")
    assert col["chat_href"] == f"/chat/{thread['id']}" and card["data"]["decided"] is False
    seen = api.get(f"/projects/{f['pid']}/quotes?trade=dobae").json()["vendors"][0]["seen_ver"]
    r = api.post(f"/projects/{f['pid']}/quotes/{f['visit']}/confirm", json={"seen_ver": seen})
    assert r.status_code == 200, r.text
    ev = ok(ask(api, f["pid"], "견적서 비교해 줘"))
    (card,) = cards_of(ev, "quote_compare")
    assert card["data"]["decided"] is True and card["data"]["cols"][0]["chosen"] is True


# ---- 업체: 날짜 바꾸기 다른 날 제안 · 틀 문장 · 고른 반나절 · 서울 시각 · 후보 시작일 · 견적서 칸 ----


def test_change_request_with_all_wishes_busy_offers_nearest_free_days(api, monkeypatch):
    """c6 #1: 고객이 바란 날이 모두 다른 공사와 겹치면 가장 가까운 빈 날을 다른 날 제안으로 보내요."""
    quiet(monkeypatch)
    from app.schedule import service as schedule_service

    customer, pid, did = scheduled(api)
    use(api, customer)
    w1, w2 = days(35, 2)
    body = {"wish_dates": [w1, w2], "reason": "이사 날짜가 바뀌었어요."}
    assert api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body).status_code == 201
    busy = [date.fromisoformat(w1), date.fromisoformat(w2)]
    taken_now = {"days": busy}

    async def taken(_s, _d, _today):  # 같은 업체의 다른 공사로 찬 날(시험이 정한다)
        return taken_now["days"]

    monkeypatch.setattr(schedule_service, "_busy", taken)
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'dates_requested'")
    tick(api)
    (n,) = nudges(trigger="dates_requested")
    assert n["body"].endswith(aftercare.NEXT_OTHER) and n["src"] == "guide"
    a = action(n["action_id"])
    start = date.fromisoformat(a["payload"]["days"][0])
    assert start not in busy and start > busy[0]
    assert a["summary"]["title"].startswith("다른 날 제안")
    # 바란 날이 비어 있으면 다른 날로는 답할 수 없어요(그날 중에서만)
    taken_now["days"] = []
    login(api, "maru@mitjip.test")
    r = api.post(
        f"/vendor/jobs/{did}/dates",
        json={
            "days": a["payload"]["days"],
            "crew": a["payload"]["crew"],
            "kind": "change",
            "request_id": a["payload"]["request_id"],
        },
    )
    assert r.status_code == 422, r.text
    taken_now["days"] = busy  # 바란 날이 모두 찼으면 다른 날 제안을 받아요
    r = approve(api, str(n["action_id"]), prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    (p,) = query("select start_date, kind from date_proposals where status = 'pending'")
    assert (p["start_date"], p["kind"]) == (start, "change")


def test_vendor_deal_confirmed_line_is_the_template(api, monkeypatch, script):
    """c6 #3: 업체 쪽 먼저 말 걸기는 틀만 써요(Haiku가 '고객이 날짜를 냈어요'처럼 틀리게 쓴 적이 있어요)."""
    quiet(monkeypatch)
    ready(api)
    query("delete from assistant_nudges")
    query("delete from notifications where kind <> 'deal_confirmed'")
    log = script([{"json": {"text": "고객님이 노원구 도배 공사 날짜를 내셨어요."}}])
    tick(api)
    (n,) = nudges(trigger="deal_confirmed")
    assert (n["status"], n["src"]) == ("sent", "guide")
    assert n["body"].endswith("이제 공사 날짜를 낼 차례예요.") and log == []


def test_vendor_sees_picked_half_in_brief_today_and_tool(api, script):
    """c6 #4 · #2: 고객이 고른 반나절과 수락할 곳(요청 화면), 시각은 서울 시각 글이에요."""
    f = picked(api)
    login(api, f["email"])
    b = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()
    assert b["picked"]["half"] == "am" and b["picked"]["href"] == f"/vendor/requests/{f['visit']}"
    assert b["facts"][0].startswith("고객이 고른 날") and b["due_at"] is None
    rows = api.get("/vendor/assistant/today").json()["rows"]
    (row,) = [x for x in rows if x["id"] == "pick"]
    assert row["title"] == "날짜 수락 1건"
    assert row["action"]["href"] == f"/vendor/requests/{f['visit']}"
    log = script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {"text": "고객이 고른 날을 요청 화면에서 수락해 주세요."},
        ]
    )
    ok(vendor_turn(api, None, "오늘 할 일 알려 줘"))
    got = tool_result(log, 1)
    (req,) = [x for x in got["requests"] if x.get("picked")]
    assert req["picked"]["half"] == "오전" and "요청 화면" in req["picked"]["note"]
    sent = json.dumps(got, ensure_ascii=False)
    assert "+00:00" not in sent and "T0" not in sent  # UTC 시각을 그대로 넘기지 않아요
    assert req["due_at"] is None or ("오전" in req["due_at"] or "오후" in req["due_at"])


def test_today_and_my_jobs_follow_customer_date_request(api, script):
    """리뷰 D2 · D3: 고객이 다른 날짜를 요청한 공사는 오늘 할 일 후보가 고객이 고른 날이에요(처음 낸 날을 다시
    보내지 않아요). my_jobs 기한은 요청 답 기한(요청 + 48시간)을 서울 시각 글로 주고 고객이 바란 날도 같이 줘요."""
    customer, pid, did, _ = ready(api)
    first = first_block(api.get(f"/vendor/jobs/{did}").json())
    assert post_days(api, did, first).status_code == 200  # 비서 첫 후보와 같은 날로 냄
    use(api, customer)
    w1, w2 = days(28, 2)
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [w1, w2]})
    assert r.status_code == 201, r.text
    login(api, "maru@mitjip.test")
    row = dates_row(api)
    assert f"후보 {date.fromisoformat(w1):%m.%d}" in row["sub"] and row["action"]["choice"]
    log = script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {"text": "고객이 바란 날로 후보를 골랐어요."},
        ]
    )
    ok(vendor_turn(api, None, "할 일 보여 줘"))
    got = tool_result(log, 1)
    (deal,) = [x for x in got["deals"] if x["dates_state"] == "requested"]
    (req,) = query(
        "select due_at from date_requests where deal_id = $1 and status = 'open'", uuid.UUID(did)
    )
    assert deal["due_at"] == cards.seoul_text(req["due_at"])  # 지난 공사 날짜 기한이 아니에요
    assert deal["wish"] == [w1, w2] and deal["candidates"][0]["start"] == w1
    assert "+00:00" not in json.dumps(got, ensure_ascii=False)


def test_today_lists_change_request_with_wish_candidates(api):
    """리뷰 D2: 수락 뒤 날짜 바꾸기 요청(change_requested)도 오늘 할 일에 뜨고, 후보는 고객이 바란 날이에요."""
    customer, pid, did = scheduled(api)
    assert "dates" not in {x["id"] for x in api.get("/vendor/assistant/today").json()["rows"]}
    use(api, customer)
    w1, w2 = days(35, 2)
    body = {"wish_dates": [w1, w2], "reason": "이사 날짜가 바뀌었어요."}
    assert api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body).status_code == 201
    login(api, "maru@mitjip.test")
    row = dates_row(api)
    assert row["title"] == "공사 날짜 낼 공사 1건"
    assert f"후보 {date.fromisoformat(w1):%m.%d}" in row["sub"] and row["action"]["choice"]


def test_request_brief_model_due_is_seoul_text(api, script):
    """리뷰 D3: 요청 브리핑 도구의 답 기한도 서울 시각 글이에요(UTC 그대로 넘기면 '오전 9시'로 읽어요)."""
    f = requested(api)
    login(api, f["email"])
    log = script(
        [
            {"tool_calls": [{"id": "b", "name": "request_brief", "input": {}}]},
            {"text": "답할 기간을 확인해 주세요."},
        ]
    )
    ok(vendor_turn(api, f["visit"], "이 요청 정리해 줘"))
    got = tool_result(log, 1)
    (v,) = query("select reply_due_at from visits where id = $1", uuid.UUID(f["visit"]))
    assert got["due_at"] == cards.seoul_text(v["reply_due_at"])
    assert "+00:00" not in json.dumps(got, ensure_ascii=False)


@dataclass
class FakeJob:
    """date_candidates · request_candidates가 읽는 공사 칸만(schedule JobOut 꼴)."""

    status: str = "scheduled"
    plan_start: date | None = None
    busy_days: list = field(default_factory=list)
    weekend_work: bool = False
    request: object = None
    quote: object = field(default_factory=lambda: SimpleNamespace(days=2))
    need: object = field(default_factory=lambda: SimpleNamespace(days=2, crew=3))

    def model_copy(self, update: dict) -> "FakeJob":
        return replace(self, **update)


def _clear_monday() -> date:
    """오늘 + 20일 뒤 첫 월요일 중 그 주 월~목에 공휴일이 없는 날."""
    d = TODAY + timedelta(days=20)
    while d.weekday() != 0 or any(d + timedelta(days=i) in HOLIDAYS for i in range(4)):
        d += timedelta(days=1)
    return d


def test_date_candidates_start_on_plan_start_and_requests_fall_back():
    """c6 #5 · #1: 후보는 예상 시작일 그날부터(+1 아님), 고객이 바란 날이 모두 찼으면 가장 가까운 빈 날(alt)."""
    mon = _clear_monday()
    tue, wed = mon + timedelta(days=1), mon + timedelta(days=2)
    first = vendor_tools.date_candidates(FakeJob(plan_start=mon), uuid.uuid4(), TODAY)[0]
    assert first["start"] == mon.isoformat()
    req = SimpleNamespace(id=uuid.uuid4(), wish_dates=[mon, tue])
    got = aftercare_tools.request_candidates(
        FakeJob(plan_start=mon, request=req, busy_days=[mon]), uuid.uuid4(), TODAY
    )
    assert [c["start"] for c in got] == [tue.isoformat()] and not got[0].get("alt")
    got = aftercare_tools.request_candidates(
        FakeJob(plan_start=mon, request=req, busy_days=[mon, tue]), uuid.uuid4(), TODAY
    )
    assert got and all(c["alt"] for c in got) and got[0]["start"] == wed.isoformat()


def test_vendor_checklist_has_removal_waste_warranty_and_fits_empty_home(api):
    """c6 #8: 견적서 칸에 철거 · 폐기물 · 하자 보증, 빈 집이면 '가구 옮기기'를 빼요, 빈 칸을 먼저."""
    f = requested(api)  # 빈 집
    login(api, f["email"])
    c = api.get(f"/vendor/assistant/checklists/{f['visit']}").json()
    labels = [x["label"] for x in c["fields"]]
    assert {"철거", "폐기물 처리", "하자 보증"} <= set(labels)
    assert not any("가구" in x for x in c["easy_miss"])

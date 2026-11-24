"""점검 고침 X3(비서 도구 · 조사, 통합 b84acb2 점검 R2 · R1b): 담기 칸 기준 요청 칸 검사(B1) · 전문가 숫자 근거는
고객 말(B2) · 업체 브리핑 카드 말과 거절한 제안(B3 · B8) · 무료 모드 미룸 · 묻는 말 · 부정(B4) · 취소 남기는 말(B5) ·
빈 카드 안 보내기(B6 · B9) · 같은 면적(B7) · 조사(B10) · 후보 없을 때 다른 길(B11), 넘어가기마다 주소 · robots(R1b #11) ·
찾을 수(#14) · 목표 200자(#15) · 요청 점검 오탐(#16) · 가림 자리(#21). 유료 호출 0회(Claude 대본), 웹은 MockTransport."""

import asyncio
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import asks, linkimage, pagecheck, research
from app.assistant.schemas import CardOut, TodayData, VisitSlotsData
from app.assistant.tools import aftercare as aftercare_tools
from app.assistant.tools import cards as card_tools
from app.assistant.tools import customer as customer_tools
from app.assistant.tools import propose
from app.assistant.tools import vendor as vendor_tools
from app.config import settings
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_dates import ready as dates_ready
from tests.test_extras import scheduled
from tests.test_v3_project_home import HOME
from tests.test_v3_visit_kit import add, customer, quiet, requested, vendor
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_aftercare import worked
from tests.test_v4_assistant_cards import proposed
from tests.test_v4_assistant_experts import TRADE_ROUTE, _gate, _out
from tests.test_v4_assistant_free import cards_of, vendor_turn
from tests.test_v4_assistant_turns import ask, home, ok, turn_row
from tests.test_v4_r6_a1_cards import RECOMMEND, tool_result
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


@pytest.fixture
def repo_search(monkeypatch):
    """지식 검색을 저장소 색인으로(시험 DB에는 지식이 없어요). 임베딩은 부르지 않아요."""
    from app.knowledge import service as knowledge

    async def _index(_s):
        return repo_index(), []

    async def no_embed(_texts):
        return None

    monkeypatch.setattr(knowledge, "_index", _index)
    monkeypatch.setattr(llm, "embed_texts", no_embed)


def tokens(ev) -> str:
    return "".join(d.get("text", "") for e, d, _ in ev if e == "token")


def shown(ev) -> str:
    got = cards_of(ev, "answer")
    return (got[-1]["data"]["text"] if got else "") + "|" + tokens(ev)


def trace_of(ev) -> dict:
    t = turn_row(ev[0][1]["turn_id"])["trace"]
    return json.loads(t) if isinstance(t, str) else t


# ---- B1: 요청 칸은 담기 칸(3칸) 기준 ----

NAMES = ("결도배", "마루와벽", "한결도배", "솜씨도배", "바른도배")


def test_b1_full_shortlist_blocks_new_vendor_and_picks_only_held(api, script, monkeypatch):
    quiet(monkeypatch)
    vids = [vendor(api, f"x3b1{i}@mitjip.test", n) for i, n in enumerate(NAMES)]
    id_of = dict(zip(NAMES, vids, strict=True))
    _, pid = customer(api)
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "세 곳이에요."}])
    ok(ask(api, pid, "업체 추천해 줘"))
    first = tool_result(log, 1)["picks"][0]
    held = [n for n in NAMES if n != first["name"]][:3]
    for n in held:  # 화면에서 다른 업체 3곳을 담기만(요청 전): 담기 칸 3개가 다 찬다
        assert add(api, pid, id_of[n]).status_code == 201

    # 담지 않은 업체에는 요청 카드를 만들지 않아요(만들면 승인 때 409 slots_full)
    req = {
        "id": "p",
        "name": "propose_visit_request",
        "input": {"trade": "dobae", "vendor_refs": [first["ref"]]},
    }
    log = script([{"tool_calls": [req]}, {"text": "담기 칸이 다 찼어요."}])
    ev = ok(ask(api, pid, f"{first['name']}에 실측 요청해 줘"))
    err = tool_result(log, 1)
    assert err["error"] == "slots_full" and err["message"] == propose.slots_full_said(0, 0, 3)
    assert "3곳을 담아 둬서 새 업체에 요청할 수 없어요" in err["message"] and proposed(ev) == []

    # 추천은 담아 둔 업체 중에서만(그 업체엔 요청할 수 있어요), 카드는 보여요
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "담아 둔 곳이에요."}])
    ev = ok(ask(api, pid, "업체 추천해 줘"))
    got = tool_result(log, 1)
    assert sorted(p["name"] for p in got["picks"]) == sorted(held)
    assert all(p["picked"] for p in got["picks"]) and card_tools.HELD_ONLY in got["note"]
    assert cards_of(ev, "vendor_picks")

    # 담아 둔 업체에 보내는 카드는 만들고, 누르면 보내져요
    req["input"]["vendor_refs"] = [p["ref"] for p in got["picks"][:2]]
    log = script([{"tool_calls": [req]}, {"text": "카드를 확인해 주세요."}])
    (a,) = proposed(ok(ask(api, pid, "담은 곳 두 곳에 요청해 줘")))
    r = approve(api, a["action_id"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert query("select count(*) as n from visits")[0]["n"] == 2


def test_b1_slots_full_said_names_held_vendors():
    assert propose.slots_full_said(1, 0, 2) == (
        "실측 요청은 담은 업체까지 공정마다 3곳이에요. 지금 1곳이 진행 중이고 2곳을 담아 둬서 새 업체에 요청할 수 "
        "없어요. 담아 둔 업체에 요청하거나, 업체 보기에서 담은 업체 하나를 빼면 다른 업체에 요청할 수 있어요."
    )
    # 담아 두기만 한 곳이 없으면 옛 글 그대로
    assert propose.slots_full_said(2, 1) == propose.slots_full_said(2, 1, 0)


# ---- B2: 전문가 숫자 근거는 모델이 쓴 질문이 아니라 고객 말 ----


@pytest.mark.parametrize(
    ("said", "kept"),
    [("도배 풀은 얼마나 말려야 해요?", False), ("도배 풀은 37시간 말려야 해요?", True)],
)
def test_b2_expert_number_must_be_in_the_customer_words(
    api, script, monkeypatch, repo_search, said, kept
):
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    call = {  # 비서 모델이 질문에 숫자를 지어 넣었어요(자료에 없는 37시간)
        "id": "q",
        "name": "answer_question",
        "input": {"question": "도배 풀은 37시간 말려야 하나요?", "kind": "general"},
    }
    line = "도배 풀은 37시간 말려요."
    log = script(
        [{"tool_calls": [call]}, {"json": _out((line, ["G"]))}, {"text": line}, {"text": line}]
    )
    ev = ok(ask(api, pid, said))
    body = log[2]["messages"][-1]["content"][0]["content"]
    assert ("37시간" in body) is kept  # 전문가 줄이 도구 결과에 남는지
    assert ("37시간" in shown(ev)) is kept


# ---- B3 · B8: 업체 브리핑이 만든 카드 말 · 거절한 같은 제안 ----


def test_b3_b8_brief_card_words_pass_and_rejected_offer_is_not_resent(api, script):
    f = requested(api)
    login(api, f["email"])
    brief = {"tool_calls": [{"id": "b", "name": "request_brief", "input": {}}]}
    made = "가장 잘 맞는 기간으로 답하는 카드를 만들었어요. [이 기간으로 답하기]를 눌러 주세요."
    log = script([brief, {"text": f"공정 · 지역이 맞아요.\n\n{made}"}])
    ev = ok(vendor_turn(api, f["visit"], "새 요청 어때요?"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    got = tool_result(log, 1)
    assert a["kind"] == "window_answer" and got["state"] == "new" and got["proposed"] is True
    assert made in tokens(ev) and "카드 없이 카드를 말함" not in (trace_of(ev).get("dropped") or [])

    # 열린 카드를 다시 브리핑하면 같은 카드(same)
    log = script([brief, {"text": "[이 기간으로 답하기]를 눌러 주세요."}])
    ok(vendor_turn(api, f["visit"], "다시 보여 줘"))
    assert tool_result(log, 1)["state"] == "same"

    # 업체가 거절한 뒤 다시 브리핑: 새 카드가 없으면 proposed False · 거절 행 이벤트도 다시 보내지 않아요
    r = api.post(
        f"/vendor/assistant/actions/{a['action_id']}/reject", json={"client_key": uuid.uuid4().hex}
    )
    assert r.status_code == 200, r.text
    log = script([brief, {"text": "공정 · 지역이 맞아요."}])
    ev = ok(vendor_turn(api, f["visit"], "다시 브리핑해 줘"))
    got = tool_result(log, 1)
    assert got["proposed"] is False and got["state"] == "rejected" and acts(ev) == []


# ---- B4: 무료 모드 낱말 길(추가 금액 미룸 · 남은 일 부정 · 한 번 더 부정 · 끝났는지 묻는 말) ----


def test_b4_free_words_skip_later_negations_and_questions():
    for text in (
        "추가 금액 승인은 나중에 할게요",
        "추가 금액 승인은 아직이요",
        "추가 비용 승인은 좀 더 생각해 볼게요",
    ):
        assert aftercare_tools._answer_of(text) is None, text
    assert aftercare_tools._answer_of("추가 금액 승인할게요") == "approve"
    assert aftercare_tools._answer_of("거절 말고 승인할게요") == "approve"
    for text in (
        "벽지 다시 해 주실 필요는 없어요",
        "몰딩은 고쳐 주지 않아도 돼요",
        "남은 일은 없어요",
        "몰딩 고쳐 달라는 거 아니에요",
    ):
        assert not aftercare_tools.fix_said(text), text
    assert aftercare_tools.fix_said("벽지 마감이 안 좋아요. 다시 해 주세요")
    assert aftercare_tools.fix_said("남은 일이 있어요. 안방 몰딩 고쳐 주세요")
    for text in (
        "결도배에 다시 요청 안 할래요",
        "한 번 더 요청하지 마세요",
        "다시 요청은 하지 말아 주세요",
        "다시 요청할 필요 없어요",
    ):
        assert not aftercare_tools.again_said(text), text
    assert aftercare_tools.again_said("결도배에 한 번 더 요청해 주세요")


@pytest.fixture
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def test_b4_free_done_question_shows_state_without_approval_card(api, off):
    customer_token, pid, did = scheduled(api)
    worked()
    assert api.post(f"/vendor/jobs/{did}/done", json={}).status_code == 200
    use(api, customer_token)
    for text in ("공사 끝났나요?", "공사 끝났는지 모르겠어요"):
        ev = ok(ask(api, pid, text))
        assert [x for x in acts(ev) if x["kind"] == "work_check"] == [], text
        assert cards_of(ev, "knowledge")[0]["card_id"] == f"after-{did}"
        assert cards_of(ev, "answer")[-1]["data"]["text"].endswith(aftercare_tools.WORK_ASKED)
    ev = ok(ask(api, pid, "공사 끝났어요 확인할게요"))  # 분명한 말은 그대로 승인 카드
    assert [x["kind"] for x in acts(ev) if x["status"] == "proposed"] == ["work_check"]


# ---- B5: 취소 대상 풀기의 '취소하지 말고' · '취소 안 할래요' ----


def test_b5_cancel_targets_read_keep_words():
    live = [SimpleNamespace(vendor_name="결도배"), SimpleNamespace(vendor_name="마루와벽")]

    def names(text: str) -> list[str]:
        return [v.vendor_name for v in propose.cancel_targets(live, text)]

    assert names("결도배는 취소하지 말고 마루와벽만 취소해 주세요") == ["마루와벽"]
    assert names("결도배는 취소 안 할래요. 마루와벽 취소해 줘") == ["마루와벽"]
    assert names("결도배는 취소 안 하고 나머지는 취소해 주세요") == ["마루와벽"]
    assert names("결도배는 취소하지 마세요") == []  # 다른 요청을 취소하라는 말이 없으면 고르기 칩
    assert names("결도배는 남기고 마루와벽 취소") == ["마루와벽"]
    assert names("둘 다 취소해 주세요") == ["결도배", "마루와벽"]


# ---- B6 · B9: 고를 것 · 할 일이 없으면 빈 카드 대신 까닭 ----


def test_b6_slots_before_the_vendor_answers_send_no_empty_card(api, script, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)  # 업체 답 기다림
    call = {
        "id": "s",
        "name": "vendor_free_slots",
        "input": {"ref": "m1", "prefer": "any", "days": "any"},
    }
    log = script([{"tool_calls": [call]}, {"text": "업체가 아직 기간을 답하지 않았어요."}])
    ev = ok(ask(api, f["pid"], "실측 시간 고를래요"))
    assert cards_of(ev, "visit_slots") == []
    got = tool_result(log, 1)
    assert got["status"] == "requested" and got["candidates"] == []
    assert got["note"].startswith(customer_tools.NO_SLOTS["requested"])


def test_b6_no_wish_window_sends_no_empty_card(api, script, monkeypatch):
    vendor(api, "x3b6@mitjip.test", "마루와벽")
    _, pid = customer(api)
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "한 곳이에요."}])
    ok(ask(api, pid, "업체 추천해 줘"))
    ref = tool_result(log, 1)["picks"][0]["ref"]

    async def none(s, user, pid, vend, today, refs, *, prefer, days):
        data = VisitSlotsData(vendor_name=vend["name"], window=None, wishes=[], calendar_href="/")
        card = CardOut(card_id="wish-x", kind="visit_slots", data=data.model_dump(mode="json"))
        return card, {"vendor": vend["name"], "wishes": []}

    monkeypatch.setattr(card_tools, "wishes", none)
    call = {
        "id": "w",
        "name": "vendor_free_slots",
        "input": {"ref": ref, "prefer": "any", "days": "any"},
    }
    log = script([{"tool_calls": [call]}, {"text": "빈 일정이 없어요."}])
    ev = ok(ask(api, pid, "실측 언제 돼요?"))
    assert cards_of(ev, "visit_slots") == []
    assert tool_result(log, 1)["note"].startswith(customer_tools.NO_WISHES)


def test_b9_show_card_today_sends_no_empty_card(api, script, monkeypatch):
    _, pid = home(api)

    async def empty(s, user, pid, today_, now, refs):
        data = TodayData(date=today_, todo=[], waiting=[], news=[])
        card = CardOut(card_id="today", kind="today", data=data.model_dump(mode="json"))
        return card, {"date": today_, "todo": [], "waiting": [], "news": [], "count": 0}

    monkeypatch.setattr(card_tools, "today", empty)
    call = {"id": "s", "name": "show_card", "input": {"kind": "today"}}
    log = script([{"tool_calls": [call]}, {"text": "오늘 정할 일이 없어요."}])
    ev = ok(ask(api, pid, "오늘 정할 일 있어요?"))
    assert cards_of(ev, "today") == []
    got = tool_result(log, 1)
    assert got.get("shown") is None and got["note"] == customer_tools.TODAY_EMPTY


# ---- B7 · B10: 같은 면적 · 조사 ----


def test_b7_same_area_written_as_int_is_no_change(api, script):
    signup(api, "x3b7@mitjip.test")
    r = api.post("/projects", json={**HOME, "area_m2": "84.0", "area_basis": "exclusive"})
    assert r.status_code == 201, r.text
    call = {
        "id": "p",
        "name": "propose_home_info",
        "input": {"fields": {"area_m2": 84, "area_basis": "exclusive"}},
    }
    log = script([{"tool_calls": [call]}, {"text": "지금 집 정보와 같아요."}])
    ev = ok(ask(api, r.json()["id"], "우리 집 전용 84㎡예요"))
    assert proposed(ev) == [] and tool_result(log, 1)["error"] == "no_change"
    assert propose.same_value("area_m2", "84.0", "84")
    assert not propose.same_value("area_m2", "84.0", "84.5")


def test_b10_rejected_note_particle():
    assert propose.rejected_note("vendor").startswith("업체가 거절한 제안이에요.")
    assert propose.rejected_note("customer").startswith("고객이 거절한 제안이에요.")
    assert "업체이" not in propose.rejected_note("vendor")


# ---- B11: 공사 날 후보가 없으면 고객 날짜 요청이 없어도 다른 길(note) ----


def test_b11_my_jobs_without_candidates_gives_the_other_way(api, script, monkeypatch):
    quiet(monkeypatch)
    dates_ready(api)  # 업체(마루와벽)로 로그인해 있다

    def nothing(*_a, **_k) -> list:
        return []

    monkeypatch.setattr(vendor_tools, "date_candidates", nothing)
    log = script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {"text": "보낼 수 있는 빈 날이 없어요."},
        ]
    )
    ok(vendor_turn(api, None, "공사 날짜 보낼래요"))
    (deal,) = tool_result(log, 1)["deals"]
    assert deal["candidates"] == [] and deal["note"] == vendor_tools.NO_DAYS_NOTE


# ---- R1b #11: 넘어가기(30x)마다 주소 · 사이트 · robots를 다시 봐요 ----


def html(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def go(handler, *urls: str, image: bool = False) -> list:
    async def run() -> list:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"User-Agent": linkimage.UA}
        )
        robots: dict = {}
        async with client:
            if image:
                return [await linkimage.image_for(client, u, robots) for u in urls]
            return [await pagecheck.fetch(client, u, robots, ()) for u in urls]

    return asyncio.run(run())


def test_r1b11_page_check_rechecks_each_redirect():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        host, path = req.url.host, req.url.path
        if path == "/robots.txt":
            if host == "shop.example":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
            if host == "moved.example":  # robots.txt가 내부 주소로 넘어감: 모름(읽지 않음)
                return httpx.Response(302, headers={"location": "http://169.254.169.254/r.txt"})
            return httpx.Response(404)
        jumps = {
            "/item": "http://169.254.169.254/latest/meta-data/",
            "/item2": "https://shop.example/private/secret",
            "/item3": "/p/3",
            "/item4": "https://127.0.0.1/admin",
            "/away": "https://other.example/x",
            "/loop": "/loop",
        }
        if host == "shop.example" and path in jumps:
            return httpx.Response(302, headers={"location": jumps[path]})
        return html("<title>벽지</title>1롤 32,000원")

    got = go(
        handler,
        "https://shop.example/item",
        "https://shop.example/item2",
        "https://shop.example/item3",
        "https://shop.example/item4",
        "https://shop.example/away",
        "https://shop.example/loop",
        "https://moved.example/x",
        "https://10.0.0.5/x",
    )
    assert got[2][0] == 200 and "32,000원" in got[2][1]  # 같은 사이트 안 허용 경로는 따라가요
    assert [x for i, x in enumerate(got) if i != 2] == [(None, None)] * 7
    bad = ("169.254", "/private/", "127.0.0.1", "10.0.0.5", "other.example")
    assert not [u for u in seen if any(b in u for b in bad)], seen
    assert seen.count("https://shop.example/loop") == linkimage.MAX_HOPS + 1


def test_r1b11_images_stay_on_the_maker_site():
    seen: list[str] = []
    lx = "https://www.lxzin.com/zin/product/"

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        jumps = {"1": "https://127.0.0.1/admin", "2": f"{lx}3", "4": "https://evil.example/x"}
        n = req.url.path.rsplit("/", 1)[-1]
        if n in jumps:
            return httpx.Response(302, headers={"location": jumps[n]})
        return html('<meta property="og:image" content="https://octapi.lxzin.com/a.jpg">')

    got = go(handler, f"{lx}1", f"{lx}2", f"{lx}4", image=True)
    assert got == [None, "https://octapi.lxzin.com/a.jpg", None]
    assert not [u for u in seen if "127.0.0.1" in u or "evil.example" in u], seen


def test_r1b11_public_url():
    for url in (
        "https://shop.example/x",
        "https://8.8.8.8/",
        "https://www.lxzin.com/a",
        "https://도배.한국/",
    ):
        assert linkimage.public_url(url), url
    for url in (
        "http://shop.example/x",
        "https://169.254.169.254/x",
        "https://10.0.0.1/",
        "https://127.1/",
        "https://0x7f.1/",
        "https://2130706433/",
        "https://localhost/",
        "https://intranet/",
        "https://foo.local/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://shop.example:8443/x",
    ):
        assert not linkimage.public_url(url), url


# ---- R1b #14 · #16 · #21: 찾을 수 · 요청 점검 · 가림 자리 ----


def test_r1b14_room_counts_are_not_the_wanted_count():
    assert research.want_count("송파구 32평 방 3개 아파트 실크 벽지 추천") is None
    assert research.want_count("방 세 개 집 벽지 두 가지") == 2
    assert research.want_count("강남구 도배 업체 5곳") == 5
    assert asks.research_goal(
        "송파구 방 3개 아파트 실크 벽지", "벽지 5가지 찾아줘", "materials", 200
    ) == ("송파구 방 3개 아파트 실크 벽지 · 5가지")
    assert asks.extract("방 3개 아파트 벽지 추천해줘").count is None
    assert asks.extract("업체 4곳 방 3개 집 추천해줘").count == 4


@pytest.mark.parametrize(
    ("text", "show"),
    [
        ("집 정보 바꾸는 방법 알려줘", ()),
        ("평수 바꾸면 견적 달라져요?", ()),
        ("공정표 보여 주지 마세요", ()),
        ("공정표 안 보여 줘도 돼요", ()),
        ("집 정보 바꾸지 말고 그대로 둬", ()),
        ("표준견적서 보여 주면 좋겠어요", ("standard_quote",)),
        ("집 정보 확인하고 싶어요", ("home_info",)),
    ],
)
def test_r1b16_show_asks_skip_method_if_and_negation(text, show):
    assert asks.extract(text).show == show


@pytest.mark.parametrize(
    ("text", "price"),
    [
        ("도배 얼마나 들어요?", True),
        ("얼마로 해 주세요?", True),
        ("이 값으로 해 줘", False),
        ("이 가격으로 할게요", False),
        ("공사 얼마나 걸려요?", False),
    ],
)
def test_r1b16_price_asks(text, price):
    assert asks.extract(text).price is price


def test_r1b21_every_mask_is_taken_out_of_the_goal():
    for text, want in (
        ("서울 송파구 올림픽로 300 101동 1203호", "서울 송파구"),
        ("결도배 카톡 abc123 문의", "결도배 카톡 문의"),
    ):
        got = research.clean_goal(text)
        assert got == want and "가림" not in got, got


# ---- R1b #15: 평 맞추기로 길어진 목표도 200자 안 ----


def test_r1b15_long_goal_after_pyeong_fit_still_starts(api, script, monkeypatch):
    _, pid = home(api)

    async def pyeong(*_a):
        return Decimal("21.4")

    monkeypatch.setattr(research, "home_pyeong", pyeong)
    goal = "송파구 아파트 21평 " + "실크 벽지 친환경 제품 " * 16
    # 정리한 목표(199자)의 '21평'을 '21.4평'으로 맞추면 200자를 넘어요
    assert len(research.clean_goal(goal)) + 2 > research.GOAL_MAX
    call = {"id": "t", "name": "start_research", "input": {"kind": "materials", "goal": goal}}
    log = script([{"tool_calls": [call]}, {"text": "잠깐(1분 안팎) 걸려요."}])
    ok(ask(api, pid, "실크 벽지 알아봐 줘"))
    assert tool_result(log, 1)["state"] == "started"
    (r,) = query("select goal from assistant_research")
    assert len(r["goal"]) <= research.GOAL_MAX and "21.4평" in r["goal"]

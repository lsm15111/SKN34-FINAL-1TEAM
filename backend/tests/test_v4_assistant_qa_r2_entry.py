"""v4 비서 고침 2차 갈래 E2(입구 검사 · 개인정보 가림 · 턴 서비스 · 업체 브리핑): 빈 글 422 · 제어 문자 지움 ·
입력 가림 빈틈 16가지 · 레거시 /v2/ask 입구 가림 · 브리핑 GET 읽기만 · 열린 제안 덮지 않기 · 서비스 지역 밖 요청 ·
업체 대화 하나 · 다음에 물을 말 실패 · 먼저 말 건 옛 줄 · 끝난 줄 카드 id · 단계 제안 · health · 화면 날짜 꼴.
유료 호출 0회(Claude 대본 · 무료 모드 · 가짜 LLM)."""

import asyncio
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.agent.v3.check import mask
from app.assistant import repository as assistant_repo
from app.assistant import runtime
from app.assistant import service as assistant_service
from app.assistant.tools import vendor as vendor_tools
from app.db import SessionLocal
from app.shared.clock import today_seoul
from app.v2 import ask as v2_ask
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v2_ask import FakeLLM
from tests.test_v3_thread_api import pair, send
from tests.test_v3_visit_kit import quiet, requested, user_id
from tests.test_v4_assistant_actions import action_row, acts
from tests.test_v4_assistant_free import vendor_turn
from tests.test_v4_assistant_nudges import add_nudge, run
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


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


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


# ---- 1. 빈 글(리뷰 R1 · QA P1 입구 몫) · 2. 제어 문자(보안 L1 · L2) ----


def test_blank_turn_is_422_before_llm(api, script):
    _, pid = home(api)
    log = script([{"text": "부르면 안 돼요."}])
    for text in ("   ", "\n\t ", "\x00", "\u202e \x1b[31m"):
        assert err(ask(api, pid, text)) == (422, "invalid"), repr(text)
    f = requested(api, customer_email="blank@mitjip.test")
    login(api, f["email"])
    assert err(vendor_turn(api, f["visit"], "   ")) == (422, "invalid")
    assert log == []  # LLM을 부르지 않았다(빈 글 블록 400 → 차단기 길이 없다)
    assert query("select count(*) as n from assistant_turns")[0]["n"] == 0


def test_blank_after_mask_is_422_in_service(api):
    """스키마를 지나도(카드 단추 · 다른 입구) 가린 뒤 비면 LLM 전에 422."""
    from app.shared.errors import AppError

    _, pid = home(api)
    uid = query("select owner_id from projects")[0]["owner_id"]

    async def go():
        async with SessionLocal() as s:
            from app.auth.models import User

            user = await s.get(User, uid)
        return await assistant_service.start_turn(
            user, surface="customer", client_key="k" * 10, text=" \x00 ", project_id=pid
        )

    with pytest.raises(AppError) as e:
        run(api, go)
    assert (e.value.status, e.value.code) == (422, "invalid")


def test_nul_in_turn_text_is_dropped_before_llm_and_saved(api, script):
    """보안 L1: NUL 하나로 LLM은 다 돌고 저장에서 실패(failed)하던 일."""
    _, pid = home(api)
    log = script([{"text": "도배는 보통 하루면 끝나요."}])
    ev = ok(ask(api, pid, "도배 기간\x00 알려 줘요\u202e"))
    assert ev[-1][0] == "done"
    sent = log[0]["messages"][-1]["content"]
    assert "\x00" not in str(sent) and "\u202e" not in str(sent)
    (row,) = query("select text from chat_messages where role = 'user'")
    assert row["text"] == "도배 기간 알려 줘요"


def test_signup_and_me_names_drop_controls(api):
    r = api.post(
        "/auth/signup",
        json={"name": "가\x00나", "email": "nul@mitjip.test", "password": "pass-1234-word"},
    )
    assert r.status_code == 201, r.text
    assert query("select name from users where email = 'nul@mitjip.test'")[0]["name"] == "가나"
    r = api.patch("/me", json={"name": "가\x07\x1b[31m나\u202e다\u2066"})
    assert r.status_code == 200, r.text and r.json()["name"] == "가나다"
    assert query("select name from users where email = 'nul@mitjip.test'")[0]["name"] == "가나다"
    bad = api.post(
        "/auth/signup",
        json={"name": "\x00\u200f", "email": "nul2@mitjip.test", "password": "pass-1234-word"},
    )
    assert err(bad) == (422, "invalid")


def test_thread_message_drops_controls_and_keeps_lines(api):
    p = pair(api)
    use(api, p.customer)
    r = send(api, p.tid, "안녕\x00하세요\u202e\n둘째 줄\x1b[31m이에요")
    assert r.status_code == 201, r.text
    assert r.json()["body"] == "안녕하세요\n둘째 줄이에요"
    assert err(send(api, p.tid, "\x00 \u202e")) == (422, "invalid")


# ---- 3. 입력 가림 빈틈(보안 M1): 보고서 16가지 · 날짜 · 금액은 그대로 ----

PII = (
    "기억해 줘: 평일 저녁에만 집에 있어요. 연락처 010-2345-6789, 해외번호 +82 10-3456-7890, 집전화 02-345-6789, "
    "한글로 공일공 이삼사오 육칠팔구, 띄어 쓴 0 1 0 7 7 7 7 8 8 8 8, 빗금 010/4567/8901. "
    "주소 노원구 동일로 1234 상계주공 101-1203 (101동 1203호), 3층 2호. "
    "이메일 kim.minsu@gmail.com, kim.minsu(at)gmail.com, 카톡 아이디 minsu88. "
    "주민번호 900101-1234567, 계좌 국민 123456-12-345678, 신한 110 123 456789. 이 정보로 업체랑 일정 잡아 줘요."
)
PII_MASKED = (
    "기억해 줘: 평일 저녁에만 집에 있어요. 연락처 (번호 가림), 해외번호 (번호 가림), 집전화 (번호 가림), "
    "한글로 (번호 가림), 띄어 쓴 (번호 가림), 빗금 (번호 가림). "
    "주소 노원구 (주소 가림) 상계주공 (동호수 가림) ((동호수 가림)), (동호수 가림). "
    "이메일 (이메일 가림), (이메일 가림), 카톡 아이디 (아이디 가림). "
    "주민번호 (주민번호 가림), 계좌 국민 (계좌 가림), 신한 (계좌 가림). 이 정보로 업체랑 일정 잡아 줘요."
)
# 보안 QA t_pii_turn.py의 16가지(가린 글에 남으면 안 되는 조각)
NEEDLES = {
    "010-2345-6789": "010-2345-6789",
    "+82 10-3456-7890": "3456-7890",
    "02-345-6789": "02-345-6789",
    "공일공 이삼사오": "공일공",
    "0 1 0 7 7 7 7": "0 1 0 7 7 7 7",
    "010/4567/8901": "010/4567/8901",
    "101-1203": "101-1203",
    "101동 1203호": "1203호",
    "3층 2호": "2호",
    "동일로 1234": "동일로 1234",
    "kim.minsu@gmail.com": "@gmail.com",
    "kim.minsu(at)gmail.com": "(at)gmail",
    "minsu88": "minsu88",
    "900101-1234567": "1234567",
    "국민 123456-12-345678": "345678",
    "신한 110 123 456789": "456789",
}


def test_mask_hides_all_sixteen_forms():
    got = mask(PII)
    assert got == PII_MASKED  # 가린 결과 고정
    assert [k for k, needle in NEEDLES.items() if needle in got] == []
    assert "9(번호 가림)" not in got  # 주민번호를 전화 규칙이 먼저 가로채지 않는다


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("+82 10-3456-7890", "(번호 가림)"),
        ("82-10-3456-7890", "(번호 가림)"),
        ("010/4567/8901", "(번호 가림)"),
        ("010_4567_8901", "(번호 가림)"),
        ("(010)4567-8901", "(번호 가림)"),
        ("010 - 4567 - 8901", "(번호 가림)"),
        ("0 1 0 7 7 7 7 8 8 8 8", "(번호 가림)"),
        ("공일공 이삼사오 육칠팔구", "(번호 가림)"),
        ("상계주공 101-1203", "상계주공 (동호수 가림)"),
        ("3층 2호", "(동호수 가림)"),
        ("주소 노원구 동일로 1234", "주소 노원구 (주소 가림)"),
        ("노원구 월계로45길 11, 상계동", "노원구 (주소 가림), 상계동"),
        ("상계동 123-45번지", "상계동 (주소 가림)"),
        ("kim.minsu(at)gmail.com", "(이메일 가림)"),
        ("minsu 골뱅이 gmail 점 com", "(이메일 가림)"),
        ("카톡 아이디 minsu88.", "카톡 아이디 (아이디 가림)."),
        ("900101-1234567", "(주민번호 가림)"),
    ],
)
def test_mask_each_form(text, want):
    assert mask(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "2026-12 공사로 3,300,000원 예산이에요",
        "공사 기간 2026-12-15 ~ 2026-12-18, 34평 84.9㎡예요",
        "12.01(화) ~ 12.07(월) 사이에 실측해 주세요",
        "12.14(월) 12.15(화) 12.16(수) 사이에 해요",
        "노원구 기준으로 3곳을 골랐어요",
        "실크로 34평 견적 알려 줘요",
        "합지로 바꾸면 2,708,669원이에요",
        "노원구 상계동 아파트 100-200만 원 정도예요",
        "오전 9시 ~ 오후 6시, 3층 거실이 넓어요",
        "2호선 타고 가요",
        "도배 4.5일, 품 0.5 단위로 올림",
        "대통령령 제36437호, 제2026-360호",
        "공사 일정은 2026/01/05 부터 2026/01/09 까지예요",
        "사업자등록번호 214-86-03518이에요",
        "카톡으로 연락 주세요. 라인 LED 조명이요",
    ],
)
def test_mask_keeps_dates_money_and_plain_words(text):
    assert mask(text) == text


def test_turn_saves_and_sends_masked_text(api, script):
    _, pid = home(api)
    log = script([{"text": "연락처는 믿집 채팅으로 이어져요."}])
    ok(ask(api, pid, PII[:400]))
    sent = str(log[0]["messages"])
    assert [k for k, needle in NEEDLES.items() if needle in sent] == []
    (row,) = query("select text from chat_messages where role = 'user'")
    assert [k for k, needle in NEEDLES.items() if needle in row["text"]] == []


# ---- 4. 레거시 /v2/ask 입구 가림(보안 M2) ----


def test_v2_ask_masks_before_gate_embedding_llm_and_save(api, monkeypatch):
    fake = FakeLLM({"text": "연락처는 화면에서 바꿀 수 있어요."})
    monkeypatch.setattr(llm, "chat_tools", fake)
    seen: dict[str, list] = {"gate": [], "embed": []}

    async def classify(message, waiting=None):
        seen["gate"].append(message)

    async def embed(text):
        seen["embed"].append(text)

    monkeypatch.setattr(v2_ask.agent_gate, "classify", classify)
    monkeypatch.setattr(llm, "embed_query", embed)
    signup(api)
    text = "도배 상담이요. 제 번호 010/1234/5678, 상계주공 101-1203 (101동 1203호)\x00예요"
    r = api.post("/v2/ask", json={"message": text})
    assert r.status_code == 200, r.text
    sent = str(fake.seen[0]["messages"])
    for needle in ("1234/5678", "101-1203", "1203호", "\x00"):
        assert needle not in sent and needle not in str(seen), needle
    assert "(번호 가림)" in sent and seen["gate"] and seen["embed"]
    (row,) = query("select text from chat_messages where role = 'user'")
    assert "1234/5678" not in row["text"] and "101-1203" not in row["text"]


def test_v2_answer_only_and_grounds_mask_again(api, monkeypatch):
    fake = FakeLLM({"text": "도배는 하루면 끝나요."})
    monkeypatch.setattr(llm, "chat_tools", fake)
    queries: list[str] = []

    async def embed(text):
        queries.append(text)

    monkeypatch.setattr(llm, "embed_query", embed)
    signup(api)
    text = "카톡 아이디 minsu88, 010_1234_5678로 연락 주세요. 도배 기간은요?"
    run(api, v2_ask.answer_only, "u", text, today_seoul())
    run(api, v2_ask.grounds, text)
    assert "minsu88" not in str(fake.seen) and "1234_5678" not in str(fake.seen)
    assert queries and all("minsu88" not in q and "1234_5678" not in q for q in queries)


# ---- 5. 브리핑 GET 읽기만 · 열린 제안 덮지 않기(리뷰 B3 · 보안 L4) ----


def test_brief_get_and_post_keep_vendor_decline_card(api, monkeypatch):
    """리뷰 B3 재현의 반대: 대화로 만든 못 받아요 카드는 요청 화면을 열어도(GET · POST) 닫히지 않는다."""
    quiet(monkeypatch)
    llm.clear_stubs()
    f = requested(api)
    login(api, f["email"])
    ev = ok(vendor_turn(api, f["visit"], "일정이 꽉 차서 이번 요청은 못 받아요"))
    (dec,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert dec["kind"] == "decline"
    for method in ("get", "post"):
        r = getattr(api, method)(f"/vendor/assistant/briefs/{f['visit']}")
        assert r.status_code == 200, r.text
        assert r.json()["suggest"] is None and r.json()["windows"]  # 후보는 보이고 제안은 없다
        assert action_row(dec["action_id"])["status"] == "proposed", method
    assert query("select count(*) as n from assistant_actions")[0]["n"] == 1


def test_brief_get_reads_only_and_post_proposes_once(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    login(api, f["email"])
    got = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()
    assert got["suggest"] is None and got["windows"]
    assert (
        query("select count(*) as n from assistant_actions")[0]["n"] == 0
    )  # GET은 행을 만들지 않는다
    made = api.post(f"/vendor/assistant/briefs/{f['visit']}")
    assert made.status_code == 200, made.text
    aid = made.json()["suggest"]["action_id"]
    assert action_row(aid)["kind"] == "window_answer"
    again = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()
    assert again["suggest"]["action_id"] == aid  # 열린 제안은 GET도 보인다
    assert api.post(f"/vendor/assistant/briefs/{f['visit']}").json()["suggest"]["action_id"] == aid
    assert query("select count(*) as n from assistant_actions")[0]["n"] == 1
    # 권한: 손님 401 · 고객 403
    use(api, f["token"])
    assert api.post(f"/vendor/assistant/briefs/{f['visit']}").status_code == 403
    api.cookies.clear()
    assert api.post(f"/vendor/assistant/briefs/{f['visit']}").status_code == 401


def test_read_tool_and_nudge_keep_open_decline(api, monkeypatch, script):
    """읽기 도구 request_brief · 먼저 말 걸기(origin nudge)도 열린 못 받아요 카드를 덮지 않는다."""
    quiet(monkeypatch)
    llm.clear_stubs()
    f = requested(api)
    login(api, f["email"])
    ev = ok(vendor_turn(api, f["visit"], "일정이 꽉 차서 이번 요청은 못 받아요"))
    (dec,) = [x for x in acts(ev) if x["status"] == "proposed"]
    script(
        [
            {"tool_calls": [{"id": "b", "name": "request_brief", "input": {}}]},
            {"text": "요청을 정리했어요."},
        ]
    )
    ok(vendor_turn(api, f["visit"], "이 요청 정리해 줘"))
    assert action_row(dec["action_id"])["status"] == "proposed"
    vid = user_id(f["email"])

    async def nudge_brief():
        async with SessionLocal() as s:
            from app.auth.models import User

            user = await s.get(User, vid)
            refs = runtime.RefTable(uuid.uuid4())
            out = await vendor_tools.brief(
                s,
                user,
                uuid.UUID(f["visit"]),
                today_seoul(),
                datetime.now(UTC),
                refs,
                commit=False,
                origin="nudge",
            )
            await s.commit()
            return out

    _card, _model, data, made, closed = run(api, nudge_brief)
    assert made == [] and closed == [] and data.suggest is None
    assert action_row(dec["action_id"])["status"] == "proposed"
    assert query("select count(*) as n from assistant_actions")[0]["n"] == 1


# ---- 6. 서비스 지역 밖 요청(리드 결정 D11) ----


def test_out_of_area_request_is_check_and_keeps_window(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    login(api, f["email"])
    vid = uuid.UUID(f["vendor"])
    query("delete from vendor_areas where vendor_id = $1", vid)
    query("insert into vendor_areas (vendor_id, sido, sgg) values ($1, 'seoul', '도봉구')", vid)
    b = api.post(f"/vendor/assistant/briefs/{f['visit']}").json()
    area = next(x for x in b["fit"] if x["key"] == "area")
    assert (area["ok"], area["state"]) == (False, "check")
    assert area["text"].endswith("서비스 지역 밖(가까운 구)")
    assert b["windows"] and b["suggest"]  # 기간 후보 · 답하기 제안은 그대로
    assert "못 받아요" not in b["sentence"]
    query("delete from vendor_areas where vendor_id = $1", vid)
    query("insert into vendor_areas (vendor_id, sido, sgg) values ($1, 'seoul', '강남구')", vid)
    far = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()
    area = next(x for x in far["fit"] if x["key"] == "area")
    assert area["state"] == "check" and area["text"].endswith("서비스 지역 밖")


def test_template_says_out_of_area_check():
    from app.assistant.schemas import BriefHalves, FitRow, VendorBriefData

    data = VendorBriefData(
        visit_id=uuid.uuid4(),
        title="노원구 · 도배",
        facts=[],
        fit=[
            FitRow(key="trade", label="공정", ok=True, text="도배 요청", state="ok"),
            FitRow(
                key="area",
                label="지역",
                ok=False,
                text="서울 노원구 · 서비스 지역 밖",
                state="check",
            ),
        ],
        estimate=None,
        halves=BriefHalves(days=[], taken={}, open_count=0),
        suggest=None,
        due_at=None,
        memo=None,
    )
    assert (
        vendor_tools.brief_template(data) == "서비스 지역 밖 요청이에요. 요청을 열어 확인해 주세요."
    )


# ---- 7. 업체 대화 하나(R8) · 다음에 물을 말 실패(R10) · 먼저 말 건 옛 줄(R13) ----


def test_vendor_chat_is_made_once_when_opened_together(api):
    f = requested(api)
    vid = user_id(f["email"])

    async def open_one():
        async with SessionLocal() as s:
            chat = await assistant_service.ensure_chat(s, vid, None)
            await asyncio.sleep(0.2)  # 다른 쪽이 같은 때 읽게 둔다
            await s.commit()
            return chat.id

    async def both():
        return await asyncio.gather(open_one(), open_one())

    a, b = run(api, both)
    assert a == b
    rows = query("select count(*) as n from chats where user_id = $1 and kind = 'assistant'", vid)
    assert rows[0]["n"] == 1


def test_suggest_failure_keeps_saved_turn_done(api, monkeypatch):
    _, pid = home(api)

    async def boom(*_a, **_k):
        raise RuntimeError("읽기 실패")

    monkeypatch.setattr(assistant_repo, "shown_nudges", boom)
    ev = ok(ask(api, pid, "안녕하세요"))
    assert ev[-1][0] == "done" and ev[-1][1]["suggest"] == []
    assert query("select status from assistant_turns")[0]["status"] == "done"


def test_feed_keeps_old_nudge_lines_when_chat_is_short(api):
    _, pid = home(api)
    uid = query("select owner_id from projects")[0]["owner_id"]
    start = datetime.now(UTC) - timedelta(days=40)
    for i in range(35):
        add_nudge(
            uid,
            trigger="dates_proposed",
            channel="feed",
            status="sent",
            project_id=uuid.UUID(pid),
            sent_at=start + timedelta(days=i),
            body=f"먼저 말 건 줄 {i}",
            src="guide",
        )
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    lines = [x for x in feed["items"] if x.get("nudge_id")]
    assert len(lines) == 35 and feed["before"] is None


# ---- 8. 끝난 먼저 말 건 줄 카드 id(QA P4) ----


def test_card_id_with_line_suffix_is_accepted(api):
    _, pid = home(api)
    card_id = f"slots-{uuid.uuid4()}@{uuid.uuid4()}"
    assert len(card_id) == 79
    r = ask(
        api, pid, "토요일 오전으로 할래요", context={"card_id": card_id, "choice": "visit_slot:s2"}
    )
    ev = ok(r)
    assert ev[-1][0] == "done"
    assert assistant_service.card_of(card_id) == card_id.split("@")[0]
    assert assistant_service.card_of("") is None and assistant_service.card_of(None) is None


# ---- 9. 다음에 물을 말 단계(QA P12, P5는 고침 B 시험) ----


def _overview(phase: str, code: str, start: date | None = None):
    nxt = SimpleNamespace(kind="start", day=start) if start else None
    return SimpleNamespace(phase=phase, todo=SimpleNamespace(code=code), next=nxt, trades=[])


def test_step_key_follows_work_stage():
    today = today_seoul()
    assert (
        assistant_service.step_key(_overview("done", "done"), today) is None
    )  # 끝난 공사: 전날 준비물 아님
    assert assistant_service.step_key(_overview("work", "working"), today) is None
    assert assistant_service.step_key(_overview("work", "check"), today) == "check"
    tomorrow = today + timedelta(days=1)
    assert assistant_service.step_key(_overview("work", "before_work", tomorrow), today) == "eve"
    later = today + timedelta(days=9)
    assert assistant_service.step_key(_overview("work", "before_work", later), today) == "prep"


# ---- 10. health는 화면에 필요한 값만(보안 I3) ----


def test_health_hides_service_cap_and_breaker(api, monkeypatch):
    from app.usage import service as usage

    signup(api)
    monkeypatch.setattr(llm, "available", lambda: True)

    async def closed():
        return True

    async def opened():
        return False

    def cap(scope):
        async def allow(_uid, _label):
            if scope:
                raise usage.OverCap(scope, 10, 10)

        return allow

    monkeypatch.setattr(runtime, "breaker_open", closed)
    monkeypatch.setattr(usage, "allow", cap(None))
    assert api.get("/assistant/health").json() == {"mode": "free", "reason": "off"}
    monkeypatch.setattr(runtime, "breaker_open", opened)
    for scope, want in (("service_day", "off"), ("total", "off"), ("user_day", "budget")):
        monkeypatch.setattr(usage, "allow", cap(scope))
        assert api.get("/assistant/health").json() == {"mode": "free", "reason": want}, scope
    monkeypatch.setattr(usage, "allow", cap(None))
    assert api.get("/assistant/health").json() == {"mode": "llm", "reason": "ok"}


# ---- 11. 화면 날짜 꼴(리뷰 프런트 #4, 내 파일 몫) ----


def test_brief_and_board_show_short_korean_dates(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    query("update visits set work_wish_on = current_date + 40")
    login(api, f["email"])
    b = api.post(f"/vendor/assistant/briefs/{f['visit']}").json()
    shown = [*b["facts"], *(x["text"] for x in b["fit"])]
    assert not [x for x in shown if ISO.search(x)], shown
    assert any(x.startswith("공사 시작 희망 ") for x in b["facts"])
    summary = json.loads(action_row(b["suggest"]["action_id"])["summary"])
    period = next(r["value"] for r in summary["rows"] if r["label"] == "기간")
    assert not ISO.search(period) and "(" in period  # '12.15(화) ~ 12.21(월)'
    use(api, f["token"])
    board = api.get("/assistant/board", params={"project_id": f["pid"]}).json()
    assert board["period"] and not ISO.search(board["period"]["value"])


def test_brief_tool_keeps_iso_dates_for_number_check(api, script):
    """화면 글을 '12.15(화)' 꼴로 바꿔도 모델 값에는 ISO 날짜가 있어 '12월 15일' 문장이 숫자 검사를 지난다."""
    f = requested(api)
    query("update visits set work_wish_on = current_date + 40")
    login(api, f["email"])
    log = script(
        [
            {"tool_calls": [{"id": "b", "name": "request_brief", "input": {}}]},
            {"text": "요청을 정리했어요."},
        ]
    )
    ok(vendor_turn(api, f["visit"], "이 요청 정리해 줘"))
    got = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    assert ISO.fullmatch(got["wish_start"]) and ISO.fullmatch(got["wish_end"])
    assert ISO.fullmatch(got["work_wish_on"])
    sched = next(x for x in got["fit"] if x["label"] == "일정")
    assert sched["text"].startswith("고객 희망 ") and not ISO.search(sched["text"])

"""점검 고침 X6 에이전트 · 숫자 검사(2026-11-24).

- R6 B1: 309자리 넘는 숫자 줄이 숫자 검사(guard)에서 OverflowError → /ai/turns · /v2/ask 500, 비서 턴 error.
- R6 B2: v2 상담 대화가 v3 AI 칸 목록 · 이어 보기에 섞이고, v2 waiting('orchestrator')으로 v3 턴을 이으면 500.
- R6 B4: search3 공종 표 캐시가 id(ix)로 잡혀 새 색인이 옛 표를 받음.
- R6 B5: 전각 숫자 · '오만 원' · '이십오만 원' · '일억 원' · '이십오 평'이 숫자 검사를 지나감.
- R6 B6: 빈 질문 + 의미 검색 결과면 bm25.search가 ValueError.
- R1a B2: 비서 문장 숫자 검사가 값만 견줌 → 단위(일 · 주 · 개월 · 시간 · 배 · %) · 요일 · 다른 공정 기간도 근거와 같아야 해요.
DB 없는 검사 + 무료 모드 API + Claude 대본 비서 턴(유료 호출 0회)."""

import asyncio
import gc
import json
import random
import uuid

import pytest
from v3_kb import repo_index

from app.agent import intent as clf
from app.agent import llm
from app.assistant import prompts, runtime
from app.knowledge import bm25, search3
from app.v2 import guard
from tests.conftest import query
from tests.helpers import signup
from tests.test_v4_assistant_turns import ask as assistant_ask
from tests.test_v4_assistant_turns import events, home

BIG = "9" * 400  # float으로 inf가 되는 길이(309자리 넘음)
FACTS = """지금: 11월 24일(화) 오후 3시
올해: 2026년
업체: 결도배(m1) 견적서 옴(1판 · 부가세 포함 3,520,000원) / 마루와벽(m2) 견적서 옴(2판 · 부가세 포함 3,820,000원)
공정표: 예상 공정표 · 예상 공사 12월 15일(화)~17일(목) · 일하는 날 3일
집: 노원구 · 32평형(공급) · 방 3개"""
STANDARD = "표준견적서 합계 1,974,069원"


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


def said(text: str, allowed: str = FACTS, *more: str) -> str:
    """비서 문장 검사(SentenceGate)를 지나 고객에게 간 글(빠지면 '')."""
    out: list[str] = []

    async def emit(name: str, data: dict) -> None:
        out.append(data.get("text", ""))

    async def go() -> None:
        g = runtime.SentenceGate(emit, prompts.rules("customer"), allowed)
        for x in more:
            g.allow(x)
        await g.feed(text + " ")
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return "".join(out).strip()


# ---- R1a B2: 단위 · 요일 · 다른 공정 기간 ----


@pytest.mark.parametrize(
    "text",
    [
        "공사는 3주예요.",  # 근거는 3일
        "공사는 3개월 걸려요.",
        "업체가 32시간 안에 답해요.",  # 32는 32평형
        "결도배가 2배 더 비싸요.",  # 2는 2판
        "마루와벽이 3% 더 비싸요.",
        "공사는 12월 15일(월)에 시작해요.",  # 근거는 (화)
        "공사는 12월 15일 월요일에 시작해요.",
        "15일(월)에 시작해요.",
        "욕실 공사는 보통 3일 걸려요.",  # 3일은 도배 일하는 날
        "욕실은 3일이면 끝나요.",
        "바닥 공사는 2주쯤 걸려요.",
        "32평이면 보통 2일이면 끝나요.",
        "2~3일 걸려요.",  # 2는 2판(단위 없음)
    ],
)
def test_period_ratio_weekday_and_other_trade_must_match_the_ground(text):
    assert said(text) == ""


@pytest.mark.parametrize(
    "text",
    [
        "공사는 12월 15일(화)에 시작해서 3일 걸려요.",
        "일하는 날은 3일이에요.",
        "15일(화)에 시작해서 17일(목)에 끝나요.",
        "공사는 12월 15일 화요일에 시작해요.",
        "기존 벽지 철거까지 3일 걸려요.",  # 철거는 도배 견적 칸
        "욕실 공사가 끝난 뒤 도배는 3일 걸려요.",  # 기간 앞 가까운 공정은 도배
        "결도배는 15일, 마루와벽은 17일에 시작해요.",  # 업체 이름의 '마루'는 바닥 공정이 아님
        "결도배는 약 350만 원이에요.",  # 금액 검사는 그대로
        "두 곳 차이는 30만 원이에요.",
        "방 3개예요.",
    ],
)
def test_grounded_periods_and_weekdays_still_pass(text):
    assert said(text) == text


def test_tool_fields_give_units_and_weekdays():
    tool = json.dumps(
        {"work_days": 3, "warranty_months": 12, "start": "2026-12-15"}, ensure_ascii=False
    )
    assert said("보증은 12개월이에요.", "", tool) == "보증은 12개월이에요."
    assert said("일하는 날은 3일이에요.", "", tool) == "일하는 날은 3일이에요."
    assert said("보증은 12주예요.", "", tool) == ""
    assert (
        said("12월 15일(화)에 시작해요.", "", tool) == "12월 15일(화)에 시작해요."
    )  # 연도로 센 요일
    assert said("12월 15일(월)에 시작해요.", "", tool) == ""


def test_weekday_of_a_date_without_one_in_the_ground_uses_today():
    """근거에 요일이 없는 날짜(고객 말)는 '지금' · '올해' 줄의 오늘에 가장 가까운 해로 센다."""
    ground = "지금: 11월 24일(화) 오후 3시\n올해: 2026년\n12월 20일이나 1월 4일에 하고 싶어요"
    assert said("12월 20일(일)에 할 수 있어요.", ground) == "12월 20일(일)에 할 수 있어요."
    assert said("12월 20일(토)에 할 수 있어요.", ground) == ""
    assert said("1월 4일(월)도 돼요.", ground) == "1월 4일(월)도 돼요."  # 2027년
    assert said("1월 4일(일)도 돼요.", ground) == ""


def test_other_trade_period_passes_only_from_a_line_about_that_trade():
    ground = FACTS + "\n욕실은 5일 걸린대요. 2~3일 걸리는 일도 있어요"
    assert said("욕실 공사가 5일 걸리면 그 뒤에 도배해요.", ground) == (
        "욕실 공사가 5일 걸리면 그 뒤에 도배해요."
    )
    assert said("2~3일 걸려요.", ground) == "2~3일 걸려요."
    assert said("타일 공사는 5일 걸려요.", ground) == ""


# ---- R6 B1: 아주 긴 숫자 줄 ----


def test_digit_runs_past_float_do_not_overflow():
    assert guard.numbers(BIG) == set()
    assert guard.numbers(f"{BIG}원 {BIG}억") == set()
    got = guard.check(f"도배 {BIG}원이에요.", f"도배 {BIG}원")
    assert got.text == "" and got.dropped
    g = guard.ground(f"도배 {BIG}원 {BIG}평 {BIG}억 원", guard.basis([f"도배 {BIG}원"]))
    bad, _ = guard.loose(f"도배 {BIG}원이에요.", g)
    assert bad is not None
    assert said(f"도배 {BIG}원이에요.", f"도배 {BIG}") == ""


def test_ai_turns_and_v2_ask_answer_a_digit_run(api):
    signup(api)
    r = api.post(
        "/ai/turns", json={"text": f"도배 {BIG}", "client_key": "x6-audit-big-1", "context": {}}
    )
    assert r.status_code == 200, r.text[:200]
    assert "event: done" in r.text
    r = api.post("/v2/ask", json={"message": f"도배 {BIG}"})
    assert r.status_code == 200, r.text[:200]


def test_assistant_turn_with_a_digit_run_is_done(api, script):
    _, pid = home(api)
    script([{"text": "도배 견적은 표준견적서에서 볼 수 있어요."}])
    r = assistant_ask(api, pid, f"도배 {BIG} 얼마예요?")
    assert r.status_code == 200
    assert [e for e, _, _ in events(r.text)][-1] == "done"


# ---- R6 B2: v2 상담 대화와 v3 AI 칸 ----


def test_v2_chat_stays_out_of_the_v3_panel(api, monkeypatch):
    async def fake_chat_tools(system, messages, tools):
        return {"text": "몇 평인지 알려 주실래요? [되물음]", "tool_calls": [], "stop": "stop"}

    monkeypatch.setattr(llm, "chat_tools", fake_chat_tools)
    signup(api)
    r = api.post("/v2/ask", json={"message": "도배하고 싶은데 처음이라 잘 몰라요"})
    assert r.status_code == 200, r.text
    v2_chat = r.json()["chat_id"]
    assert v2_chat
    assert query("select kind from chats where id = $1", uuid.UUID(v2_chat))[0]["kind"] == "v2"
    assert all(x["chat_id"] != v2_chat for x in api.get("/ai/threads").json())
    assert api.get("/ai/threads/latest").json() is None
    assert api.get(f"/ai/threads/{v2_chat}").status_code == 404
    body = {"text": "네", "client_key": "x6-audit-k1", "chat_id": v2_chat, "context": {}}
    assert api.post("/ai/turns", json=body).status_code == 404
    # v2는 제 대화를 그대로 이어 가요
    r = api.post("/v2/ask", json={"message": "32평이요", "chat_id": v2_chat})
    assert r.status_code == 200, r.text
    assert r.json()["chat_id"] == v2_chat


def test_v3_turn_drops_a_waiting_label_that_is_not_a_v3_route(api):
    """0055 전 v2 대화는 kind ai · waiting 'orchestrator'로 남아 있어요(Redis 되묻기 칸 없음). v3 담당으로 읽지 않아요."""
    signup(api)
    cid = uuid.uuid4()
    query(
        "insert into chats (id, user_id, rev, waiting, kind) values ($1, $2, 2, 'orchestrator', 'ai')",
        cid,
        uuid.UUID(api.get("/me").json()["id"]),
    )
    short = next(
        x for x in ("네", "음", "그거요") if max((clf.probs(x) or {x: 1.0}).values()) < 0.7
    )
    body = {"text": short, "client_key": "x6-audit-k3", "chat_id": str(cid), "context": {}}
    r = api.post("/ai/turns", json=body)
    assert r.status_code == 200, r.text[:300]
    assert "event: done" in r.text


# ---- R6 B4: 공종 표 캐시 ----


def test_scope_table_follows_the_index_not_its_address():
    tags = {"도배": "dobae", "목공": "mokgong", "공통": "common"}

    def make(trade: str) -> bm25.Index:
        chunk = bm25.Chunk(ref="K1", doc="d", text="몰딩 문틀 벽지", trades=(trade,), rid="ds/1")
        return bm25.build([chunk], {"d": bm25.Doc(title="t", kind="kcs")})

    gc.collect()
    before = len(search3._scope_cache)
    rnd = random.Random(7)
    cur = make("도배")
    search3.scopes(cur, tags)
    for _ in range(300):
        trade = rnd.choice(["목공", "도배"])
        cur = make(trade)  # 옛 색인을 버린다(knowledge.service._cache 꼴)
        assert search3.scopes(cur, tags) == {"K1": frozenset({tags[trade]})}
    gc.collect()
    assert len(search3._scope_cache) <= before + 1


# ---- R6 B5: 전각 숫자 · 한글 숫자 ----


@pytest.mark.parametrize(
    "text",
    [
        "약 ３００만 원이에요.",
        "도배는 오만 원이에요.",
        "이십오만 원이에요.",
        "일억 원이에요.",
        "이십오 평이에요.",
    ],
)
def test_wide_digits_and_hangul_numbers_are_checked(text):
    assert guard.check(text, STANDARD).text == ""  # v2
    assert guard._why(text, guard.numbers(STANDARD)) is not None  # v3 sentence_ok
    assert said(text, STANDARD) == ""  # v4


@pytest.mark.parametrize(
    "text",
    [
        "합계는 １,９７４,０６９원이에요.",  # 전각이어도 근거 값이면 지나요
        "도배 공사만 원하시면 말씀해 주세요.",
        "도배 일만 원래 날짜에 해요.",
        "이 평수면 실크가 잘 맞아요.",
    ],
)
def test_words_that_only_look_like_numbers_pass(text):
    assert guard._why(text, guard.numbers(STANDARD)) is None


# ---- R6 B6: 빈 질문 + 의미 검색 ----


def test_empty_question_with_dense_hits_does_not_raise():
    chunk = bm25.Chunk(ref="K1", doc="d", text="벽지 초배 시공 순서", trades=("도배",), rid="ds/1")
    ix = bm25.build([chunk], {"d": bm25.Doc(title="t", kind="kcs")})
    got = bm25.search(ix, "", dense=["ds/1"])
    assert [h.ref for h in got.hits] == ["K1"] and got.enough is False

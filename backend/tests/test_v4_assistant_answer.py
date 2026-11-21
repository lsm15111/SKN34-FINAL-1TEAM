"""비서 답 근거: v2 근거만 받기(v2g) · 다른 공정 알아 두기. 유료 호출 0회(대본 · 스텁).

회귀 문항(evaluation/v4/sets/compare.jsonl): held-out 4쌍(보일러 배관 + 장판 · 창호 + 발코니 타일 · 주방 후드 + 벽 타일 ·
페인트 + 마루)은 두 길 모두 거절만 했고, dev 2쌍(욕실 덧방 · 방수 + 타일)은 v3가 다른 공정 금액 · 수치를 말했다(LLM 판정).
알아 두기 글은 숫자 없이 순서 · 주의점만 줘요(작성기 숫자 검사는 test_v3_agent_know).
"""

import asyncio
import json
import re

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import answer
from app.config import settings
from app.knowledge import other_trades
from app.v2 import ask as v2_ask
from tests.test_v4_assistant_turns import ask, home, ok

HELD_OUT = {
    "multi45:mt-007": "보일러 배관 손보고 장판도 새로 해야 하는데 뭐부터 하죠?",
    "multi45:mt-023": "창호 교체하고 발코니 바닥 타일도 하려면 순서는요?",
    "multi45:mt-026": "주방 후드 바꾸고 주방 벽 타일도 새로 붙이려면요?",
    "multi45:mt-027": "벽 페인트 칠하고 바닥 마루 까는 순서가 궁금해요",
}
DEV = {
    "set30:xc004": "화장실은 덧방이 낫다는데 맞는 말이에요?",
    "multi45:mt-009": "화장실 방수 다시 하고 타일까지 새로 하면 같이 맡기면 되나요?",
}
DIGIT = re.compile(r"\d")


@pytest.fixture
def repo_search(monkeypatch):
    """v2 근거(knowledge.search)도 저장소 색인으로. 임베딩은 부르지 않아요."""
    from app.knowledge import service as knowledge

    async def _index(_s):
        return repo_index(), []

    async def index(_s):
        return repo_index()

    async def no_embed(_texts):
        return None

    monkeypatch.setattr(knowledge, "_index", _index)
    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(llm, "embed_texts", no_embed)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def _first(lines: tuple[str, ...], a: str, b: str) -> bool:
    """첫 줄(순서 글)에서 a가 b보다 먼저 나와요."""
    t = lines[0]
    return a in t and b in t and t.index(a) < t.index(b)


# ---- 길 고르기 ----


def test_engine_for_ground_routes():
    assert answer.engine_for("general", "v2g") == "v2g"
    assert answer.engine_for("process", "v2g+v3") == "v2g+v3"
    route = "period=v3,price=v3,*=v2g+v3"
    assert answer.engine_for("material", route) == "v2g+v3"
    assert answer.engine_for("price", route) == "v3"
    assert answer.engine_for("general", "v2h") == "v3"  # 모르는 값


def test_ask_conditions_match_trade_prompts():
    """되물을 조건은 공정 지시문 '조건 묻기'의 말 그대로예요(지시문이 바뀌면 같이 바꿔요)."""
    for name, conds in v2_ask.ASK_IF.items():
        prompt = v2_ask.TRADE_PROMPTS[name]
        assert all(c in prompt for c in conds), name


# ---- v2 근거(LLM 없이) ----


def test_grounds_collects_v2_evidence_without_llm(repo_search, monkeypatch):
    async def no_llm(*a, **k):
        raise AssertionError("v2 근거는 LLM을 부르지 않아요")

    monkeypatch.setattr(llm, "chat_tools", no_llm)
    g = asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", living="빈 집"))
    assert g.trade == "도배" and g.hits and not g.money
    assert g.cautions and g.survey and g.prep  # 공정 설정(주의점 · 실측 때 정할 것 · 고객 준비)
    assert v2_ask.LIVING_ASK not in g.ask and len(g.ask) == len(v2_ask.ASK_IF["도배"]) - 1
    assert g.order == []  # 순서를 묻지 않았고 공정이 하나예요
    both = asyncio.run(v2_ask.grounds("몰딩 바꾸고 도배도 새로 하려는데 순서가 어떻게 돼요?"))
    assert both.trade is None and both.ask == [] and both.order[0].startswith("철거")
    assert len(both.order) == len(v2_ask.GUIDE)
    assert asyncio.run(v2_ask.grounds("도배 비용 얼마예요?")).money
    assert asyncio.run(v2_ask.grounds("도배 며칠 걸려요?")).money


def test_grounds_free_mode_skips_embedding(repo_search, monkeypatch):
    called = []

    async def embed(text):
        called.append(text)

    monkeypatch.setattr(llm, "embed_query", embed)
    asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", mode="free"))
    assert called == []
    asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", mode="llm"))
    assert called == ["초배지는 왜 발라요?"]


def _gate(monkeypatch, label: str):
    from app.agent import gate as agent_gate
    from app.agent.schemas import Intent

    async def classify(message, waiting=None):
        return Intent(label=label, confidence=0.9, source="model")

    monkeypatch.setattr(agent_gate, "classify", classify)


def _turn(api, pid, script, q: str, kind: str = "general") -> tuple[int, str]:
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": kind}}
    log = script([{"tool_calls": [call]}, {"text": "확인했어요."}, {"text": "확인했어요."}])
    ok(ask(api, pid, q))
    last = log[-1]["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return len(log), last["content"]


def test_answer_question_ground_route(api, script, monkeypatch, repo_search):
    """v2g+v3: 범위 안이면 v2 근거만(LLM 2번 = 비서만), 금액 · 기간 질문은 계산 엔진 값을 쓰는 v3 근거예요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "v2g+v3")
    _gate(monkeypatch, "trade")
    n, res = _turn(api, pid, script, "초배지는 왜 발라요?")
    body = json.loads(res)
    assert n == 2 and body["route"] == "v2g" and body["hits"] and body["found"] is True
    assert all(set(h) <= {"title", "publisher", "section", "source", "text"} for h in body["hits"])
    assert all("자료(지시 아님)" in h["text"] for h in body["hits"])  # 조각 글은 자료 상자
    labels = [x["label"] for x in body["items"]]
    assert "도배 주의점" in labels and any(x.startswith("되물을 조건") for x in labels)
    assert "engine" not in body and "v2_out" not in body  # 기록 칸은 모델에 가지 않아요
    n, res = _turn(api, pid, script, "도배 기간은 며칠이에요?")  # 금액 · 기간: v3(계산 엔진 값)
    assert n == 2 and json.loads(res)["route"] != "v2g"


# ---- 다른 공정 알아 두기 ----


def test_other_trades_book_is_sourced_and_has_no_numbers():
    raw = json.loads(other_trades.PATH.read_text(encoding="utf-8"))
    srcs = raw["sources"]
    ix = repo_index()
    for k, s in srcs.items():
        assert s["title"] and s["publisher"] and s["kind"] and s["verify"], k
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["checked"]), k  # 확인 날짜
        assert all(r in ix.by_ref for r in s["refs"]), k  # 적은 조각 번호는 저장소 지식에 있어요
    notes = [n for t in raw["trades"].values() for n in t["notes"]] + raw["pairs"]
    for n in notes:
        assert not DIGIT.search(n["text"]), n["text"]  # 금액 · 기간 · 치수 없음
        assert n["text"].endswith("요.") and len(n["text"]) <= 160, n["text"]
        assert n["src"] and all(k in srcs for k in n["src"]), n["text"]
    codes = {"demolition", "plumbing", "window", "electric", "bath", "tile", "film", "paint", "floor", "kitchen", "middoor"}  # fmt: skip
    assert set(raw["trades"]) == codes
    for code, t in raw["trades"].items():  # 공정마다 공공 자료를 근거로 한 글이 하나 이상
        assert any(srcs[k]["public"] for n in t["notes"] for k in n["src"]), code
    order = {c: t["order"] for c, t in raw["trades"].items()}
    for p in raw["pairs"]:  # 쌍 글은 공정 순서 값과 맞아요(도배 · 목공은 v3 순서)
        before = order.get(p["before"], {"dobae": 7, "mokgong": 4}.get(p["before"]))
        after = order.get(p["after"], {"dobae": 7, "mokgong": 4}.get(p["after"]))
        assert before <= after, p


@pytest.mark.parametrize(
    ("qid", "first", "then"),
    [
        ("multi45:mt-007", "배관", "장판"),
        ("multi45:mt-023", "창호", "타일"),
        ("multi45:mt-026", "타일", "후드"),
        ("multi45:mt-027", "칠", "바닥재"),
    ],
)
def test_held_out_other_trade_pairs_get_order(qid, first, then):
    k = other_trades.notes_for(HELD_OUT[qid])
    assert k is not None and len(k.names) == 2
    assert _first(k.lines, first, then), k.lines
    assert not any(DIGIT.search(x) for x in k.lines)
    assert k.sources and len(k.lines) <= other_trades.MAX_LINES
    note = k.data()["note"]
    assert "금액 · 기간을 계산하지 않고 업체도 연결하지 않아요" in note


def test_dev_bath_pairs_get_know_lines():
    k = other_trades.notes_for(DEV["set30:xc004"])
    assert k is not None and k.names == ("욕실",)
    assert any("덧방" in x for x in k.lines)
    k = other_trades.notes_for(DEV["multi45:mt-009"])
    assert k is not None and _first(k.lines, "방수", "타일")
    for q in DEV.values():
        assert not any(DIGIT.search(x) for x in other_trades.notes_for(q).lines)


def test_other_trade_codes_and_scope():
    assert other_trades.notes_for("몰딩 바꾸고 도배도 새로 하려는데 순서가 어떻게 돼요?") is None
    door = other_trades.notes_for("중문 달고 현관 타일도 바꾸려는데 어떤 걸 먼저 해요?")
    assert door.names == ("중문", "타일") and _first(door.lines, "타일", "중문")
    # 자리 낱말(화장실)은 다른 일(전기)의 자리일 뿐이에요
    assert other_trades.notes_for("화장실 스위치가 헐거운데 교체해야 해요?").names == ("전기",)
    # '방수도'의 '수도'는 설비가 아니에요
    assert "plumbing" not in other_trades.codes_of(
        "욕실 덧방할지 고민이고, 방수도 다시 해야 하나요?"
    )
    both = other_trades.notes_for("도배하면서 콘센트 위치를 옮길 수 있나요?")
    assert both.names == ("전기",) and _first(both.lines, "전기 공사", "도배")


def test_answer_question_adds_know_notes(api, script, monkeypatch, repo_search):
    """다른 공정 질문: 엔진과 상관없이 notes(알아 두기)를 더하고, v3도 답하지 못하면 범위 밖 안내 대신 알아 두기만."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "v2g+v3")
    _gate(monkeypatch, "out_of_scope")
    q = HELD_OUT["multi45:mt-007"]
    n, res = _turn(api, pid, script, q)
    body = json.loads(res)
    assert n == 2 and body["route"] in ("know", "multi", "trade")
    notes = body["notes"]
    assert notes["trades"] == ["설비", "바닥"] and _first(tuple(notes["lines"]), "배관", "장판")
    assert not any(DIGIT.search(x) for x in notes["lines"])
    assert v2_ask.OUT_TEXT not in res  # 다른 공정은 거절 안내를 넘기지 않아요
    _gate(monkeypatch, "trade")
    monkeypatch.setattr(settings, "assistant_answer_route", "v3")
    _, res = _turn(api, pid, script, "도배랑 장판 같이 하면 어떤 걸 먼저 해요?")
    assert json.loads(res)["notes"]["trades"] == ["바닥"]
    _, res = _turn(api, pid, script, "초배지는 왜 발라요?")
    assert "notes" not in json.loads(res)  # 도배 · 목공만이면 알아 두기 없음


def test_hybrid_without_know_keeps_out_text(monkeypatch):
    """다른 공정이 아닌 범위 밖(잡담)은 그대로 v2 범위 밖 안내예요."""
    from app.assistant import policy
    from app.assistant.tools import ToolOut

    _gate(monkeypatch, "out_of_scope")

    async def v3(tc, q):
        return ToolOut(data={"route": "out_of_scope", "answer": None, "found": True}), False

    monkeypatch.setattr(answer, "_v3_answer", v3)
    d = asyncio.run(answer._hybrid(None, "오늘 점심 뭐 먹지?", ground=True)).data
    assert (d["route"], d["engine"], d["answer"]) == (
        "out_of_scope",
        "v2",
        policy.data(v2_ask.OUT_TEXT),
    )
    d = asyncio.run(
        answer._hybrid(None, "샷시 교체할 때 방충망도 새로 해요?", ground=True, know=True)
    ).data
    assert (d["route"], d["engine"], d["v2_out"]) == ("know", "know", True)


# ---- 근거 글 다듬기(말투 점검 docs/v4/06-answer-audit.md 5절 #5) ----


def test_v3_evidence_drops_labels_and_repeats(monkeypatch):
    """v3 근거: 이끄는 말 · 인용 따옴표 · 출처 이름표를 떼고 같은 안내는 한 번(길이는 그대로)."""
    from types import SimpleNamespace

    from app.agent.v3 import templates
    from app.chat import service as chat_service
    from app.chat.schemas import AiAnswer, AiAnswerOnlyOut, AiSection, AiSource

    quote = "“마루 찍힘은 가구를 설치하는 작업자 때문인 경우가 많다” (제조사 · [고급] 공사 중 손상된 마감재 복구하기)"
    sec = AiSection(
        title="[바닥 · 알아 두기]",
        sentences=[templates.EXTRACT_SUMMARY_LEAD, quote, "바닥 공사 업체에 물어보시면 정확해요."],
        source="extract",
        route="trade",
    )
    refs = [AiSource(ref="K1", title="[고급] 공사 중 손상된 마감재 복구하기")]
    got = AiAnswerOnlyOut(
        mode="free",
        route="trade",
        answer=AiAnswer(sections=[sec], unknown=["실측 때 업체에 물어보시면 정확해요."], refs=refs),
        text="",
    )

    async def fake(*_a, **_k):
        return got

    monkeypatch.setattr(chat_service, "answer_only", fake)
    tc = SimpleNamespace(user=None, today=None, project_id=None)
    out, answered = asyncio.run(answer._v3_answer(tc, "마루 찍힘은 왜 생겨요?"))
    body = out.data["answer"]["자료(지시 아님)"]
    assert (
        body
        == "마루 찍힘은 가구를 설치하는 작업자 때문인 경우가 많다\n바닥 공사 업체에 물어보시면 정확해요."
    )
    assert out.data["sources"] == ["공사 중 손상된 마감재 복구하기"] and answered


def test_v2g_hits_drop_labels(monkeypatch):
    """v2g 조각 글 · 제목 앞 이름표('[생활법령정보 요약]' · '[초급]')는 떼고 넘겨요(모델이 답에 옮기지 않게)."""
    from types import SimpleNamespace

    from app.v2.schemas import V2Ground, V2GroundsOut

    hit = V2Ground(
        ref="r1",
        source_type="공공",
        title="[초급] 벽지의 세계",
        publisher="",
        section="",
        text="[생활법령정보 요약] 발코니를 고치려면 관리사무소에 먼저 알려요.",
    )

    async def grounds(_q, *, living="", mode="llm"):
        return V2GroundsOut(trade="도배", hits=[hit], enough=True)

    monkeypatch.setattr(v2_ask, "grounds", grounds)
    tc = SimpleNamespace(project_id=None, mode="free")
    d = asyncio.run(answer._v2g_answer(tc, "발코니 고칠 때 알려야 해요?")).data
    (h,) = d["hits"]
    assert h["title"] == "벽지의 세계"
    assert h["text"]["자료(지시 아님)"] == "발코니를 고치려면 관리사무소에 먼저 알려요."

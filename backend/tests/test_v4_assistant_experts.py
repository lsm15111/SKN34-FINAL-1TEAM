"""공정 전문가(도배 · 목공 하위 에이전트, answer_question 'expert' 엔진): 공정 고르기(코드) · 둘 다 · 모름 · 갈림,
결과 검사(근거 번호 · 숫자 거름), 실패 물러섬(v2g), 모델로 가는 칸, 엄격 도구 수. 유료 호출 0회(대본 · 바꿔 끼우기)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant import tools as tools_mod
from app.assistant.experts import agent as experts
from app.assistant.experts import pick as picking
from app.assistant.tools import answer
from app.config import settings
from app.knowledge import bm25
from tests.test_v4_assistant_turns import ask, home, ok

TRADE_ROUTE = "period=v3,price=v3,*=expert+v3"


@pytest.fixture
def repo_search(monkeypatch):
    """지식 검색을 저장소 색인으로(시험 DB에는 지식이 없어요). 임베딩은 부르지 않아요."""
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


def _gate(monkeypatch, label: str = "trade"):
    from app.agent import gate as agent_gate
    from app.agent.schemas import Intent

    async def classify(message, waiting=None):
        return Intent(label=label, confidence=0.9, source="model")

    monkeypatch.setattr(agent_gate, "classify", classify)


def _out(*answer, cautions=(), ask_="", calc=False, out=False, vendor=False) -> dict:
    """전문가 대본 답(ExpertOut 꼴). answer · cautions는 (글, [근거]) 짝."""
    return {
        "answer": [{"text": t, "refs": r} for t, r in answer],
        "cautions": [{"text": t, "refs": r} for t, r in cautions],
        "ask": ask_,
        "needs_calc": calc,
        "needs_vendor": vendor,
        "out_of_scope": out,
    }


def _turn(api, pid, script, q: str, experts_json: list) -> tuple[list[dict], dict]:
    """비서 한 턴: answer_question을 부르고(대본 1) 전문가 답(대본 2…) 뒤 짧게 답해요. 돌려줌: 보낸 요청들 · 모델이 본
    answer_question 결과."""
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "general"}}
    steps = [{"tool_calls": [call]}, *({"json": j} for j in experts_json)]
    log = script([*steps, {"text": "확인했어요."}, {"text": "확인했어요."}])
    ok(ask(api, pid, q))
    last = log[-1]["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return log, json.loads(last["content"])


def _hit(ref: str, scope: tuple[str, ...], topic: float = 0.8, weight: float = 10.0) -> bm25.Hit:
    return bm25.Hit(
        ref=ref, source_type="표준시방서", title="t", publisher="", date="", section="", text="글",
        score=1.0, scope=scope, topic=topic, weight=weight,
    )  # fmt: skip


# ---- 공정 고르기(LLM 없이) ----


def test_pick_by_words_project_other_and_unknown():
    assert picking.pick("초배지는 왜 발라요?") == picking.Pick(("도배",), "question")
    # 비서 안에서는 실크도 도배 낱말
    assert picking.pick("실크 이음새가 벌어졌어요").trades == ("도배",)
    assert picking.pick("석고보드 벽에 못 박아도 돼요?").trades == ("목공",)
    both = picking.pick("몰딩 바꾸고 도배도 새로 하려는데 순서가 어떻게 돼요?")
    assert both == picking.Pick(("도배", "목공"), "question")
    # 낱말이 없으면 이 공사 공정 하나, 둘이면 모름(지식 조각 갈래로 더 봐요)
    assert picking.pick("하자 생기면 어떻게 해요?", ("도배",)) == picking.Pick(("도배",), "project")
    assert picking.pick("하자 생기면 어떻게 해요?", ("도배", "목공")).why == "unknown"
    # 다른 공정 낱말만 있으면 이 공사 공정으로 넘기지 않아요(알아 두기가 맡아요)
    other = picking.pick("보일러 배관 손보고 장판도 새로 하려는데요?", ("도배",), other=True)
    assert other == picking.Pick((), "other")
    # 목공이 맡는 몫이 있는 일(우물천장 · 간접조명 박스 · 붙박이장)은 다른 공정 낱말이 같이 있어도 목공 전문가(QA r6 T23)
    ceiling = picking.pick("거실 우물천장에 간접조명을 넣고 싶은데 직접 달 수 있어요?", other=True)
    assert ceiling == picking.Pick(("목공",), "question")
    assert picking.pick("붙박이장 떼고 바로 도배해도 돼요?").trades == ("도배", "목공")


def test_infer_from_knowledge_scopes():
    d, m, c = ("도배",), ("목공",), (bm25.COMMON,)
    assert picking.infer([_hit("K1", d), _hit("K2", d), _hit("K3", c)]).trades == ("도배",)
    mokgong = picking.infer([_hit("K1", m), _hit("K2", m), _hit("K3", m), _hit("K4", d)])
    assert mokgong == picking.Pick(("목공",), "knowledge")
    mixed = picking.infer([_hit("K1", d), _hit("K2", d), _hit("K3", m), _hit("K4", m)])
    assert mixed.why == "split"
    # 공통이 공정 조각만큼 있으면 모름(공통 근거로 답해요), 주제가 안 맞는 조각은 세지 않아요
    assert picking.infer([_hit("K1", d), _hit("K2", c)]).why == "unknown"
    assert picking.infer([_hit("K1", d, topic=0.1), _hit("K2", d, topic=0.1)]).why == "unknown"
    assert picking.infer([_hit("K1", ("범위밖",)), _hit("K2", ("범위밖",))]).why == "unknown"


# ---- 결과 검사 ----


def _pieces() -> dict[str, experts.Piece]:
    text = "초배지는 질기고 풀칠하기 쉬운 한지나 부직포를 쓰고 벽 · 천장은 초배지 1회 · 도배지 1회 바른다."
    return {"K1": experts.Piece("K1", "표준시방서", "KCS 41 51 05 도배공사", "초배", text)}


def test_refine_keeps_grounded_lines_only():
    pieces = _pieces()
    out = experts.ExpertOut.model_validate(
        _out(
            ("초배지는 질긴 한지나 부직포를 써요.", ["[K1]"]),
            ("벽 · 천장은 초배지를 1회 발라요.", ["k1"]),  # 조각에 있는 숫자
            ("초배지는 한지나 부직포를 3겹 발라요.", ["K1"]),  # 조각에 없는 숫자 → 버림
            ("전혀 다른 자료 이야기예요.", ["K999"]),  # 받지 않은 조각 번호 → 근거 없음
            ("석고보드 나사 간격은 촘촘해야 해요.", ["K1"]),  # 조각과 낱말이 안 겹침 → 근거 뗌
            ("바탕이 젖어 있으면 들뜨기 쉬워요.", ["G"]),  # 전문 지식
            cautions=[("초배지는 질긴 한지나 부직포를 써요.", ["K1"])],  # 핵심 답과 같은 줄
            ask_="풀을 3일 말렸는지",  # 근거 없는 숫자가 든 물음은 비워요
        )
    )
    allowed = "\n".join(["초배는 왜 해요?", *(p.text for p in pieces.values())])
    note = experts.refine("도배", out, pieces, allowed)
    assert [x.text for x in note.answer] == [
        "초배지는 질긴 한지나 부직포를 써요.",
        "벽 · 천장은 초배지를 1회 발라요.",
        "바탕이 젖어 있으면 들뜨기 쉬워요.",
    ]
    assert [x.refs for x in note.answer] == [("K1",), ("K1",), ("G",)]
    assert note.cautions == [] and note.ask == "" and note.ok
    assert note.dropped == {"number": 1, "ref": 2, "cite": 1}
    assert note.sources() == ["KCS 41 51 05 도배공사"]
    rec = note.record()
    assert rec["guide_only"] == 1 and rec["cited"] == ["K1"] and rec["lines"] == 3


def test_refine_caps_lines_and_marks_out_of_scope():
    pieces = _pieces()
    many = [(f"초배지는 한지나 부직포를 써요 {'가나다라'[i]}.", ["G"]) for i in range(4)]
    out = experts.ExpertOut.model_validate(
        _out(*many, ("초배지는 질긴 부직포도 써요.", ["G"]), cautions=[("a", ["G"])] * 3)
    )
    note = experts.refine("도배", out, pieces, "")
    assert len(note.answer) == experts.ANSWER_MAX and len(note.cautions) == experts.CAUTION_MAX
    gone = experts.refine("도배", experts.ExpertOut.model_validate(_out(out=True)), pieces, "")
    assert gone.out and not gone.ok


# ---- 실패 물러섬 ----


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (llm.LLMOff("꺼짐"), "off"),
        (llm.OverBudget("user_day"), "budget"),
        (llm.LLMBadOutput("꼴"), "bad"),
        (llm.LLMError("실패"), "error"),
        (TimeoutError(), "time"),
    ],
)
def test_consult_one_failure_has_no_lines(monkeypatch, error, reason):
    async def fail(*_a, **_k):
        raise error

    monkeypatch.setattr(llm, "claude_json", fail)
    note = asyncio.run(experts.consult_one("도배", "초배지는 왜 발라요?", experts.Home(), []))
    assert note.failed == reason and not note.ok and note.answer == []


def test_expert_answer_falls_back_to_v2g(monkeypatch, repo_search):
    """무료 모드 · 전문가 실패면 v2g 근거(가짜 설명 없음), 갈림이면 되물을 조건 하나를 더해요."""

    async def fail(*_a, **_k):
        raise llm.LLMError("실패")

    monkeypatch.setattr(llm, "claude_json", fail)
    tc = SimpleNamespace(user=None, project_id=None, mode="llm")
    d = asyncio.run(answer._expert_answer(tc, "초배지는 왜 발라요?")).data
    assert d["route"] == "v2g" and d["hits"] and d["engine"] == "v2g"
    assert d["expert"]["why_v2g"] == "experts" and d["expert"]["notes"][0]["failed"] == "error"
    free = SimpleNamespace(user=None, project_id=None, mode="free")
    d = asyncio.run(answer._expert_answer(free, "초배지는 왜 발라요?")).data
    assert d["route"] == "v2g" and d["expert"]["why_v2g"] == "free"

    async def split(_q, _terms=()):
        return picking.Pick((), "split")

    monkeypatch.setattr(experts, "pick_unknown", split)
    d = asyncio.run(answer._expert_answer(tc, "어떤 게 좋아요?")).data
    assert d["route"] == "v2g" and d["expert"]["pick"] == "split"
    assert {"label": answer.SPLIT_LABEL, "lines": [picking.SPLIT_ASK]} in d["items"]


def test_expert_data_partial_failure_passes_found_pieces():
    """둘 다 고른 질문에서 한 전문가만 실패하면 성공한 줄 + 실패한 공정의 찾아 둔 조각(hits)을 넘겨요."""
    pieces = _pieces()
    good = experts.refine(
        "도배",
        experts.ExpertOut.model_validate(_out(("초배지는 질긴 한지나 부직포를 써요.", ["K1"]))),
        pieces,
        "",
    )
    bad = experts.Note(
        trade="목공", pieces={"K2": experts.Piece("K2", "표준시방서", "목공사", "", "각재")}
    )
    bad.failed = "time"
    d = answer.expert_data([good], [good, bad], order=True)
    assert d["trades"] == ["도배"] and d["sources"] == ["KCS 41 51 05 도배공사"]
    assert [h["title"] for h in d["hits"]] == ["목공사"]
    assert answer.ORDER_LABEL in [x["label"] for x in d["items"]]
    seen = policy.to_model({**d, "engine": "expert", "expert": {"pick": "question"}})
    assert "engine" not in seen and "expert" not in seen and seen["hits"]


def test_mokgong_vendor_needed_adds_connection_scope():
    """목공 시공이 필요한 답이면 믿집 연결 범위(도배만)와 다음 걸음 하나를 붙여요(QA r6 c2 L2). 도배는 붙이지 않아요."""
    pieces = _pieces()
    line = ("몰딩이 조금 들뜬 곳은 본드로 다시 붙여요.", ["G"])
    mok = experts.refine(
        "목공", experts.ExpertOut.model_validate(_out(line, vendor=True)), pieces, ""
    )
    d = answer.expert_data([mok], [mok], order=False, own=("도배",))
    scope = next(x for x in d["items"] if x["label"] == answer.CONNECT_LABEL)
    assert scope["lines"] == [policy.DOBAE_ONLY, answer.CONNECT_NEXT[False]]
    d = answer.expert_data([mok], [mok], order=False, own=("도배", "목공"))
    assert answer.CONNECT_NEXT[True] in json.dumps(d, ensure_ascii=False)
    dobae = experts.refine(
        "도배", experts.ExpertOut.model_validate(_out(line, vendor=True)), pieces, ""
    )
    plain = experts.refine("목공", experts.ExpertOut.model_validate(_out(line)), pieces, "")
    for n in (dobae, plain):
        labels = [x["label"] for x in answer.expert_data([n], [n], order=False)["items"]]
        assert answer.CONNECT_LABEL not in labels
    assert mok.record()["needs_vendor"] is True


def test_terms_widen_expert_search(monkeypatch, repo_search):
    """비서가 준 표준 용어(terms)를 검색어로 같이 써서 고객 말로는 안 잡히던 시방서 조각을 찾아요(QA r6 c2 T11:
    '도배 전에 조명 떼 놔야 해요?' → KCS 41 51 05 3.3(3)① 조명 기구 제거)."""
    sent: list[str] = []

    async def fake(_p, _schema, _system, msg, **_k):
        sent.append(msg)
        raise llm.LLMError("기록만")

    monkeypatch.setattr(llm, "claude_json", fake)
    tc = SimpleNamespace(user=None, project_id=None, mode="llm")
    q = "도배 전에 기존 조명을 떼 놔야 해요?"
    asyncio.run(answer._expert_answer(tc, q))
    asyncio.run(answer._expert_answer(tc, q, ("도배 전 조명 기구 제거",)))
    assert "K2578" not in sent[0] and "K2578" in sent[1]
    assert answer.terms_of(["  조명 기구   제거 ", "조명 기구 제거", "", "010-1234-5678 전화"]) == (
        "조명 기구 제거",
        policy.mask_in("010-1234-5678 전화"),
    )


# ---- 비서 턴(대본) ----


def test_expert_route_turn_one_trade(api, script, monkeypatch, repo_search):
    """도배 질문: 전문가 한 번(LLM 3번 = 비서 2 + 전문가 1). 모델은 검사한 줄 · 출처 · 확인할 조건만 받아요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    expert = _out(
        ("곰팡이 핀 벽은 원인부터 잡고 곰팡이를 없앤 뒤 도배해요.", ["G"]),
        ("곰팡이를 없애고 4321일 말려요.", ["G"]),  # 근거 없는 숫자 → 버림
        ("남의 자료 이야기예요.", ["K999999"]),  # 받지 않은 번호 → 버림
        cautions=[("빈 집이라 시공 뒤 창을 닫아 천천히 말리기 좋아요.", ["G"])],
        ask_="지금 벽에 결로 자국이 있는지",
    )
    q = "곰팡이 핀 벽에 그냥 도배해도 돼요? 010-1234-5678"
    log, body = _turn(api, pid, script, q, [expert])
    assert len(log) == 3
    req = log[1]  # 전문가 요청: 도배 지시문 · 이 집 사실 · 조각, 가린 질문
    system = json.dumps(req.get("system"), ensure_ascii=False)
    msg = json.dumps(req["messages"], ensure_ascii=False)
    assert "도배 전문가" in system and "자료 조각" in msg and "빈 집" in msg
    assert "010-1234-5678" not in msg and "<K" in msg
    assert body["route"] == "expert" and body["trades"] == ["도배"] and body["found"] is True
    assert "engine" not in body and "expert" not in body  # 기록 칸은 모델에 가지 않아요
    labels = [x["label"] for x in body["items"]]
    assert labels == ["도배 전문가 답", "도배 주의점(이 집)", answer.ASK_LABEL]
    said = [x["text"][policy.DATA_KEY] for x in body["items"][0]["lines"]]
    assert said == ["곰팡이 핀 벽은 원인부터 잡고 곰팡이를 없앤 뒤 도배해요."]
    assert "4321" not in json.dumps(body, ensure_ascii=False)


def test_expert_route_turn_both_trades(api, script, monkeypatch, repo_search):
    """도배 · 목공 둘 다: 전문가 두 번을 함께 부르고 공정 순서 줄을 붙여요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    one = _out(("목공을 먼저 끝낸 뒤 도배해요.", ["G"]))
    log, body = _turn(api, pid, script, "몰딩 바꾸고 도배도 새로 하려면 뭐부터 해요?", [one, one])
    assert len(log) == 4
    systems = {json.dumps(r.get("system"), ensure_ascii=False)[:200] for r in log[1:3]}
    assert any("도배 전문가" in s for s in systems) and any("목공 전문가" in s for s in systems)
    assert body["trades"] == ["도배", "목공"]
    labels = [x["label"] for x in body["items"]]
    assert labels[:2] == ["도배 전문가 답", "목공 전문가 답"] and answer.ORDER_LABEL in labels


def test_expert_route_money_and_failure(api, script, monkeypatch, repo_search):
    """금액 · 기간은 전문가 없이 v3, 전문가가 실패하면 v2g 근거(LLM 3번: 실패한 전문가 1번 포함)."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    log, body = _turn(api, pid, script, "도배 비용 얼마예요?", [])
    assert len(log) == 2 and body["route"] not in ("expert", "v2g")
    call = {"id": "q", "name": "answer_question", "input": {"question": "초배는 왜 해요?"}}
    log = script([{"tool_calls": [call]}, llm.LLMError("x"), {"text": "네."}, {"text": "네."}])
    ok(ask(api, pid, "초배는 왜 해요?"))
    body = json.loads(log[-1]["messages"][-1]["content"][0]["content"])
    assert len(log) == 3 and body["route"] == "v2g" and body["hits"]


# ---- 도구 표면 · 지시문 ----


def test_tool_surface_unchanged():
    """전문가는 answer_question의 엔진이라 도구를 더하지 않아요(엄격 도구 20개 상한 · 읽기 도구는 엄격 아님)."""
    t = tools_mod.get("answer_question", "customer")
    assert t.kind == "read"
    strict = [d for d in tools_mod.defs("customer") if d["strict"]]
    assert len(strict) <= tools_mod.STRICT_MAX
    assert not any("expert" in d["name"] for d in tools_mod.defs("customer"))
    assert answer.engine_for("general", TRADE_ROUTE) == "expert+v3"
    assert answer.engine_for("price", TRADE_ROUTE) == "v3"
    assert answer.engine_for("general", "expert") == "expert"


def test_expert_prompts_and_primer(tmp_path, monkeypatch):
    """지시문은 판 고정 파일이고 전문 지식 절에는 숫자가 없어요(근거 없는 숫자를 부르지 않게). 입문서가 있으면 붙여요."""
    for trade, spec in experts.SPECS.items():
        text = experts.system_of(spec)
        assert f"{trade} 전문가" in text and "## 전문 지식(G)" in text
        body = text.split("## 전문 지식(G)", 1)[1].split("## 좋은 예", 1)[0]
        assert not any(ch.isdigit() for ch in body), trade
    monkeypatch.setattr(experts, "PRIMER_DIR", tmp_path)
    experts.primer.cache_clear()
    (tmp_path / "dobae_primer.md").write_text("# 도배 입문\n초배는 밑종이예요.", encoding="utf-8")
    try:
        assert "초배는 밑종이예요." in experts.system_of(experts.SPECS["도배"])
        assert "입문서" not in experts.system_of(experts.SPECS["목공"])
    finally:
        experts.primer.cache_clear()


def test_asks_skip_known_conditions():
    home_ = experts.Home(("빈 집",), ("도배",), frozenset({"living", "grade"}))
    asks = experts.asks_for(experts.SPECS["도배"], home_)
    assert "사는 채로 하는지" not in asks and "벽지 종류(합지 · 실크)" not in asks
    assert "천장까지 하는지" in asks

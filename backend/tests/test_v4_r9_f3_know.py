"""QA r9 고침 F3(지식 · 공정 전문가 · 조사 답). 유료 호출 0회(Claude 대본 · 바꿔 끼우기).

- M3: 아는 집 정보(천장 도배 여부 · 범위)는 전문가 · v2 근거가 되묻지 않고, 예산 물음엔 이 공사 금액(표준견적서 ·
  업체 가견적, 계산 엔진 · 서버 값 그대로)을 같이 넘겨요(c2 T16).
- '며칠'이 든 지식 질문(마르는 · 창문 닫아 둘 기간)은 이 공사 공정표 길이 아니라 공정 전문가 길로 가요(c2 T18).
- 지식 답이 다음 걸음 없이 끝나면 지금 단계에 맞는 다음 걸음 한 줄을 붙여요(c2 T19).
- 조사 제목은 꾸밈말 가운데서 끊지 않고, 조사 끝 줄은 실제로 되는 일만 말해요(c2 조사).
- 알아 두기 카드 발췌에 법령 원문 한자를 보이지 않아요(c2 T9).
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.assistant import research
from app.assistant.experts import agent as experts
from app.assistant.tools import answer, cards
from app.config import settings
from tests.conftest import query
from tests.test_v4_assistant_experts import TRADE_ROUTE, _gate, _out, repo_search  # noqa: F401
from tests.test_v4_assistant_more import two_requested
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, home, ok


@pytest.fixture
def script():
    from app.agent import llm

    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def tool_body(log) -> dict:
    """마지막 LLM 요청이 받은 도구 결과(모델에 간 값)."""
    last = log[-1]["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return json.loads(last["content"])


def _answered(monkeypatch):
    """v3 길이 '답했다'고 돌려줘요(QA r9 c2 T18 194바이트 답처럼). 전문가로 잇는지 보려고 써요."""
    from app.assistant.tools import ToolOut

    async def v3(_tc, _q):
        return ToolOut(
            data={"route": "trade", "answer": "자료 글", "sources": [], "found": True}
        ), True

    monkeypatch.setattr(answer, "_v3_answer", v3)


# ---- M3: 아는 조건은 되묻지 않아요 ----


def test_known_ceiling_ask_is_dropped():
    """천장 도배 여부 · 범위를 집 정보로 알면 확인할 조건으로 되묻지 않아요(c2 T16 '천장까지 도배하는지 알려 주시겠어요?').
    천장 평탄화(목공) · 천장 곰팡이(벽 상태)는 다른 조건이라 그대로 둬요."""
    out = experts.ExpertOut.model_validate(_out(("친환경 실크도 가능해요.", ["G"])))
    known = frozenset({"living", "grade", "faces", "scope"})
    for said in (
        "천장까지 도배하는지",
        "천장까지 하는지",
        "천장도 도배하는지",
        "천장 도배도 하는지",
        "벽만 하는지 천장까지 하는지",
        "전체 도배인지 부분 도배인지",
    ):
        note = experts.refine("도배", out.model_copy(update={"ask": said}), {}, "", known)
        assert note.ask == "" and note.dropped["known"] == 1, said
    for said in (
        "천장 평탄화를 하는지",
        "천장에 곰팡이 · 얼룩이 있는지",
        "지금 벽에 결로 자국이 있는지",
    ):
        note = experts.refine("도배", out.model_copy(update={"ask": said}), {}, "", known)
        assert note.ask == said, said
    # 모르는 집이면 그대로 물어요
    note = experts.refine("도배", out.model_copy(update={"ask": "천장까지 도배하는지"}), {}, "")
    assert note.ask == "천장까지 도배하는지"
    asks = experts.asks_for(experts.SPECS["도배"], experts.Home(known=known))
    assert "천장까지 하는지" not in asks and "지금 벽 상태(들뜸 · 곰팡이 · 결로 · 요철)" in asks


def test_expert_gets_the_ceiling_from_the_home(api, script, monkeypatch, repo_search):  # noqa: F811
    """이 집 사실에 도배할 면(벽 · 천장)이 들어가고 아는 칸(faces · scope)으로 표시돼요(전체 공사 = 벽 + 천장)."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    seen: list = []

    async def consult(_trades, _question, home_, _terms=(), **_kw):
        seen.append(home_)
        line = experts.Line("친환경 실크도 바를 수 있어요.", ("G",))
        return [experts.Note(trade="도배", pieces={}, answer=[line])]

    monkeypatch.setattr(experts, "consult", consult)
    q = "친환경 실크벽지로 해도 괜찮을까요?"
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "material"}}
    script([{"tool_calls": [call]}, {"text": "네, 친환경 실크도 바를 수 있어요."}])
    ok(ask(api, pid, q))
    (h,) = seen
    assert {"faces", "scope"} <= h.known
    assert "도배할 면: 벽 · 천장" in h.lines


def test_v2g_does_not_ask_known_conditions(api, script, repo_search, monkeypatch):  # noqa: F811
    """전문가가 실패해 v2 근거로 물러서도 되물을 조건에서 아는 칸(벽지 종류 · 천장 · 사는 채로)은 빼요."""
    from app.agent import llm

    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    call = {"id": "q", "name": "answer_question", "input": {"question": "초배는 왜 해요?"}}
    log = script([{"tool_calls": [call]}, llm.LLMError("x"), {"text": "네."}, {"text": "네."}])
    ok(ask(api, pid, "초배는 왜 해요?"))
    body = tool_body(log)
    assert body["route"] == "v2g"
    asked = [
        line
        for x in body.get("items", [])
        if x["label"].startswith("되물을 조건")
        for line in x["lines"]
    ]
    assert "천장까지 하는지" not in asked and "벽지 종류(합지 · 실크)" not in asked
    assert "사는 채로 하는지" not in asked


# ---- M3: 예산 물음엔 이 공사 금액 ----


def test_budget_words():
    for said in (
        "근데 예산이 삼백만 원뿐인데 친환경 벽지로 해도 괜찮을까요?",
        "예산은 3백만 원 정도라서 친환경 벽지면 좋겠어요",
        "300만 원으로 될까요?",
        "300만원이면 돼요?",
    ):
        assert answer.budget_asked(said), said
    for said in (
        "도배 비용 얼마예요?",
        "업체 견적이 300만 원 나왔어요",
        "실크벽지 이음매가 벌어져요",
    ):
        assert not answer.budget_asked(said), said


def test_budget_question_gets_this_project_money(api, script, monkeypatch):
    """예산 물음(c2 T16): 모델 값에 표준견적서 합계와 실측 요청한 업체마다 요청 때 고정한 가견적 · 범위가 같이 가요
    (값은 계산 엔진 · 서버 값 그대로). 업체 금액이 없으면 업체 추천 가견적으로 말하라는 note예요."""
    pid, visits = two_requested(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _answered(monkeypatch)
    q = "근데 예산이 삼백만 원뿐인데 친환경 벽지로 해도 괜찮을까요?"
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "price"}}
    log = script([{"tool_calls": [call]}, {"text": "두 업체 가견적이 예산 안이에요."}])
    ok(ask(api, pid, q))
    money = tool_body(log)["money"]
    std = api.get(f"/projects/{pid}/standard").json()["total"]
    fixed = sorted(
        r["estimate_total"]
        for r in query(
            "select estimate_total from visits where id = any($1::uuid[])",
            [uuid.UUID(v) for v in visits],
        )
    )
    rows = {r["name"]: r["won"] for r in money["rows"]}
    assert rows.pop("표준견적서") == std
    assert sorted(rows.values()) == fixed
    assert all(name.endswith("가견적(요청 때 고정)") for name in rows)
    assert (money["estimate_low_won"], money["estimate_high_won"]) == (fixed[0], fixed[-1])
    assert answer.BUDGET_NOTE in tool_body(log)["note"]

    _, pid2 = home(api, "budget2@mitjip.test")
    log = script([{"tool_calls": [call]}, {"text": "표준견적서 안이에요."}])
    ok(ask(api, pid2, q))
    money = tool_body(log)["money"]
    assert [r["name"] for r in money["rows"]] == ["표준견적서"]
    assert money["note"] == answer.NO_VENDOR_MONEY


# ---- '며칠'이 든 지식 질문은 공정 전문가 길 ----

CARE_QS = (
    "도배 마르는 데 며칠 걸려요?",
    "도배하고 나서 며칠은 창문 열면 안 된다던데 그거 맞아요?",
    "풀 냄새는 며칠이나 가요?",
    "도배하고 며칠 뒤에 입주해도 돼요?",
)


def test_care_period_questions_are_knowledge():
    for q in CARE_QS:
        assert answer.kind_of("period", q) == "general" and not answer.money_first(q), q
    for q in ("도배 며칠 걸려요?", "공사 기간 얼마나 걸려요?", "도배 비용 얼마예요?"):
        assert answer.money_first(q), q
    assert answer.kind_of("period", "도배 며칠 걸려요?") == "period"


@pytest.mark.usefixtures("repo_search")
def test_care_period_question_goes_to_the_expert(api, script, monkeypatch):
    """'도배 마르는 데 며칠 걸려요?'를 모델이 period로 불러도 v3(이 공사 공정표 길)가 답했다고 끝내지 않고 전문가가
    근거와 함께 답해요(LLM 3번). 계산 엔진 기간만 말하라는 CALC_NOTE 대신 지식 기간 note예요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    _answered(monkeypatch)
    q = CARE_QS[0]
    expert = _out(("도배는 맞바람 없이 천천히 말려야 이음매가 덜 벌어져요.", ["G"]), calc=True)
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "period"}}
    log = script([{"tool_calls": [call]}, {"json": expert}, {"text": "천천히 말려요."}])
    ok(ask(api, pid, q))
    body = tool_body(log)
    assert len(log) == 3 and body["route"] == "expert"
    assert answer.CALC_NOTE not in body.get("note", "") and answer.CARE_NOTE in body["note"]


# ---- 지식 답 뒤 다음 걸음 한 줄 ----


@pytest.mark.usefixtures("repo_search")
def test_knowledge_answer_gets_a_next_step(api, script, monkeypatch):
    """지금 할 일 줄을 이 단계에서 이미 말한 뒤 지식 답이 다음 걸음 없이 끝나면(c2 T19) 지금 단계에 맞는 다음 걸음 한
    줄을 붙여요. 답에 업체 · 실측에 물어보라는 말이 있으면 붙이지 않아요."""
    pid, _ = two_requested(api)
    monkeypatch.setattr(settings, "assistant_answer_route", TRADE_ROUTE)
    _gate(monkeypatch)
    script([{"text": "업체마다 답하는 때가 달라요."}])
    first = tokens(ok(ask(api, pid, "업체 답은 언제 와요?")))
    assert "실측 기간 답을 기다리는 중이에요" in first  # 이 단계 지금 할 일 줄(처음 한 번)

    q = "실크벽지는 이음매가 잘 벌어진다던데 왜 그래요? 막는 방법 있어요?"
    expert = _out(("실크는 마르면서 줄어 이음매가 벌어질 수 있어요.", ["G"]))
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "general"}}
    said = "실크는 마르면서 줄어 이음매가 벌어질 수 있어요. 시공 뒤에는 맞바람을 피해 자연 건조해 주세요."
    script([{"tool_calls": [call]}, {"json": expert}, {"text": said}])
    got = tokens(ok(ask(api, pid, q)))
    assert got == f"{said}\n\n{answer.KNOW_NEXT['visit']}"

    led = "풀이 덜 스며도 이음매가 벌어지기 쉬워요. 실측 때 업체에 이음매 처리를 물어보세요."
    script([{"tool_calls": [call]}, {"json": expert}, {"text": led}])
    assert tokens(ok(ask(api, pid, q))) == led


def test_know_next_follows_the_stage():
    def o(phase="estimate", *statuses, trade="dobae"):
        return SimpleNamespace(
            phase=phase,
            trades=[SimpleNamespace(trade=trade)],
            vendors=[SimpleNamespace(status=s) for s in statuses],
        )

    assert answer.know_stage(o()) == "before"
    assert answer.know_stage(o("progress", "requested", "cancelled")) == "visit"
    assert answer.know_stage(o("progress", "requested", "booked")) == "chat"
    assert answer.know_stage(o("progress", "chosen")) == "chosen"
    assert answer.know_stage(o("work")) == "chosen"
    assert answer.know_stage(o("done", "chosen")) is None
    assert answer.know_stage(o(trade="mokgong")) is None  # 업체를 잇지 않는 공사
    assert answer.flow_step("실측 때 두 업체에 건조 기간을 물어보세요.")
    assert answer.flow_step("업체에 그 제품으로 견적을 물어볼 수 있어요.")
    assert not answer.flow_step("시공 뒤에는 맞바람을 피해 자연 건조해 주세요.")


# ---- 조사 제목 · 끝 줄 ----


@pytest.mark.parametrize(
    ("goal", "title"),
    [
        (  # c2: '…인증을 받은'에서 끊겨 '…받은 조사를 마쳤어요'
            "노원구 25평 살면서 도배, 환경표지 인증을 받은 실크벽지 제품 몇 가지와 판매처 가격",
            "노원구 25평 살면서 도배, 환경표지 인증을 받은 실크벽지",
        ),
        (  # 꾸밈을 받는 말이 40자 안에 없으면 꾸밈말을 떼요(조사만 붙은 낱말은 조사만)
            "서초구 30평 아파트 실크 도배를 꼼꼼하고 깔끔하게 마감해 주는 믿을 만한 동네 업체 위주로",
            "서초구 30평 아파트 실크 도배",
        ),
        (
            "강남구 34평 빈 집 실크 도배, 곰팡이가 잘 생기는 북쪽 방 벽에 쓰는 방균 초배지 종류",
            "강남구 34평 빈 집 실크 도배, 곰팡이가 잘 생기는 북쪽",
        ),
    ],
)
def test_title_does_not_end_inside_a_modifier(goal, title):
    got = research.title_of(goal)
    assert got == title and len(got) <= research.TITLE_HARD
    assert research.ENDED_LINE["done"].format(title=got).startswith(title + " 조사를")


def test_pick_line_says_only_what_happens():
    """조사 끝 줄은 '이어서 알아볼게요'처럼 실제 다음 턴에 없는 일을 약속하지 않아요(c2 T21: 고르면 업체에 그 제품으로
    견적을 물어보라고 이어 가요)."""
    assert "이어서 알아볼게요" not in research.ASK_PICK
    assert "업체" in research.ASK_PICK and "견적" in research.ASK_PICK


# ---- 알아 두기 카드 한자 ----

LAW = (
    "「환경기술 및 환경산업 지원법」 제22조(환경표지 등의 사용) ① 인증을 받은 자는 재료 및 제품의 포장ㆍ용기(容器) "
    "등에 환경표지를 표시할 수 있다."
)


def test_knowledge_card_has_no_hanja():
    hit = SimpleNamespace(
        text=LAW,
        title="환경기술 및 환경산업 지원법",
        section="제22조",
        publisher="법제처",
        official=True,
        source_type="법령",
    )
    (line,) = cards.knowledge_card("know-x", None, [hit]).data["lines"]
    assert cards._HANJA_WORD.search(LAW)  # 거름 꼴이 원문 한자를 잡아요
    assert not cards._HANJA_WORD.search(line) and "ㆍ" not in line
    assert "포장 · 용기 등에" in line
    assert cards.clean_source_text("본 (本) 조항") == "본 조항"


@pytest.mark.usefixtures("repo_search")
def test_v2g_fallback_without_a_project():
    """공사 없는 전문가 길(무료 모드)도 v2g로 물러서요(아는 칸 거름이 공사 없이도 깨지지 않게)."""
    tc = SimpleNamespace(user=None, project_id=None, mode="free", text="초배지는 왜 발라요?")
    d = asyncio.run(answer._expert_answer(tc, "초배지는 왜 발라요?")).data
    assert d["route"] == "v2g"

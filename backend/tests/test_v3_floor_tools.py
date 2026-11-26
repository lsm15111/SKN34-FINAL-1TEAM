"""바닥 에이전트 도구(specialists/floor/tools.py): 칸 검사 · 결과 모양 · 가림. DB · LLM 호출 없이 검증한다."""

import json
import uuid
from datetime import date

from v3_kb import repo_kb

from app.agent.v3.answer import Task
from app.agent.v3.schemas import (
    PlanBlockFact,
    PlanFacts,
    ProjectFacts,
    StandardFacts,
    StandardLineFact,
    TurnContext,
)
from app.agent.v3.specialists.floor import tools

TODAY = date(2026, 11, 26)


def _task(text="강마루랑 강화마루 차이가 뭐예요?", facts=None, **kw) -> Task:
    ctx = TurnContext(user_id=uuid.uuid4(), project_id=uuid.uuid4(), today=TODAY)
    return Task(text=text, route="trade", trades=["floor"], policy=[], ctx=ctx, facts=facts, **kw)


def _call(name, args, task=None, st=None):
    st = st or tools.State()
    out = tools.call(name, args, task or _task(), repo_kb(), st)
    return out, json.loads(out.content), st


def test_defs_match_runners_and_close_extra_fields():
    names = [d["name"] for d in tools.defs()]
    assert names == list(tools.RUN)
    for d in tools.defs():
        assert d["parameters"]["additionalProperties"] is False
        assert "project_id" not in json.dumps(d) and "user_id" not in json.dumps(d)
    ask = next(d for d in tools.defs() if d["name"] == "ask_customer")
    assert ask["parameters"]["properties"]["slot"]["enum"][0] == "floor.kind"
    hand = next(d for d in tools.defs() if d["name"] == "handoff")
    assert "floor" not in hand["parameters"]["properties"]["trade"]["enum"]
    assert "tile" in hand["parameters"]["properties"]["trade"]["enum"]


def test_unknown_tool_and_extra_fields_are_refused():
    out, body, _ = _call("save_quote", {})
    assert not out.ok and body["error"]
    # 공사 번호 · 사용자를 칸으로 넣어 남의 공사를 읽으려 해도 실행하지 않는다
    out, body, _ = _call("project_facts", {"project_id": str(uuid.uuid4())})
    assert not out.ok and body["error"] == "정해 둔 칸만 넣어요"
    out, _, _ = _call("search_knowledge", "강마루")
    assert not out.ok


def test_search_knowledge_returns_data_with_refs_and_masks():
    out, body, st = _call("search_knowledge", {"query": "강마루 강화마루 차이 010-1234-5678"})
    assert out.ok and body["note"] == tools.DATA_NOTE
    assert 0 < len(body["data"]) <= 8
    assert set(st.hits) == {d["ref"] for d in body["data"]}
    assert all(len(d["text"]) <= tools.HIT_TEXT for d in body["data"])
    assert "010-1234-5678" not in out.content
    out, body, _ = _call("search_knowledge", {"query": "  "})
    assert not out.ok


def test_project_facts_without_and_with_project():
    _, body, _ = _call("project_facts", {})
    assert body["project"] is None
    facts = ProjectFacts(area_m2=84.9, area_basis="exclusive", living="living", trades=["dobae", "floor"],
                         brief={"floor.kind": "마루", "dobae.grade": "실크"})  # fmt: skip
    _, body, _ = _call(
        "project_facts", {}, _task(facts=facts, slot="floor.remove", value="걷어내요")
    )
    p = body["project"]
    assert p["area_m2"] == 84.9 and p["area_basis"] == "전용" and p["living"] == "살면서 공사"
    assert p["trades"] == ["도배", "바닥"]
    assert p["floor"] == {"floor.kind": "마루", "floor.remove": "걷어내요"}  # 바닥 칸만


def test_floor_estimate_has_no_calc_yet_but_order_from_engine():
    _, body, st = _call("floor_estimate", {})
    assert body["lines"] == tools.NO_CALC and body["plan"] == tools.NO_CALC
    assert body["order"] == "도배 → 바닥" and body["order_note"]  # 종류를 모르면 그대로 + 안내
    assert st.calc_refs == []
    _, body, _ = _call("floor_estimate", {}, _task(slot="floor.kind", value="마루"))
    assert body["order"] == "바닥 → 도배" and "order_note" not in body
    _, body, _ = _call(
        "floor_estimate", {}, _task(facts=ProjectFacts(brief={"floor.kind": "장판"}))
    )
    assert body["order"] == "도배 → 바닥"


def test_floor_estimate_copies_engine_lines_and_blocks_only():
    facts = ProjectFacts(
        standard=StandardFacts(
            total=1_000_000, supply=909_091, vat=90_909,
            lines=[
                StandardLineFact(key="dobae_silk", name="실크벽지", state="included", trade="dobae"),
                StandardLineFact(key="floor_kang", name="강마루", state="included", qty=25.0,
                                 unit="평", unit_price=120_000, amount=3_000_000, trade="floor"),
            ],
        ),
        plan=PlanFacts(start=TODAY, end=TODAY, work_days=1, blocks=[
            PlanBlockFact(trade="floor", ko="바닥", start=TODAY, end=TODAY),
            PlanBlockFact(trade="dobae", ko="도배", start=TODAY, end=TODAY),
        ]),
    )  # fmt: skip
    _, body, st = _call("floor_estimate", {}, _task(facts=facts))
    assert [ln["ref"] for ln in body["lines"]] == ["standard.lines.floor_kang"]
    assert body["lines"][0]["amount"] == 3_000_000
    assert body["plan"] == [{"start": "2026-11-26", "end": "2026-11-26"}]
    assert st.calc_refs == ["standard.lines.floor_kang"]


def test_ask_customer_only_known_empty_slot_once():
    out, _, _ = _call("ask_customer", {"slot": "dobae.grade"})
    assert not out.ok
    out, body, st = _call("ask_customer", {"slot": "floor.kind"})
    assert out.ok and out.end_turn and body == {"asked": "floor.kind"}
    assert st.ask.slot == "floor.kind" and st.ask.options[-1] == "아직 몰라요"
    out, _, _ = _call("ask_customer", {"slot": "floor.remove"}, st=st)
    assert not out.ok  # 한 턴에 한 칸
    out, _, _ = _call(
        "ask_customer", {"slot": "floor.kind"}, _task(slot="floor.kind", value="마루")
    )
    assert not out.ok  # 방금 답한 칸
    task = _task(facts=ProjectFacts(brief={"floor.kind": "장판"}))
    out, _, _ = _call("ask_customer", {"slot": "floor.kind"}, task)
    assert not out.ok  # 모은 조건에 있는 칸


def test_handoff_registered_trade_once():
    out, _, _ = _call("handoff", {"trade": "floor"})
    assert not out.ok
    out, _, _ = _call("handoff", {"trade": "plumbing_x"})
    assert not out.ok
    out, body, st = _call(
        "handoff", {"trade": "tile"}, _task("현관 바닥 타일이랑 거실 마루 같이 해요")
    )
    assert out.ok and body["trade"] == "타일" and body["note"] == tools.DATA_NOTE
    assert st.handed == "tile" and st.handoff is not None and st.handoff.trade == "tile"
    out, _, _ = _call("handoff", {"trade": "mokgong"}, st=st)
    assert not out.ok  # 한 턴에 한 번
    task = _task()
    task.trades = ["floor", "tile"]
    out, _, _ = _call("handoff", {"trade": "tile"}, task)
    assert not out.ok  # 관문이 이미 같이 답하게 한 공종


def test_scope_catches_work_words_not_floor_explanations():
    assert tools.scope("난방 배관을 옮기려면 어떻게 해요?") == tools.SCOPE[0][1]
    assert tools.scope("보일러 교체도 바닥 업체가 해요?") == tools.SCOPE[0][1]
    assert tools.scope("오래된 아파트 석면 바닥재") == tools.SCOPE[1][1]
    assert tools.scope("거실은 에폭시 바닥으로 할래요") == tools.SCOPE[2][1]
    # 바닥 설명에 나오는 말은 그대로
    assert tools.scope("강마루는 바닥 난방 열이 잘 전해져요.") is None
    assert tools.scope("시공 뒤 보일러를 약하게 켜서 말려요.") is None
    assert tools.scope("수용성 에폭시 접착제를 써요.") is None
    assert tools.scope("온돌마루는 합판 위에 무늬목을 붙여요.") is None
    assert not any(ch.isdigit() for _, fixed in tools.SCOPE for ch in fixed)

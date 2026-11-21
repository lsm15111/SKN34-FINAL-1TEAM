"""v4 업체 브리핑 글 점검(06-answer-audit 5절 #3 · #12): 공정 · 지역이 맞지 않으면 기간 답하기 카드 없이
까닭만 · 벽지 미정은 확인 필요 · 칸 수는 카드에 보이는 하나.
유료 호출 0회(Claude 대본 · 무료 모드)."""

import json
import re
import uuid

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import vendor as vendor_tools
from tests.conftest import query
from tests.test_v3_visit_kit import requested
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_turns import ok
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


def brief(api, visit: str) -> dict:
    r = api.get(f"/vendor/assistant/briefs/{visit}")
    assert r.status_code == 200, r.text
    return r.json()


def fit_of(b: dict, key: str) -> dict:
    return next(x for x in b["fit"] if x["key"] == key)


def test_misfit_request_shows_reason_without_window_card(api):
    """#3(RT36): 지역이 맞지 않는 요청에도 기간 답하기 승인 카드를 저절로 만들던 일."""
    f = requested(api)
    login(api, f["email"])
    query(  # 고객 집(노원구)을 출장 지역에서 뺀다
        "delete from vendor_areas where vendor_id = $1 and sido = 'seoul' and sgg = '노원구'",
        uuid.UUID(f["vendor"]),
    )
    b = brief(api, f["visit"])
    area = fit_of(b, "area")
    assert (area["ok"], area["state"]) == (False, "no")
    assert b["suggest"] is None and b["windows"] == []  # 기간 후보 · 제안 없음
    assert b["sentence"] == "지역이 우리 업체와 맞지 않아요. 받기 어려우면 못 받아요로 답해 주세요."
    assert query("select count(*) as n from assistant_actions")[0]["n"] == 0
    # 무료 모드 '기간 답할게요'도 카드 없이 까닭만(못 받아요는 업체가 고른다)
    r = api.post(
        "/vendor/assistant/turns",
        json={"visit_id": f["visit"], "client_key": uuid.uuid4().hex, "text": "기간 답할게요"},
    )
    ev = ok(r)
    (said,) = [d["data"]["text"] for e, d, _ in ev if e == "card" and d["kind"] == "answer"]
    assert said.startswith("지역이 우리 업체와 맞지 않아 기간 답하기 카드는 만들지 않았어요")
    assert acts(ev) == []
    # 맞는 요청은 그대로 제안을 만든다
    query(
        "insert into vendor_areas (vendor_id, sido, sgg) values ($1, 'seoul', '노원구')",
        uuid.UUID(f["vendor"]),
    )
    assert brief(api, f["visit"])["suggest"]


def test_paper_undecided_is_check_and_one_count(api, script):
    """#12: 벽지를 아직 안 정했는데 '벽지가 맞지 않아요', 한 문장 사실에 칸 수가 둘(27 · 14)이던 일."""
    f = requested(api)
    login(api, f["email"])
    query("update visits set grade = null")
    query("update standard_quotes set grade = null")
    b = brief(api, f["visit"])
    paper = fit_of(b, "paper")
    assert (paper["ok"], paper["state"], paper["text"]) == (False, "check", "벽지 미정")
    g = b["suggest"]
    assert g is not None  # 벽지 미정은 기간 답하기를 막지 않는다
    assert "맞지 않아요" not in b["sentence"]
    assert b["sentence"].endswith(f"빈 반나절 {g['open_count']}칸이 있어 답하기 좋아요.")
    sched = fit_of(b, "schedule")
    assert sched["state"] == "ok" and "칸" not in sched["text"]  # 칸 수는 제안 기간 하나만
    # AI 한 문장 사실: 카드에 보이는 칸 수(제안 기간)만, 맞음은 세 갈래
    log = script([{"json": {"text": "답하기 좋은 기간이 있어요."}}])
    assert brief(api, f["visit"])["sentence"] == "답하기 좋은 기간이 있어요."
    facts = json.loads(log[0]["messages"][0]["content"])
    assert set(facts) == {"title", "fit", "suggest", "due"}
    assert facts["suggest"]["open_count"] == g["open_count"]
    assert {x["label"]: x["state"] for x in facts["fit"]}["벽지"] == "check"
    counts = set(re.findall(r"(\d+)칸", json.dumps(facts, ensure_ascii=False)))
    assert counts <= {str(g["open_count"])}


def test_template_check_sentence_when_no_suggestion():
    from app.assistant.schemas import BriefHalves, FitRow, VendorBriefData

    data = VendorBriefData(
        visit_id=uuid.uuid4(),
        title="노원구 · 도배",
        facts=[],
        fit=[
            FitRow(key="trade", label="공정", ok=True, text="도배 요청", state="ok"),
            FitRow(key="paper", label="벽지", ok=False, text="벽지 미정", state="check"),
        ],
        estimate=None,
        halves=BriefHalves(days=[], taken={}, open_count=0),
        suggest=None,
        due_at=None,
        memo=None,
    )
    assert vendor_tools.brief_template(data) == "벽지 확인이 필요해요. 고객이 아직 정하지 않았어요."

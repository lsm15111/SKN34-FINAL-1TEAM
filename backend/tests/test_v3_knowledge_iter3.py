"""지식 보강 3회차(iter3): 조각 번호 · 칸 규칙과, 빈 주제 핵심 질문이 새 카드로 답하는지."""

import json
import re

import pytest
from v3_kb import V3_ITER3, datasets, repo_kb

from app.agent.v3.answer import Part, knowledge
from app.knowledge.v3_csv import START2, START3

ROWS = [json.loads(x) for x in V3_ITER3.read_text(encoding="utf-8").splitlines() if x.strip()]
KINDS = {"law", "gov_notice", "gov_guide", "gov_qa", "kcs", "standard_contract", "consumer_agency",
         "official", "public_data", "gov", "maker", "maker_guide", "industry"}  # fmt: skip
MONEY = re.compile(r"\d[\d,.]*\s*(?:만\s*원|천\s*원|억\s*원|억|원)")
PERIOD = re.compile(r"\d[\d,.~]*\s*(?:일|주일|주|개월|달|년)(?![가-힣])")


def test_iter3_refs_follow_iter2_without_overlap():
    sets = dict(datasets())
    it2, it3 = sets["v3_knowledge_iter2_rag"], sets["v3_knowledge_iter3_rag"]
    nums = [int(r["ref"][1:]) for r in it3]
    assert START3 > max(int(r["ref"][1:]) for r in it2) >= START2
    assert nums == list(range(START3, START3 + len(ROWS)))
    assert len(ROWS) >= 26


def test_iter3_rows_keep_source_fields_and_no_money_or_period_numbers():
    for r in ROWS:
        assert r["id"].startswith(f"kv3i3-{r['gap']}-"), r["id"]
        assert r["source_url"].startswith(("http://", "https://")), r["id"]
        assert r["kind"] in KINDS and r["publisher"] and r["doc_key"], r["id"]
        assert 3 <= len(r["answers"]) <= 5, r["id"]
        for text in (r["summary"], r["summary_haeyo"], *r["answers"]):
            assert not MONEY.search(text) and not PERIOD.search(text), (r["id"], text)


@pytest.mark.parametrize(
    ("q", "trade", "route", "card"),
    [
        (
            "화장실 문 교체하려면 어떻게 해요?",
            "mokgong",
            "trade",
            "mokgong.method.bath-door-replace",
        ),
        ("천장도 꼭 도배해야 해요?", "dobae", "trade", "dobae.method.ceiling-need"),
        ("살면서 도배할 수 있어요?", "dobae", "trade", "dobae.prep.living-in-howto"),
        ("도배하고 바로 입주해도 돼요?", "dobae", "trade", "dobae.prep.move-in-after"),
        ("도배 전에 집에서 뭘 준비해야 해요?", "dobae", "trade", "dobae.prep.home-ready"),
        ("걸레받이 없애도 돼요?", "mokgong", "trade", "mokgong.method.no-baseboard"),
        ("몰딩 종류는 뭐가 있어요?", "mokgong", "trade", "mokgong.material.molding-types"),
        ("공사 날짜를 미뤄야 하면 어떻게 해요?", "common", "guide", "common.contract.reschedule"),
        ("좋은 도배 업체 고르는 법 알려 주세요", "common", "guide", "common.vendor.how-to-choose"),
    ],
)
def test_core_gap_questions_are_answered_by_cards(q, trade, route, card):
    part = Part(route=route, trade=trade)
    how = knowledge(part, repo_kb(), q, trade=trade, route=route)
    assert how == "card", (q, part.unknown)
    assert part.used_cards[0].startswith(f"card:{card}@"), part.used_cards

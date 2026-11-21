"""v4 비서 도배 지식 카드(갈래 KB): 벽지 롤 크기 · 상황별 라인 · 이름 바뀐 라인. 적재 DB · LLM 없음(무료 모드).

- 새 지식 줄 K1435~K1444(상담 지식 CSV 끝)는 저장소 색인에 있고, 제품 페이지 · FAQ · 기사마다 문서가 따로예요.
- 상담 지식 CSV 전체가 수동 적재(data_ingest) 검사를 통과하는 모양이에요(원본 해시 · 쪽 · 날짜).
- 새 카드는 열쇠와 비슷한 새 질문에 답 카드로 잡히고, 비슷한 기존 도배 카드 질문은 그대로 기존 카드가 받아요.
- 확인 안 된 라인 이름은 새 줄 · 카드에 없고, 카드는 우리 집 롤 수를 셈하지 않아요(계산은 표준견적서 벽지 줄).
"""

import re
from pathlib import Path

import pytest
from v3_kb import repo_index, repo_kb

from app import data_ingest as ingest
from app.agent.v3.answer import Part, knowledge

ROOT = Path(__file__).resolve().parents[2]
REFS = [f"K{n}" for n in range(1435, 1445)]
ROLL, LINES, RENAMED = (
    "dobae.material.roll-size",
    "dobae.material.lines-by-situation",
    "dobae.material.renamed-lines",
)
# 조사에서 공식 누리집으로 확인하지 못한 라인(08-벽지 자재 카탈로그 7장)
UNVERIFIED = re.compile(r"에비뉴|디아이디|DID|지아패브릭|더실링|타일벽지")
KB = repo_kb()


def answer_card(q: str) -> tuple[str, str | None]:
    part = Part(route="trade", trade="dobae")
    how = knowledge(part, KB, q, trade="dobae", route="trade")
    used = part.used_cards[0].split("@")[0].removeprefix("card:") if part.used_cards else None
    return how, used


def test_new_rows_are_indexed_with_their_own_sources():
    ix = repo_index()
    items = [ix.by_ref[r] for r in REFS]
    # 쪽마다 문서 키가 따로예요(같은 키면 첫 줄 제목 · 주소가 다른 줄 출처로 보여요)
    assert len({x.chunk.doc for x in items}) == len(REFS)
    for x in items:
        assert x.doc.kind in ("maker", "news") and x.doc.url.startswith("https://"), x.chunk.ref
        assert "도배" in x.chunk.trades and x.chunk.hints, x.chunk.ref
        assert not UNVERIFIED.search(f"{x.chunk.text} {x.doc.title}"), x.chunk.ref


def test_consult_csv_passes_ingest_checks():
    ds = ingest.inspect_csv(ROOT / "data/consult/consult_knowledge_rag.csv")
    ix = repo_index()
    ids = {ix.by_ref[r].chunk.rid.split("/", 1)[1] for r in REFS}
    assert ds.kind == "knowledge" and ids <= set(ds.hashes)


def test_new_cards_cite_new_rows_and_do_not_count_rolls():
    for cid in (ROLL, LINES, RENAMED):
        c = KB.cards.by_id[cid]
        assert 6 <= len(c.keys) <= 10 and c.review_by.isoformat() == "2027-02-22", cid
        assert set(c.cites()) & set(REFS), cid
        assert {s.ref for s in c.sources} == set(c.cites()), cid
        texts = [x.text for x in (*c.answer, c.caution, c.tip) if x]
        assert not any(UNVERIFIED.search(t) for t in texts), cid
        assert {x.ref for x in c.calc} <= {"standard.lines.paper"}, cid


@pytest.mark.parametrize(
    ("q", "card"),
    [
        ("실크 1롤은 몇 평 발라요?", ROLL),
        ("천장지는 롤이 길어요?", ROLL),
        ("벽지 롤 크기가 회사마다 달라요?", ROLL),
        ("32평 아파트 벽지 몇 롤 사야 해요?", ROLL),
        ("고급형 실크 벽지는 어떤 라인이 있어요?", LINES),
        ("긁힘에 강한 벽지 라인 알려 주세요", LINES),
        ("강아지가 벽을 긁는데 버티는 벽지 라인 있어요?", LINES),
        ("베스띠 아직 나와요?", RENAMED),
        ("베스띠 벽지 아직 살 수 있어요?", RENAMED),
        ("휘앙세 93 단종인가요?", RENAMED),
    ],
)
def test_new_cards_answer_similar_new_questions(q, card):
    assert answer_card(q) == ("card", card)


@pytest.mark.parametrize(
    ("q", "card"),
    [
        ("벽 길이로 벽지 몇 폭 필요한지 어떻게 세요?", "dobae.material.width-and-rolls"),
        ("광폭이랑 소폭 합지는 폭이 얼마나 달라요?", "dobae.material.width-and-rolls"),
        ("벽지 여분은 몇 롤 더 사 둬요?", "dobae.material.width-and-rolls"),
        ("PS 인증 받은 벽지는 뭐가 달라요?", "dobae.material.pet-home"),
        ("실크 벽지가 합지보다 좋은 점이 있어요?", "dobae.material.silk-vs-hapji"),
        ("벽지 더 살 때 로트번호 꼭 맞춰야 해요?", "dobae.material.extra-order-lot"),
    ],
)
def test_existing_dobae_cards_keep_similar_questions(q, card):
    assert answer_card(q) == ("card", card)


@pytest.mark.parametrize("q", ["테라피 벽지 아직 나와요?", "개나리 에비뉴는 단종됐어요?"])
def test_other_line_names_are_not_answered_as_renamed(q):
    # 이름 바뀐 라인 카드는 베스띠 · 휘앙세만 말해요. 다른 라인 이름 질문을 받지 않아요
    assert answer_card(q)[1] != RENAMED


@pytest.mark.parametrize("q", ["32평이에요", "35평이에요", "34평 아파트예요"])
def test_house_size_alone_is_not_answered_by_roll_size(q):
    # 날짜 질문 뒤에 붙은 '32평이에요'는 따로 가이드 길로 찾아요. 집 크기 말만으로 롤 크기 카드가 붙지 않아요
    part = Part(route="guide", trade="common")
    knowledge(part, KB, q, trade="common", route="guide")
    assert not any(c.startswith(f"card:{ROLL}@") for c in part.used_cards), part.used_cards

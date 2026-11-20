"""v3 답 카드 파일: 모양 · 수 · 숫자 규칙 · 인용 · 찾기 (cards_check.py의 코드 검사 중 말뭉치 없이 되는 것)."""

import re
from collections import Counter

from v3_kb import repo_index

from app.knowledge import cards
from app.knowledge.cards import DOC_REFS
from app.knowledge.v3_csv import START

CS = cards.default()
MONEY_OR_PERIOD = re.compile(r"\d[\d,.]*\s*(?:만\s*원|천\s*원|억\s*원|억|원|일|주일|주|개월)")
CODES = (
    "dobae", "mokgong", "floor", "tile", "bath", "kitchen", "paint", "film", "electric",
    "window", "demolition", "plumbing", "common",
)  # fmt: skip


def _sentences(c):
    return [*c.answer, *(x for x in (c.caution, c.tip) if x)]


def test_at_least_300_cards_and_every_trade_is_covered():
    by = Counter(c.trade for c in CS.cards)
    assert CS.n >= 300
    assert set(by) == set(CODES)
    assert min(by.values()) >= 14, by
    assert by["dobae"] >= 45 and by["mokgong"] >= 38 and by["common"] >= 45


def test_ids_and_keys_are_unique():
    ids = [c.id for c in CS.cards]
    assert len(ids) == len(set(ids))
    keys = Counter(k.strip() for c in CS.cards for k in c.keys)
    assert not [k for k, n in keys.items() if n > 1]


def test_cards_hold_no_money_or_period_numbers_and_speak_haeyo():
    for c in CS.cards:
        for s in _sentences(c):
            assert not MONEY_OR_PERIOD.search(s.text), (c.id, s.text)
            assert s.text.rstrip(" .)").endswith(("요", "요?")), (c.id, s.text)


def test_every_cite_is_a_known_chunk_or_service_rule():
    ix = repo_index()
    for c in CS.cards:
        for r in c.cites():
            assert r in ix.by_ref or r in DOC_REFS, (c.id, r)
            if r.startswith("K") and int(r[1:]) >= 7001 and int(r[1:]) < 20000:
                raise AssertionError(f"옛 v3 지식 번호(시공일지와 겹침) {c.id} {r}")
    assert START == 20001


def test_cards_are_only_author_checked_until_verified():
    assert {c.verified.status for c in CS.cards} == {"author_checked"}
    assert all(c.review_by > c.verified.at for c in CS.cards)


def test_each_card_is_found_by_its_own_first_key():
    hit = sum(1 for c in CS.cards if cards.find(CS, c.keys[0], k=1)[0].card.id == c.id)
    assert hit / CS.n >= 0.95


def test_guest_cards_are_service_cards():
    g = cards.guest_cards(CS)
    assert len(g) >= 3
    assert all(c.trade == "common" and c.kind == "서비스" for c in g)
    first = [c.keys[0] for c in g]
    assert "표준견적서는 업체 견적이에요?" in first and "실측은 돈이 들어요?" in first


def test_deep_trade_asks_use_known_slots():
    from app.agent.v3.trades import BY_CODE

    known = {s.key for t in ("dobae", "mokgong") for s in BY_CODE[t].slots}
    for c in CS.cards:
        if c.ask:
            assert c.trade in ("dobae", "mokgong") and c.ask.slot in known, c.id


def test_compare_tables_cite_known_chunks_and_hold_no_money_or_period():
    ix = repo_index()
    tables = [c for c in CS.cards if c.compare]
    assert tables
    for c in tables:
        refs = {s.ref for s in c.sources}
        for r in c.compare.rows:
            for x in r.cells:
                assert not MONEY_OR_PERIOD.search(x), (c.id, x)
            for ref in r.cites:
                assert ref in ix.by_ref and ref in refs, (c.id, ref)


def test_ask_next_points_to_existing_cards_of_same_trade():
    for c in CS.cards:
        for cid in c.ask.next.values() if c.ask else ():
            assert cid in CS.by_id and CS.by_id[cid].trade in (c.trade, "common"), (c.id, cid)

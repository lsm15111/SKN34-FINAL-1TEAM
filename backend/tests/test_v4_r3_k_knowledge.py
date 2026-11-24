"""고침 3차 K 4 · 5번: 알아 두기 카드(search_knowledge)와 지식 자료. 유료 호출 0회(대본 · 저장소 색인).

- 4(c4 · v1 M2 · c2 19턴 · r2 c3): 카드 제목이 검색어 그대로('추가 금액 추가금 실측 견적서 승인')였고, 상관없는 조각
  (공사 전날 준비물에 이사 · 철거 차량, 벽지 질문에 행위허가 · 비내력벽)이 붙었고, 발췌가 '-다'체 원문 · 안쪽 말('저장소
  전처리본' · PDF 파일 이름)이었어요. → 제목은 맞은 조각의 절 이름, 공사 공정 · 질문 주제로 거르기(bm25.on_topic),
  원문 '-다'체는 '자료에서 “…”', 안쪽 말은 뗌. QA r7 고침 A: 자주 나오는 끝('-한다' · '-본다' …)은 '-요'체로 바꿔
  보이고, 못 바꾸는 끝('센다')만 '자료에서 “…”'로 둬요.
- 5(s5 12번): 소폭 합지(파인하임) 한 롤 6.6㎡를 '합지'로 말했어요 → 지식 줄 K1442가 소폭임을 분명히(광폭은 넓이가 달라요).
"""

import json
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import cards
from app.knowledge import bm25
from tests.test_v4_assistant_turns import ask, home, ok

DOBAE = ("도배", bm25.COMMON)


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def _index(_s):
        return repo_index(), []

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "_index", _index)
    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def kept(q: str, scopes=DOBAE, trade: str | None = None) -> list[bm25.Hit]:
    return bm25.on_topic(bm25.search(repo_index(), q, trade=trade, k=8).hits, scopes)


def refs(hits) -> set[str]:
    return {h.ref for h in hits}


# ---- 거르기(점수 문턱 · 주제) ----


def test_wallpaper_question_drops_the_structural_permit_piece():
    """'벽지 직접 구매 …'에 행위허가 · 비내력벽 조각(K1000)이 붙던 것(v1 M2)."""
    q = "벽지 직접 구매 주의점 수량 로트 도배 전 준비"
    allp = bm25.search(repo_index(), q, k=8).hits
    assert "K1000" in refs(allp)  # 검색에는 걸려요(질문 꼴 낱말 '주의점 · 준비 · 전'만 겹침)
    got = kept(q)
    assert "K1000" not in refs(got) and "K725" in refs(got)
    assert not any("행위허가" in h.text or "비내력벽" in h.text for h in got)


def test_day_before_prep_drops_moving_and_truck_pieces():
    """'공사 전날 준비물'에 이사 방식 · 반포장이사 · 철거 · 자재 차량 동선 조각이 붙던 것(c2 19턴)."""
    for q in ("도배 전날 집 비우기 준비 이사 차량", "공사 전날 준비물"):
        got = kept(q)
        assert not any(("반포장이사" in h.text or "차량 동선" in h.text) for h in got), q
        # 다른 공정(확장 행위허가서 …) 조각 없음
        assert all(bm25.OUT not in h.scope for h in got), q


def test_on_topic_keeps_pieces_that_answer_the_question():
    assert "K405" in refs(kept("곰팡이 덜 생기는 벽지"))
    assert "K1436" in refs(kept("긁힘에 강한 벽지 라인"))
    assert "K1387" in refs(kept("추가 금액 추가금 실측 견적서 승인"))
    # 이 공사 공정이 도배만이면 목공 조각은 빼요
    assert all("목공" not in h.scope or "도배" in h.scope for h in kept("강아지 공사 날 어디"))


# ---- 카드 모양 ----


def test_card_title_quotes_and_inner_words():
    kcs = SimpleNamespace(
        text="[KCS 41 51 05] 도배공사.pdf\n[자료 시점: 제공 PDF의 판본·개정일 미확인]\n[문서 적용범위]\n"
        "1.1 적용범위\n이 기준은 종이 벽지를 붙이는 공사에 적용한다.",
        section="3.3 · 5쪽",
        title="[KCS 41 51 05] 도배공사",
        publisher="",
        official=True,
        source_type="표준시방서",
    )
    pumsem = SimpleNamespace(
        text="도배공은 하루 8시간을 기준으로 품을 센다.",
        section="1-1-3",
        title="2026 건설공사 표준품셈 (국토교통부 · 한국건설기술연구원, 원문 정오표 1차 반영 전처리본)",
        publisher="",
        official=True,
        source_type="표준품셈",
    )
    polite = SimpleNamespace(
        text="합지 벽지 폭은 93cm, 실크 벽지 폭은 106cm예요.",
        section="폭과 소요량",
        title="벽지 - 인테리어 효과",
        publisher="LX하우시스 LX Z:IN 스타일 가이드",
        official=True,
        source_type="제조사",
    )
    card = cards.knowledge_card("k", None, [kcs, pumsem, polite]).data
    assert card["title"] == "도배공사"  # 절 이름이 번호뿐이라 자료 제목(이름표 뗌)
    assert card["lines"][0] == "1.1 적용범위 이 기준은 종이 벽지를 붙이는 공사에 적용해요."
    assert card["lines"][1] == "자료에서 “도배공은 하루 8시간을 기준으로 품을 센다.”"
    # '-요'체 요약은 그대로
    assert card["lines"][2] == "합지 벽지 폭은 93cm, 실크 벽지 폭은 106cm예요."
    joined = json.dumps(card, ensure_ascii=False)
    for inner in (".pdf", "자료 시점", "전처리본", "정오표", "[KCS"):
        assert inner not in joined, inner
    assert card["source"] == "도배공사 · 2026 건설공사 표준품셈 · LX하우시스 LX Z:IN 스타일 가이드"
    # 절 이름이 있으면 그것(번호 · 괄호 · 쪽 뗌), 흐린 첫 절은 끝 절
    first = SimpleNamespace(section="구매 경로", title="KCC신한벽지 고객 FAQ")
    book = SimpleNamespace(
        section="준비사항 · 공사전-현장준비 · 1.현장점검 · 7) 수장공사 · 3쪽", title="시공 안내서"
    )
    long = SimpleNamespace(
        section="도배 전에 가구 치우고 벽에 붙은 것 떼고 바닥 덮기(제조사 셀프 도배 가이드) · 1. 도배 전 준비",
        title="x",
    )
    assert cards.topic_title(first) == "구매 경로"
    assert cards.topic_title(book) == "수장공사"
    assert cards.topic_title(long) == "도배 전에 가구 치우고 벽에 붙은 것 떼고 바닥 덮기"
    longer = SimpleNamespace(
        section="도배 전에 가구를 모두 치우고 벽에 붙은 것을 떼고 바닥을 덮기", title="x"
    )
    # 30자 안, 낱말 끝에서
    assert cards.topic_title(longer) == "도배 전에 가구를 모두 치우고 벽에 붙은 것을 떼고"


def test_search_knowledge_card_is_titled_by_the_piece_not_the_query(api, script):
    _, pid = home(api)
    q = "벽지 직접 구매 주의점 수량 로트 도배 전 준비"
    call = {"id": "s", "name": "search_knowledge", "input": {"query": q, "trade": "common"}}
    log = script([{"tool_calls": [call]}, {"text": "자료를 찾았어요."}])
    ev = ok(ask(api, pid, "벽지 직접 살 때 주의할 거 알려 줘"))
    (card,) = [d for e, d, _ in ev if e == "card" and d["kind"] == "knowledge"]
    data = card["data"]
    assert data["title"] != q[:30] and "로트" not in data["title"]
    body = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    first = kept(q)[0]
    assert data["title"] == cards.topic_title(first)
    assert body["found"] == len(body["hits"]) >= 1
    assert not any("행위허가" in json.dumps(h, ensure_ascii=False) for h in body["hits"])
    assert "행위허가" not in json.dumps(data, ensure_ascii=False)


def test_search_knowledge_without_a_fitting_piece_sends_no_card(api, script):
    _, pid = home(api)
    call = {"id": "s", "name": "search_knowledge", "input": {"query": "공사 날 집에 없어도 되나"}}
    log = script([{"tool_calls": [call]}, {"text": "자료에는 없어요."}])
    ev = ok(ask(api, pid, "공사 날 집에 없어도 돼요?"))
    assert not [d for e, d, _ in ev if e == "card" and d["kind"] == "knowledge"]
    body = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    assert body["found"] == 0 and body["note"]


# ---- 5 · 지식 자료: 소폭 합지 ----


def test_narrow_hapji_row_says_it_is_narrow():
    x = repo_index().by_ref["K1442"]
    assert "소폭 합지 한 롤은 약 6.6㎡" in x.chunk.text
    assert "광폭 합지 한 롤과는 넓이가 달라요" in x.chunk.text
    assert x.chunk.sec == "파인하임 규격(소폭 합지)"
    # 광폭 합지 줄은 실크와 넓이가 거의 같아요(믿집 표준견적서 롤 수의 기본)
    assert "약 16.5㎡" in repo_index().by_ref["K1441"].chunk.text

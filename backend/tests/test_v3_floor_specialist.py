"""바닥 공종 폴더(specialists/floor): 설정 · 검색 보강 · 연결. DB · LLM 호출 없이 검증한다."""

from v3_kb import repo_kb

from app.agent.v3 import answer, trades
from app.agent.v3.specialists import registered
from app.agent.v3.specialists.floor import retrieval
from app.agent.v3.specialists.floor.retrieval import search_query


def test_floor_folder_replaces_builtin_setting():
    s = trades.BY_CODE["floor"]
    assert [x.code for x in trades.SPECS].count("floor") == 1
    assert s.ko == "바닥" and s.depth == "knowledge" and not s.calc  # 계산 엔진이 붙기 전
    assert s.check_where == "실측 때 바닥 업체"
    assert [x.key for x in s.slots] == [
        "floor.kind", "floor.maru_type", "floor.sheet_thick", "floor.existing",
        "floor.remove", "floor.baseboard", "floor.threshold",
    ]  # fmt: skip
    assert all(x.options[-1] in ("아직 몰라요", "잘 몰라요") for x in s.slots)
    sp = registered()["floor"]
    assert sp.retrieve and sp.run and sp.prompt_path and sp.prompt_path.is_file()


def test_floor_words_route_new_customer_terms():
    assert trades.trades_in("PVC 타일이랑 장판 뭐가 나아요?")[0] == "floor"
    assert trades.trades_in("헤링본 마루로 하고 싶어요")[0] == "floor"
    assert trades.trades_in("현관 바닥 타일 바꾸려고요") == ["tile"]  # 바닥 타일은 타일 공종


def test_floor_query_adds_document_words_in_order():
    assert search_query("데코타일 직접 붙여도 돼요?").startswith("비닐합성타일 비닐타일 ")
    # '강마루' 안의 '마루'는 따로 세지 않아 다음 고객 말(본드)이 자리를 얻는다
    assert search_query("강마루 본드 냄새 괜찮아요?").startswith("강화합판마루 접착제 ")
    assert search_query("바닥 공사 끝나고 뭘 확인해요?") == "바닥 공사 끝나고 뭘 확인해요?"


def _record(monkeypatch):
    original = answer.search3.search
    calls = []

    def record(ix, q, **kwargs):
        calls.append((q, kwargs.get("policy_text"), kwargs["trades"]))
        return original(ix, q, **kwargs)

    monkeypatch.setattr(answer.search3, "search", record)
    return calls


def test_floor_search_is_plain_while_expansion_is_off(monkeypatch):
    calls = _record(monkeypatch)
    q = "데코타일 직접 붙여도 돼요?"
    answer.search(repo_kb(), q, "floor")
    assert calls == [(q, None, ["floor"])]  # 보강은 W8 뒤에 다시 재서 켠다


def test_floor_expansion_keeps_original_top_hits(monkeypatch):
    kb = repo_kb()
    q = "데코타일 직접 붙여도 돼요?"
    base = answer.search3.search(kb.ix, q, trades=["floor"], tags=kb.tags, k=retrieval.K).hits
    monkeypatch.setattr(retrieval, "EXPAND", True)
    calls = _record(monkeypatch)
    got = retrieval.retrieve(kb, q).hits
    assert [h.ref for h in got[: retrieval.KEEP]] == [h.ref for h in base[: retrieval.KEEP]]
    assert len({h.ref for h in got}) == len(got) <= retrieval.K
    assert calls[1][0] != q and calls[1][1:] == (q, ["floor"])  # 출처 제한은 원래 질문


def test_floor_source_data_has_own_refs_docs_and_trades():
    kb = repo_kb()
    refs = [r for r in kb.ix.by_ref if 17001 <= int(r[1:]) <= 17999]
    nums = sorted(int(r[1:]) for r in refs)
    assert (
        len(nums) == 395 and nums[0] == 17001 and nums[-1] < 20001
    )  # 시공일지 · v3 지식과 안 겹침
    kcs = kb.ix.by_ref["K17001"]
    assert kcs.doc.kind in ("kcs", "official") and "바닥재" in kcs.chunk.trades + ("타일",)
    assert (
        len({kb.ix.by_ref[r].chunk.doc for r in refs}) == 17
    )  # 출처 문서마다 하나(파일 하나가 문서 하나가 아님)

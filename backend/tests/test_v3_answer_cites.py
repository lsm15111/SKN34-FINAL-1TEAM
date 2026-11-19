"""답 출처 번호(chat.service._public): 코드가 문서마다 처음 나온 순서로 번호를 매기고 문장에 단다. DB 없음."""

from app.agent.v3.schemas import AgentAnswer, Brief, Section, Sentence
from app.chat.service import _public


def _src(ref: str, title: str) -> dict:
    return {"ref": ref, "title": title, "kind": "spec"}


def test_numbers_follow_first_appearance_and_group_same_document():
    a = AgentAnswer(
        sections=[
            Section(
                sentences=[
                    Sentence(text="가", cites=["K2"]),
                    Sentence(text="나", cites=["K1", "card:x@1"]),
                    Sentence(text="다", cites=["K3"]),
                ],
                sources=[_src("K2", "도배 시방"), _src("K1", "벽지 안내"), _src("K3", "도배 시방")],
            ),
            Section(
                sentences=[Sentence(text="라", cites=["K9", "K1"])],
                sources=[_src("K9", "목공 시방"), _src("K1", "벽지 안내")],
            ),
        ],
        brief=Brief(lines=[Sentence(text="가", cites=["K2"]), Sentence(text="모름")], more=3),
    )
    p = _public(a)
    assert [r.title for r in p.refs] == ["도배 시방", "벽지 안내", "목공 시방"]
    # K3은 같은 문서(도배 시방)라 1번. 카드 표시는 번호 없음
    assert p.sections[0].cites == [[1], [2], [1]]
    assert p.sections[1].cites == [[2, 3]]
    assert p.brief is not None and p.brief.cites == [[1], []]


def test_no_sources_means_no_numbers():
    a = AgentAnswer(sections=[Section(sentences=[Sentence(text="정해 둔 글", cites=["K5"])])])
    p = _public(a)
    assert p.refs == [] and p.sections[0].cites == [[]]

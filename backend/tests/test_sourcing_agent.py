"""가견적 에이전트: 출력 검사(숫자 · id · 연락처)와 후보 API 연결. LLM은 가짜 (유료 호출 0회)."""

import pytest

from app.agent import llm
from app.agent import sourcing as agent
from app.agent.sourcing import RouteDraft, SourcingNotes, VendorWhy
from app.quote.service import NOTES_FAILED
from tests.sourcing_helpers import app_vendor, consent, customer_project, ext_vendor

USAGE = llm.Usage("fake", 1, 1, 0, 0, 1)
FACTS = ["도배: 기본형, 거실", "지역: 서울 마포구", "시기: 2026-12-01 시작", "거주: 빈집"]


def cand(key="va", route="link", name="가짜인테리어 1"):
    return agent.Candidate(
        key, name, "외부", "도배", "서울 마포구", route, "확인 필요", "견적 창구 있음"
    )


def check(raw, cands=None, routes=("link",)):
    cands = cands or [cand()]
    text = agent.render(FACTS, cands, list(routes))
    return agent.validate(raw, {c.key for c in cands}, set(routes), agent.allowed_numbers(text))


def test_keys_have_no_digits():
    ks = agent.keys(30)
    assert ks[:3] == ["va", "vb", "vc"] and len(set(ks)) == 30
    assert not any(ch.isdigit() for k in ks for ch in k)


def test_invented_numbers_unknown_ids_and_contacts_are_dropped():
    raw = SourcingNotes(
        reasons=[
            VendorWhy(id="va", why="마포구에 있고 견적 창구가 있어요."),
            VendorWhy(id="va", why="두 번째는 버려요."),
            VendorWhy(id="zz", why="목록에 없는 업체예요."),
        ],
        drafts=[
            RouteDraft(
                route="link", text="믿집에서 정리한 요청이에요. 12월 1일 시작이고 3일이면 끝나요."
            ),
        ],
    )
    notes = check(raw)
    assert notes.why == {"va": "마포구에 있고 견적 창구가 있어요."}
    assert notes.drafts == {} and notes.dropped == 3  # '3일'은 입력에 없는 숫자

    ok = SourcingNotes(
        reasons=[
            VendorWhy(id="va", why="가짜인테리어 1은 같은 구 업체예요.")
        ],  # 이름 속 숫자는 입력값
        drafts=[
            RouteDraft(route="link", text="믿집 요청이에요. 2026년 12월 01일 시작을 바라요."),
            RouteDraft(route="phone", text="요청하지 않은 길이에요."),
        ],
    )
    notes = check(ok)
    assert set(notes.drafts) == {"link"} and notes.dropped == 1
    bad = SourcingNotes(
        reasons=[VendorWhy(id="va", why="홈페이지 https://x.test 를 보세요.")],
        drafts=[RouteDraft(route="link", text="연락은 fake@example.com 으로 주세요.")],
    )
    assert check(bad).why == {} and check(bad).drafts == {}
    long = SourcingNotes(reasons=[VendorWhy(id="va", why="가" * 121)], drafts=[])
    assert check(long).why == {}


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"calls": [], "raise": False, "notes": None}

    async def parse(system, user, schema, **kw):
        state["calls"].append(user)
        if state["raise"]:
            raise llm.LlmError("stub")
        keys = [line.split(" | ")[0][2:] for line in user.splitlines() if line.startswith("- v")]
        return state["notes"] or SourcingNotes(
            reasons=[VendorWhy(id=k, why="같은 구에서 이 공정을 맡아요.") for k in keys],
            drafts=[
                RouteDraft(route="app_request", text="믿집에서 정리한 가견적 요청이에요."),
                RouteDraft(
                    route="link", text="믿집에서 정리한 가견적 요청이에요. 붙여 넣어 주세요."
                ),
            ],
        ), USAGE

    monkeypatch.setattr(llm, "parse", parse)
    return state


def world(api):
    app_vendor(api, "app1@mitjip.test", "가짜앱도배")
    v = ext_vendor(
        "n-link", name="가짜견적창구", quote_url="https://fake-1.test/q", phone="0212345678"
    )
    consent(v)
    ext_vendor("n-ref", name="가짜정보만")
    return customer_project(api)


def test_notes_are_attached_and_cached(api, fake_llm):
    _, pid = world(api)
    out = api.get(f"/projects/{pid}/sourcing").json()
    assert out["notice"] is None and out["prompt_version"] == "sourcing-v1"
    by = {c["name"]: c for c in out["candidates"]}
    assert by["가짜앱도배"]["why"] and by["가짜앱도배"]["draft"].startswith("믿집에서")
    assert by["가짜견적창구"]["route"] == "link" and by["가짜견적창구"]["draft"].endswith(
        "넣어 주세요."
    )
    assert by["가짜정보만"]["route"] == "reference" and by["가짜정보만"]["draft"] is None
    (user,) = fake_llm["calls"]
    # LLM에는 연락처 값 · 링크 · 전화번호를 주지 않는다
    assert "01000000001" not in user and "https://" not in user and "0212345678" not in user
    assert "<input>" in user and "요청문을 쓸 받는 길: app_request" in user
    again = api.get(f"/projects/{pid}/sourcing").json()
    assert len(fake_llm["calls"]) == 1  # 같은 입력은 하루 캐시
    assert again["candidates"] == out["candidates"]


def test_llm_failure_shows_list_without_notes(api, fake_llm):
    fake_llm["raise"] = True
    _, pid = world(api)
    out = api.get(f"/projects/{pid}/sourcing").json()
    assert out["notice"] == NOTES_FAILED and out["prompt_version"] is None
    assert len(out["candidates"]) == 3
    assert all(c["why"] is None and c["draft"] is None for c in out["candidates"])


def test_all_invalid_output_counts_as_failure(api, fake_llm):
    fake_llm["notes"] = SourcingNotes(
        reasons=[VendorWhy(id="zz", why="목록 밖")],
        drafts=[RouteDraft(route="link", text="99만 원이면 돼요.")],
    )
    _, pid = world(api)
    out = api.get(f"/projects/{pid}/sourcing").json()
    assert out["notice"] == NOTES_FAILED
    assert all(c["why"] is None for c in out["candidates"])


def test_stub_mode_never_calls_the_model(api):
    # LLM_LIVE=false(기본, CI)면 llm.parse가 부르지 않고 실패로 돌려준다
    _, pid = world(api)
    assert api.get(f"/projects/{pid}/sourcing").json()["notice"] == NOTES_FAILED

"""받는 길 고르기 규칙과 후보 목록 API (가짜 업체, LLM 호출 없음)."""

from datetime import UTC, datetime

import pytest

from app.config import settings
from app.quote.service import NO_CANDIDATES
from app.quote.sourcing import Facts, call_checklist, choose, cost_label
from tests.helpers import signup, use
from tests.sourcing_helpers import app_vendor, consent, customer_project, ext_vendor

ON, OFF = True, False


@pytest.mark.parametrize(
    ("facts", "enabled", "route", "cost", "proxy_off"),
    [
        (Facts(is_app=True), OFF, "app_request", "free", False),
        (Facts(is_app=False, has_consented_contact=True), ON, "proxy", "unknown", False),
        # 동의한 연락처가 있어도 꺼져 있으면 다음 길로, 꺼져 있다고 알린다
        (Facts(is_app=False, has_consented_contact=True, quote_url="https://x.test/q"), OFF,
         "link", "unknown", True),
        (Facts(is_app=False, has_consented_contact=True), OFF, "reference", "unknown", True),
        # 수신거부한 업체에는 대신 연락하지 않는다
        (Facts(is_app=False, has_consented_contact=True, opted_out=True, phone="0212345678"), ON,
         "phone", "unknown", False),
        (Facts(is_app=False, quote_url="https://x.test/q", phone="0212345678"), ON, "link",
         "unknown", False),
        (Facts(is_app=False, phone="0212345678", visit_fee=0), ON, "phone", "free", False),
        (Facts(is_app=False, visit_fee=50000), ON, "reference", "vendor_fee", False),
        (Facts(is_app=False), ON, "reference", "unknown", False),
    ],
)  # fmt: skip
def test_route_rule_table(facts, enabled, route, cost, proxy_off):
    c = choose(facts, proxy_enabled=enabled)
    assert (c.route, c.cost, c.proxy_off) == (route, cost, proxy_off)


def test_cost_labels_and_call_checklist():
    labels = [
        cost_label(choose(Facts(is_app=True), proxy_enabled=False)),
        cost_label(choose(Facts(is_app=False, visit_fee=0), proxy_enabled=False)),
        cost_label(choose(Facts(is_app=False, visit_fee=50000), proxy_enabled=False)),
        cost_label(choose(Facts(is_app=False), proxy_enabled=False)),
    ]
    assert labels == ["무료", "무료 (업체 공지)", "출장비 50,000원 (업체 공지)", "확인 필요"]
    assert len(call_checklist(["dobae", "mokgong"])) == len(call_checklist([])) + 4
    assert call_checklist(["tile"]) == call_checklist([])  # 아직 공정별 항목이 없는 공정


def setup_world(api):
    """고객 프로젝트(서울 마포구 도배 · 목공)와 여러 조건의 업체들"""
    app_vendor(api, "app1@mitjip.test", "가짜앱도배", trades=("dobae",))
    app_vendor(api, "app2@mitjip.test", "가짜앱목공", trades=("mokgong",), area=("seoul", "강동구"))
    app_vendor(api, "app3@mitjip.test", "가짜승인대기", approved=False)
    ids = {
        "link": ext_vendor("e-link", name="가짜견적창구", quote_url="https://fake-1.test/q"),
        "phone": ext_vendor("e-phone", name="가짜전화", trades=["mokgong"], phone="0212345678"),
        "far": ext_vendor("e-far", name="가짜옆동네", sgg="서대문구", visit_fee=30000),
        "consent": ext_vendor("e-consent", name="가짜동의", visit_fee=0),
    }
    consent(ids["consent"])
    ext_vendor("e-out", name="가짜수신거부", opted_out=True)
    ext_vendor(
        "e-closed",
        name="가짜폐업",
        reg_kind="business",
        reg_no="1000000009",
        biz_status="closed",
        biz_checked_at=datetime.now(UTC),
    )
    ext_vendor("e-busan", name="가짜부산", sido="busan", sgg="해운대구")
    ext_vendor("e-window", name="가짜창호", trades=["window"])
    token, pid = customer_project(api)
    return token, pid, ids


def test_candidates_routes_costs_and_sources(api):
    _, pid, _ = setup_world(api)
    r = api.get(f"/projects/{pid}/sourcing")
    assert r.status_code == 200, r.text
    out = r.json()
    names = [c["name"] for c in out["candidates"]]
    # 앱 업체 먼저, 외부는 같은 구 · 동의한 연락처 · 견적 창구 순. 수신거부 · 폐업 · 다른 시도 · 다른 공정은 없다
    assert names == ["가짜앱도배", "가짜동의", "가짜견적창구", "가짜전화", "가짜옆동네"]
    by = {c["name"]: c for c in out["candidates"]}
    assert (
        by["가짜앱도배"]["route"] == "app_request" and by["가짜앱도배"]["cost"]["label"] == "무료"
    )
    assert by["가짜앱도배"]["source"]["kind"] == "app"
    assert by["가짜견적창구"]["route"] == "link"
    assert by["가짜견적창구"]["links"]["quote"] == "https://fake-1.test/q"
    phone = by["가짜전화"]
    assert phone["route"] == "phone" and phone["phone"] == "02-1234-5678"
    assert phone["checklist"] and phone["trades"] == ["mokgong"]
    far = by["가짜옆동네"]
    assert (far["near"], far["region"], far["route"]) == (False, "서울 서대문구", "reference")
    assert far["cost"] == {
        "kind": "vendor_fee",
        "amount": 30000,
        "label": "출장비 30,000원 (업체 공지)",
    }
    assert far["source"]["label"] == "개발용 가짜 데이터" and far["source"]["fetched_at"]
    # 동의한 연락처가 있어도 대신 연락이 꺼져 있으면 정보만, 꺼져 있다고 알린다
    assert out["proxy_enabled"] is False
    assert (by["가짜동의"]["route"], by["가짜동의"]["proxy_off"]) == ("reference", True)
    assert by["가짜동의"]["cost"]["label"] == "무료 (업체 공지)"
    assert all(c["why"] is None and c["draft"] is None for c in out["candidates"])
    assert "01000000001" not in r.text  # 동의한 연락처 값은 내보내지 않는다
    assert out["facts"][:2] == [
        "도배: 기본형, 거실 · 방 · 방 2",
        "목공: 천장 몰딩 · 걸레받이, 거실",
    ]
    assert "지역: 서울 마포구" in out["facts"]
    assert "집: 아파트, 30평대 (공급), 2009년 준공, 발코니 확장" in out["facts"]


def test_proxy_route_when_enabled(api, monkeypatch):
    monkeypatch.setattr(settings, "contact_send_enabled", True)
    _, pid, ids = setup_world(api)
    by = {c["id"]: c for c in api.get(f"/projects/{pid}/sourcing").json()["candidates"]}
    assert by[ids["consent"]]["route"] == "proxy" and by[ids["consent"]]["proxy_off"] is False


def test_only_the_owner_customer_sees_candidates(api):
    _, pid, _ = setup_world(api)
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{pid}/sourcing").status_code == 404  # 남의 것은 있는지도 모른다
    vendor_token, _ = app_vendor(api, "app9@mitjip.test", "가짜업체9")
    use(api, vendor_token)
    assert api.get(f"/projects/{pid}/sourcing").status_code == 403  # 역할이 다르면 403
    api.cookies.clear()
    assert api.get(f"/projects/{pid}/sourcing").status_code == 401


def test_no_candidates_says_so(api):
    _, pid = customer_project(api, sido="jeju", sgg="제주시")
    out = api.get(f"/projects/{pid}/sourcing").json()
    assert out["candidates"] == [] and out["notice"] == NO_CANDIDATES

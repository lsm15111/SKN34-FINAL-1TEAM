"""가견적 테스트가 같이 쓰는 준비 (합성 데이터: 가짜 고객 · 가짜 업체, 실제 업체 아님)."""

import uuid

from app.config import settings
from tests.conftest import query
from tests.helpers import signup, vendor_signup
from tests.test_directory_models import add
from tests.test_project import body


def customer_project(api, email: str = "customer@mitjip.test", **over) -> tuple[str, str]:
    """고객 가입 + 프로젝트 (서울 마포구, 도배 · 목공). (세션 토큰, 프로젝트 id)"""
    token = signup(api, email)
    r = api.post("/projects", json=body(**over))
    assert r.status_code == 201, r.text
    return token, r.json()["id"]


def app_vendor(
    api,
    email: str,
    name: str,
    trades=("dobae",),
    area=("seoul", "마포구"),
    approved: bool = True,
) -> tuple[str, str]:
    """앱 업체 가입 + (승인) + 공정 · 시공 지역. (세션 토큰, 업체 id)"""
    r = vendor_signup(api, email=email)
    assert r.status_code == 201, r.text
    vid = uuid.UUID(r.json()["id"])
    token = api.cookies.get(settings.session_cookie)
    query("update vendors set biz_name = $1 where user_id = $2", name, vid)
    if approved:
        query("update vendors set status = 'approved', reviewed_at = now() where user_id = $1", vid)
    for t in trades:
        query("insert into vendor_trades (vendor_id, trade) values ($1, $2)", vid, t)
    query("insert into vendor_areas (vendor_id, sido, sgg) values ($1, $2, $3)", vid, *area)
    return token, str(vid)


def ext_vendor(source_id: str, **cols) -> str:
    """외부 업체 한 곳 (기본: 서울 마포구 도배)"""
    add(**({"source_id": source_id, "sido": "seoul", "sgg": "마포구"} | cols))
    return str(query("select id from ext_vendors where source_id = $1", source_id)[0]["id"])


def consent(vendor_id: str, channel: str = "sms", value: str = "01000000001") -> None:
    """업체가 동의해 준 연락처 (가짜 번호)"""
    query(
        "insert into ext_vendor_contacts (id, vendor_id, channel, value, consented_at, source)"
        " values (gen_random_uuid(), $1, $2, $3, now(), 'seed')",
        uuid.UUID(vendor_id),
        channel,
        value,
    )

"""T02 v3 새 경로(채팅 · 줄기 · 리뷰 · 신고 · 회원 관리)의 권한 문: 로그인 없으면 401, 역할이 다르면 403.
남의 것 404 · 로그인 전 본문 한도 · 실제 줄기 출처는 test_sec_threads.py에 있어요."""

import uuid

import pytest

from tests.helpers import make_admin, signup, vendor_signup

X = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/threads"),
        ("get", f"/threads/{X}/messages"),
        ("post", f"/threads/{X}/messages"),
        ("get", "/stream"),
        ("post", "/reports"),
        ("get", "/vendor/reviews"),
        ("post", f"/projects/{X}/deals/{X}/review"),
        ("get", "/admin/reports"),
        ("get", "/admin/members"),
    ],
    # 작업마다 생성되는 UUID가 테스트 수집 ID를 바꾸지 않게 한다.
    ids=lambda value: value.replace(X, "{id}"),
)
def test_new_routes_need_login(api, method, path):
    api.cookies.clear()
    r = getattr(api, method)(path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "login_required"


def test_customers_cannot_use_vendor_or_admin_routes(api):
    signup(api)
    for method, path in (
        ("get", "/vendor/reviews"),
        ("put", f"/vendor/reviews/{X}/reply"),
        ("get", "/admin/reports"),
        ("post", f"/admin/reports/{X}/resolve"),
        ("get", "/admin/members"),
        ("post", f"/admin/members/{X}/suspend"),
        ("post", f"/admin/reviews/{X}/hide"),
    ):
        assert getattr(api, method)(path).status_code == 403, path


def test_vendors_cannot_use_customer_or_admin_routes(api):
    vendor_signup(api)
    for method, path in (
        ("post", f"/threads/{X}/block"),  # 차단은 고객만
        ("post", f"/projects/{X}/deals/{X}/review"),  # 리뷰 쓰기는 고객만
        ("patch", f"/reviews/{X}"),
        ("get", "/admin/reports"),
        ("post", f"/admin/members/{X}/suspend"),
    ):
        assert getattr(api, method)(path).status_code == 403, path
    pending = api.get("/vendor/reviews")  # 승인 전 업체는 업체 기능도 못 쓴다
    assert pending.status_code == 403 and pending.json()["error"]["code"] == "vendor_not_approved"


def test_admins_are_not_chat_parties(api):
    make_admin(api)
    for method, path in (("get", "/threads"), ("post", "/reports"), ("post", f"/threads/{X}/read")):
        assert getattr(api, method)(path).status_code == 403, path

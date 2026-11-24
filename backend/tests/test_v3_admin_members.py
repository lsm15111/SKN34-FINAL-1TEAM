"""관리자 회원 · 업체 멈춤 · 탈퇴 때 대화 (B1b, A03 · D26 · C53 · b7.md W6): 회원 찾기 · 상태 · 공사 수 · 쪽 나누기,
정지하면 세션이 바로 끊김 · 로그인 막힘 · 관리자 계정은 못 정지 · 이미면 409, 업체 멈춤 새 요청만 · 진행 중도 ·
풀기(멈춤으로 닫은 대화 중 요청이 살아 있는 것만 다시 열림), 탈퇴하면 대화는 읽기만(withdrawn) · 글 · 이름표는 남음."""

import uuid

from tests.conftest import query
from tests.helpers import PASSWORD, make_admin, signup, use
from tests.test_v3_thread_api import pair, project_for, send, user_id

FAKE_USER = (
    "insert into users (id, email, password_hash, name, phone, role, created_at)"
    " values ($1, $2, 'x', $3, '01000000000', 'customer', now() - make_interval(mins => $4))"
)


def test_member_list_search_status_and_pages(api):
    a = signup(api, "haneul@example.com", name="김하늘")
    signup(api, "doyun@example.com", name="김도윤")
    signup(api, "minjun@example.com", name="이민준")
    project_for(user_id("haneul@example.com"))
    project_for(user_id("haneul@example.com"), "수유동")
    admin = make_admin(api)
    use(api, admin)
    page = api.get("/admin/members").json()
    assert [x["email"] for x in page["items"]] == [
        "minjun@example.com",
        "doyun@example.com",
        "haneul@example.com",
    ]  # 가입 최근 순 · 관리자는 빼요
    haneul = page["items"][-1]
    assert (haneul["name"], haneul["role"], haneul["status"], haneul["project_count"]) == (
        "김하늘",
        "customer",
        "active",
        2,
    )
    assert page["next_before"] is None
    found = api.get("/admin/members", params={"q": "김"}).json()["items"]
    assert {x["name"] for x in found} == {"김하늘", "김도윤"}
    by_mail = api.get("/admin/members", params={"q": "MINJUN@"}).json()["items"]
    assert [x["name"] for x in by_mail] == ["이민준"]
    assert api.get("/admin/members", params={"q": "%"}).json()["items"] == []  # 글자 그대로 찾음
    uid = user_id("haneul@example.com")
    assert (
        api.post(f"/admin/members/{uid}/suspend", json={"note": "욕설 신고 3건"}).status_code == 200
    )
    stopped = api.get("/admin/members", params={"status": "suspended"}).json()["items"]
    assert [x["email"] for x in stopped] == ["haneul@example.com"]
    # 50명씩: 가입일이 다른 가짜 회원 52명 (비밀번호 해시 없음, 목록만 보려고)
    for n in range(52):
        query(FAKE_USER, uuid.uuid4(), f"m{n}@example.com", f"회원{n}", 100 + n)
    first = api.get("/admin/members").json()
    assert len(first["items"]) == 50 and first["next_before"] is not None
    rest = api.get("/admin/members", params={"before": first["next_before"]}).json()
    assert len(rest["items"]) == 5 and rest["next_before"] is None
    use(api, a)
    assert api.get("/admin/members").status_code == 401  # 정지돼 세션이 지워졌다


def test_suspend_member_cuts_sessions_and_blocks_login(api):
    token = signup(api, "c@mitjip.test")
    uid = user_id("c@mitjip.test")
    admin = make_admin(api)
    use(api, admin)
    r = api.post(f"/admin/members/{uid}/suspend", json={"note": "사기 의심"})
    assert r.status_code == 200 and r.json() == {"user_id": str(uid), "status": "suspended"}
    assert query("select count(*) n from user_sessions where user_id = $1", uid)[0]["n"] == 0
    again = api.post(f"/admin/members/{uid}/suspend", json={})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already"
    use(api, token)
    assert api.get("/me").status_code == 401  # 세션이 바로 끊긴다
    api.cookies.clear()
    login = api.post("/auth/login", json={"email": "c@mitjip.test", "password": PASSWORD})
    assert login.status_code == 403 and login.json()["error"]["code"] == "suspended"
    use(api, admin)
    assert api.post(f"/admin/members/{uid}/unsuspend", json={}).json()["status"] == "active"
    assert api.post(f"/admin/members/{uid}/unsuspend", json={}).status_code == 409
    api.cookies.clear()
    assert (
        api.post("/auth/login", json={"email": "c@mitjip.test", "password": PASSWORD}).status_code
        == 200
    )
    use(api, admin)
    me = query("select id from users where role = 'admin'")[0]["id"]
    r = api.post(f"/admin/members/{me}/suspend", json={})
    assert r.status_code == 403  # 관리자 계정은 정지하지 않는다
    assert api.post(f"/admin/members/{uuid.uuid4()}/suspend", json={}).status_code == 404
    acts = query("select action, target_user_id, note from admin_actions order by at")
    assert [(a["action"], a["note"]) for a in acts] == [
        ("suspend_user", "사기 의심"),
        ("unsuspend_user", None),
    ]
    assert all(a["target_user_id"] == uid for a in acts)


def test_vendor_suspend_new_then_all_then_unsuspend(api):
    # 확정한 공사(요청 chosen)는 멈춤(all)으로 닫히지 않아 멈춤을 풀면 대화가 다시 열린다.
    # 멈춤으로 닫힌 요청의 대화는 풀어도 읽기만이다(test_v4_audit_flow, 점검 R4#4)
    p = pair(api, status="chosen")
    admin = make_admin(api)
    use(api, admin)
    url = f"/admin/vendors/{p.vid}"
    r = api.post(f"{url}/suspend", json={"scope": "new", "note": "확인 중"})
    assert r.status_code == 200, r.text
    assert (r.json()["suspend_scope"], r.json()["closed_visits"]) == ("new", 0)
    first_at = r.json()["suspended_at"]
    assert query("select status from threads")[0]["status"] == "open"  # 새 요청만: 대화는 그대로
    assert api.post(f"{url}/suspend", json={"scope": "new", "note": "또"}).status_code == 409
    wider = api.post(f"{url}/suspend", json={"scope": "all", "note": "사기 확인"}).json()
    assert (
        wider["suspend_scope"] == "all" and wider["suspended_at"] == first_at
    )  # 처음 멈춘 때 그대로
    t = query("select status, ro_reason from threads")[0]
    assert (t["status"], t["ro_reason"]) == ("read_only", "admin")
    assert api.post(f"{url}/suspend", json={"scope": "all", "note": "또"}).status_code == 409
    use(api, p.vendor)
    assert send(api, p.tid, "안녕하세요").status_code == 409
    use(api, admin)
    r = api.post(f"{url}/unsuspend", json={})
    assert r.status_code == 200 and (r.json()["suspended_at"], r.json()["suspend_scope"]) == (
        None,
        None,
    )
    assert (
        query("select status from threads")[0]["status"] == "open"
    )  # 멈춤으로 닫은 대화는 다시 열림
    assert api.post(f"{url}/unsuspend", json={}).status_code == 409
    assert (
        api.post(
            f"/admin/vendors/{uuid.uuid4()}/suspend", json={"scope": "new", "note": "x"}
        ).status_code
        == 404
    )
    assert api.post(f"{url}/suspend", json={"scope": "new"}).status_code == 422  # 메모 필수
    acts = [a["action"] for a in query("select action from admin_actions order by at")]
    assert acts == ["suspend_vendor", "suspend_vendor", "unsuspend_vendor"]
    assert (
        query("select count(*) n from notifications where kind = 'vendor_suspended'")[0]["n"] == 2
    )
    # 고객이 차단한 대화는 멈춤을 풀어도 닫힌 채
    use(api, p.customer)
    assert api.post(f"/threads/{p.tid}/block").status_code == 200
    use(api, admin)
    api.post(f"{url}/suspend", json={"scope": "all", "note": "다시"})
    api.post(f"{url}/unsuspend", json={})
    t = query("select status, ro_reason from threads")[0]
    assert (t["status"], t["ro_reason"]) == ("read_only", "blocked")


def test_withdraw_closes_chats_and_keeps_messages(api):
    p = pair(api)
    use(api, p.customer)
    send(api, p.tid, "101동 1203호예요")
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 204
    t = query("select status, ro_reason, customer_id, project_id, customer_label from threads")[0]
    assert (t["status"], t["ro_reason"], t["customer_id"], t["project_id"]) == (
        "read_only",
        "withdrawn",
        None,
        None,
    )
    assert t["customer_label"] == "상계동 고객"  # 이름표는 남는다
    use(api, p.vendor)
    (row,) = api.get("/threads").json()
    assert (row["title"], row["status"], row["ro_reason"]) == (
        "상계동 고객",
        "read_only",
        "withdrawn",
    )
    msgs = api.get(f"/threads/{p.tid}/messages").json()
    assert [m["from"] for m in msgs] == ["system", "them"]  # 보낸 글은 그 업체 채팅에 남아요(C53)
    assert send(api, p.tid, "안녕하세요").status_code == 409
    # 업체가 탈퇴해도 고객 쪽 대화는 읽기만
    q = pair(api, "c2@mitjip.test", "v2@mitjip.test", "결도배")
    use(api, q.vendor)
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 204
    use(api, q.customer)
    (row,) = api.get("/threads").json()
    assert (row["title"], row["status"], row["ro_reason"]) == ("결도배", "read_only", "withdrawn")

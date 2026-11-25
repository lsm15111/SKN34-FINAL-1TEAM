"""QA r7 화면 고침 C: 업체가 보는 요청 자세히에도 고객이 직접 할 일(N5).

화면에서 보낸 실측 요청의 '고객이 직접 할 일'(요청 때 고정한 사본 visits.diy)을 요청 화면(기간 답하기 · 날짜 수락 ·
실측 확정)과 작업함 옆 자세히가 읽는 GET /vendor/visits/{id}에 화면 말로 줘요.
유료 호출 0회."""

from tests.helpers import use
from tests.test_v3_visit_kit import add, ask, customer, vendor, visit_of
from tests.test_visit_inbox import login


def test_vendor_request_detail_shows_customer_diy(api):
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    token, pid = customer(api)
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["silicone", "outlet"]}).status_code == 200
    assert add(api, pid, vid).status_code == 201
    assert ask(api, pid, [vid]).status_code == 201
    visit = visit_of(pid, vid)

    login(api, "maru@mitjip.test")
    r = api.get(f"/vendor/visits/{visit}")
    assert r.status_code == 200, r.text
    # 칩 순서 · 화면 말 그대로
    assert r.json()["diy"] == ["콘센트 · 스위치 커버", "실리콘 · 줄눈"]

    # 고객이 '없어요'로 바꾸면 확정 전 요청 사본도 비어요(visit.flow.sync_diy)
    use(api, token)
    assert api.put(f"/projects/{pid}/diy", json={"diy": []}).status_code == 200
    login(api, "maru@mitjip.test")
    assert api.get(f"/vendor/visits/{visit}").json()["diy"] == []

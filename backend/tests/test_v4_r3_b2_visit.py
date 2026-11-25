"""고침 3차 B2(QA r3 s1 · s4 · s6 · c1 · c4 #37 · v1 M6 · r2 c6): 지역 바꾸기 · 잠금 풀기 · 다른 구 업체 읽기 · 맡긴
고르기(점수 1위) · 취소 대상 고르기 · 닫힌 요청 · 취소 뒤 단계 · 작업 줄 · 새 소식 · 바뀐 카드 줄 · 반나절 뒤 일 · 다른
시간 후보 · 다른 날 제안 · 잠긴 뒤 칸 단추. 유료 호출 0회(Claude 대본 · LLM 꺼짐)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.calc.schedule import wish_open, wishes_blocked, workdays
from app.visit import service as visit_service
from tests.helpers import use
from tests.test_dates import OFF, TODAY
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import booked
from tests.test_v3_visit_kit import status as visit_status
from tests.test_visit_inbox import login


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def cancel(api, pid: str, visit: str):
    r = api.post(f"/projects/{pid}/visits/{visit}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text


def locked(api, pid: str) -> bool:
    return api.get(f"/projects/{pid}").json()["locked"]


# ---- 결정 1 · 2: 지역 바꾸기 · 잠금 풀기 ----


def test_a_sent_quote_keeps_home_locked_after_every_request_is_closed(api):
    f = booked(api)  # 실측 잡힘 → 견적서 옴 → 다시 고르기로 모두 닫힘
    login(api, f["email"])
    quote(api, f["visit"], 3_080_000)
    use(api, f["token"])
    r = api.post(f"/projects/{f['pid']}/visits/reselect", json={"trade": "dobae"})
    assert r.status_code == 200, r.text
    assert visit_status(f["visit"]) == "closed"
    assert locked(api, f["pid"]) is True  # 견적서가 온 뒤에는 풀리지 않아요
    # 견적서 없이 다시 고르기로 닫으면 풀려요
    g = booked(api, email="gyeol@mitjip.test", name="결도배", customer_email="b@mitjip.test")
    r = api.post(f"/projects/{g['pid']}/visits/reselect", json={"trade": "dobae"})
    assert r.status_code == 200, r.text
    assert locked(api, g["pid"]) is False


# ---- 결정 3 · 4: 다른 구 업체 읽기 · 맡기면 점수 1위 ----


# ---- 취소: 대상이 여럿이면 고르기 · 닫힌 요청은 카드 없음 ----


def test_ended_why_names_the_reason_of_each_closed_request():
    def v(status, **kw):
        return SimpleNamespace(
            **{"close_reason": None, "expired_reason": None, **kw}, status=status
        )

    assert visit_service.ended_why(v("requested")) is None
    assert visit_service.ended_why(v("closed", close_reason="other_chosen")) == (
        "다른 업체를 확정해서 닫힌 요청이에요"
    )
    assert visit_service.ended_why(v("expired", expired_reason="reply")).startswith(
        "업체가 48시간 안에"
    )
    assert visit_service.ended_why(v("quoted")).startswith("견적서가 온 요청이라")


# ---- 취소 뒤: 단계 · 작업 줄 수 · 새 소식 ----


# ---- 바뀐 카드 줄 · 반나절 뒤 일 · 다른 시간 ----


# ---- 결정 5: 다른 날 제안(r2 c6) ----


def test_wish_judgment_sees_the_whole_block_not_only_the_start_day():
    d = workdays(TODAY + timedelta(days=35), 5, OFF)
    busy = [d[1], d[3]]  # 바란 시작일(d0 · d2) 자체는 비었지만 이어지는 날이 다른 공사
    assert wish_open(d[0], 1, busy, OFF) is True
    assert wish_open(d[0], 3, busy, OFF) is False
    assert wishes_blocked([d[0], d[2]], 3, TODAY, busy, OFF) is True
    assert wishes_blocked([d[0], d[2]], 1, TODAY, busy, OFF) is False
    assert wishes_blocked([TODAY], 3, TODAY) is True  # 지난 날은 막힌 것
    sat = next(x for x in (TODAY + timedelta(days=i) for i in range(30, 40)) if x.weekday() == 5)
    assert wish_open(sat, 2) is False  # 일하는 날이 아닌 시작일


# ---- 잠긴 뒤 옛 카드 칸 단추(v1 M6) ----

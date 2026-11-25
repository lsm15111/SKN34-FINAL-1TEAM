"""QA 9차 F2(실측 흐름 도구 · 카드). 유료 호출 0회(Claude 대본 · LLM 꺼짐). 업체 지시문(M5)은
test_v4_r3_a1_prompt.

- H1: 업체가 다른 날을 낸 뒤(proposed) 처음 실측 가능 기간에서 다시 고르는 후보 · 승인 카드(repick + pick 한 번에).
- M1: 같은 업체 두 번째 요청의 취소 카드 · 이어 하기 안내가 다시 요청할 수 없다고 미리 말하고, 막힌 업체는 추천 ·
  요청에서 까닭을 남겨요.
- 낮음: 실측 말(실측 가능 기간 · 이 날짜로 고르기 · 고른 실측 날짜 · 칩) · 콕 집은 요일 먼저 · 요청 뒤 요일 바꾸기 길 ·
  취소 메모 상태별 · 실측 확정 할 일 줄 · 오늘 정할 일 한 줄.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from v3_kb import repo_index

from app.calc import slots
from app.calc.progress import TradeFacts, progress
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import use
from tests.test_v3_visit_kit import (
    booked,
    d,
    day,
    picked,
    requested,
    run,
    user_id,
    with_user,
)
from tests.test_v3_visit_kit import status as visit_status
from tests.test_v4_r3_b2_visit import cancel
from tests.test_visit_inbox import login


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


SLOTS = {"prefer": "any", "days": "any"}


def proposed(api) -> dict:
    """바로 확정 끔 → 고객이 오늘 + 6일 오전을 고름 → 업체가 오늘 + 7일 오후 · 8일 오전을 냄(고객으로 로그인한 채)."""
    f = picked(api)
    login(api, f["email"])
    body = {
        "reason_code": "other_site",
        "note": "오전은 다른 현장이에요",
        "slots": [{"day": d(7), "half": "pm"}, {"day": d(8), "half": "am"}],
    }
    r = api.post(f"/vendor/visits/{f['visit']}/propose", json=body)
    assert r.status_code == 200, r.text
    use(api, f["token"])
    return f


def second_try(api) -> dict:
    """마루와벽 요청 → 취소 → 한 번 더 요청(시도 2). visit은 두 번째 요청(고객으로 로그인한 채)."""
    f = requested(api)
    cancel(api, f["pid"], f["visit"])
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/again")
    assert r.status_code == 201 and r.json()["attempt"] == 2, r.text
    return {**f, "first": f["visit"], "visit": r.json()["visit_id"]}


def rows_of(got: dict) -> dict[str, str]:
    return {r["label"]: r["value"] for r in got["summary"]["rows"] if "value" in r}


# ---- H1: 업체가 낸 날 대신 처음 실측 가능 기간에서 다시 고르기 ----


def test_repick_pick_keeps_the_proposal_when_the_pick_fails(api):
    from app.visit import flow
    from app.visit.schemas import SlotIn

    f = proposed(api)

    def go(s, user):
        data = SlotIn(day=day(20), half="am")  # 처음 기간(5 ~ 12일) 밖
        return flow.repick_pick(
            s, user, uuid.UUID(f["pid"]), uuid.UUID(f["visit"]), data, datetime.now(UTC)
        )

    with pytest.raises(AppError) as e:
        run(with_user(user_id("home@mitjip.test"), go))
    assert e.value.code == "invalid"
    assert visit_status(f["visit"]) == "proposed"  # 다시 고르기도 같이 되돌려요
    assert query("select status from visit_proposals")[0]["status"] == "open"


# ---- M1: 같은 업체 두 번째 요청 ----


# ---- 낮음: 실측 말 ----


# ---- 낮음: 콕 집은 요일 먼저 ----


def test_named_weekday_comes_before_the_other_weekend_day():
    sat = date(2026, 12, 12)  # 토요일
    sun = sat + timedelta(days=1)
    days = [slots.DayOpen(sat, 2, 2), slots.DayOpen(sun, 2, 2)]
    work = sun + timedelta(days=22)  # 희망일 − 20일 = 일요일 다음 날: 일요일이 더 가까워요
    old = slots.candidates(days, work, sat - timedelta(days=5), day_prefer="weekend", n=1)
    assert old[0].day == sun  # 주말로만 보면 일요일이 먼저
    got = slots.candidates(
        days, work, sat - timedelta(days=5), day_prefer="weekend", n=1, named=frozenset({5})
    )
    assert got[0].day == sat and "prefer_day" in got[0].why
    # 요일을 말하지 않고(any) 토요일만 콕 집어도 토요일 먼저
    got = slots.candidates(days, work, sat - timedelta(days=5), n=1, named=frozenset({5}))
    assert got[0].day == sat


# ---- 낮음: 요청 뒤 요일 바꾸기 길 ----


# ---- 낮음: 취소 메모는 상태마다 ----


# ---- 낮음: 실측 확정 할 일 줄 ----


def test_progress_says_the_visit_date_is_set():
    base = TradeFacts(
        trade="dobae",
        created_on=date(2026, 11, 2),
        standard_on=date(2026, 11, 2),
        asked=2,
        asked_on=date(2026, 11, 2),
        quotes=0,
        waiting=0,
        quoted_on=None,
    )
    now = datetime(2026, 11, 8, 3, tzinfo=UTC)
    assert progress(base, date(2026, 11, 8), now).todo == "visit_requested"
    one = TradeFacts(**{**base.__dict__, "booked": 1})
    assert progress(one, date(2026, 11, 8), now).todo == "visit_requested"  # 한 곳은 아직 맞추는 중
    both = TradeFacts(**{**base.__dict__, "booked": 2})
    assert progress(both, date(2026, 11, 8), now).todo == "visit_booked"


def test_overview_todo_after_the_visit_is_booked(api):
    f = booked(api)
    t = api.get(f"/projects/{f['pid']}/overview").json()["trades"][0]["todo"]
    assert t["code"] == "visit_booked" and t["text"].startswith("실측 날짜가 정해졌어요")


# ---- 낮음: 오늘 정할 일은 같은 일을 한 줄로 ----

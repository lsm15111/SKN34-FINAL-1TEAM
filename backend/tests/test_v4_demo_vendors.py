"""v4 목업 업체 심기(app/demo_vendors.py, 명세 demo_assets/mock_vendors.json). LLM 없이(유료 호출 0회).

- 명세 수 그대로: 업체 상태별 · 공정별 · 지역, 업체마다 끝낸 공사 · 리뷰 수, 꽉 찬 업체의 실측 달력.
- 두 번 돌려도 같다(멱등), 되돌리기는 v4m-* 계정과 거기 딸린 행 · 파일만 지운다.
- 다른 구 샘플 고객 다섯이 받는 추천 3곳(recommend_vendors, 계산 엔진 점수)이 서로 다르고 점수가 갈린다.
- 고객 · 업체 · 관리자 화면 API가 지난 공사 · 달력 행으로 500을 내지 않는다."""

import asyncio
from collections import Counter
from datetime import timedelta
from pathlib import Path

from app import demo, demo_vendors
from app.auth import repository as auth_repo
from app.config import settings
from app.db import SessionLocal, engine
from app.shared.clock import today_seoul
from app.visit import service as visit_service
from tests.conftest import query
from tests.helpers import make_admin, signup

SPEC = demo_vendors.load_spec()
VENDORS = {v["no"]: v for v in SPEC["vendors"]}
TABLES = (
    "users", "vendors", "vendor_areas", "vendor_trades", "vendor_faqs", "vendor_portfolio",
    "vendor_price_sets", "vendor_review_links", "projects", "visits", "visit_windows", "visit_holds",
    "vendor_quotes", "deals", "reviews", "review_replies", "files", "notifications", "admin_actions",
)  # fmt: skip
COUNT_SQL = " union all ".join(f"select '{t}' t, count(*) n from {t}" for t in TABLES)


def _counts() -> dict[str, int]:
    return {r["t"]: r["n"] for r in query(COUNT_SQL)}


def _build() -> Counter:
    return asyncio.run(demo_vendors.build(demo.demo_password()))


def _login(api, email: str) -> None:
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": email, "password": demo.demo_password()})
    assert r.status_code == 200, r.text


def _vid(no: int) -> str:
    return str(
        query("select id from users where email = $1", demo_vendors.vendor_mail(no))[0]["id"]
    )


def test_build_follows_spec_is_idempotent_and_undo_removes_only_mine(api):
    signup(api, "other@mitjip.test")  # 목업이 아닌 고객 · 관리자: 되돌리기 뒤에도 남는다
    make_admin(api)
    got = _build()
    done = sum(v.get("history", {}).get("done", 0) for v in SPEC["vendors"])
    assert got["vendors"] == len(SPEC["vendors"]) == 48 and got["customers"] == 5
    assert got["jobs"] == done and got["holds"] > 0

    # 상태별 수: 승인 40(그중 멈춤 2) · 심사 기다림 4(보완해서 다시 보냄 · 거절 뒤 다시 신청 포함) · 보완 2 · 거절 2
    rows = query(
        "select v.status, v.suspended_at is not null sus, count(*) n from vendors v"
        " join users u on u.id = v.user_id where u.email like 'v4m-%' group by 1, 2"
    )
    by = {(r["status"], r["sus"]): r["n"] for r in rows}
    assert by == {
        ("approved", False): 38, ("approved", True): 2, ("pending", False): 4,
        ("needs_info", False): 2, ("rejected", False): 2,
    }  # fmt: skip
    # 공정별: 도배만 · 목공만 · 둘 다(명세 그대로), 지역은 업체마다 1~5곳
    trades = query(
        "select string_agg(t.trade, ',' order by t.trade) ts from vendor_trades t"
        " join users u on u.id = t.vendor_id where u.email like 'v4m-%' group by t.vendor_id"
    )
    assert Counter(r["ts"] for r in trades) == Counter(
        ",".join(sorted(v["trades"])) for v in SPEC["vendors"]
    )
    areas = query(
        "select count(*) n from vendor_areas a join users u on u.id = a.vendor_id"
        " where u.email like 'v4m-%' group by a.vendor_id"
    )
    assert all(1 <= r["n"] <= 5 for r in areas)

    # 업체마다 끝낸 공사 · 리뷰 수 = 명세(별점 수 합), 별점 평균이 업체마다 갈린다
    per = query(
        "select u.email, (select count(*) from deals d where d.vendor_id = u.id and d.status = 'done') done,"
        " (select count(*) from reviews r where r.vendor_id = u.id) reviews,"
        " (select avg(r.rating) from reviews r where r.vendor_id = u.id) avg"
        " from users u where u.email like 'v4m-__@mitjip.test'"
    )
    for r in per:
        v = VENDORS[int(r["email"][4:6])]
        h = v.get("history", {"done": 0, "stars": [0]})
        assert (r["done"], r["reviews"]) == (h["done"], sum(h["stars"])), r["email"]
    avgs = sorted(float(r["avg"]) for r in per if r["avg"] is not None)
    assert avgs[0] < 3.6 and avgs[-1] > 4.85 and max(r["reviews"] for r in per) >= 200

    # 꽉 찬 업체(비단벽지 v4m-16): 앞으로 4주 실측 반나절이 하나도 없고, 달력이 없는 업체는 넉넉하다
    async def free(no: int) -> int:
        try:
            async with SessionLocal() as s:
                user = await auth_repo.user_by_email(s, demo_vendors.vendor_mail(no))
                today = today_seoul()
                got = await visit_service.open_halves_for(
                    s, user.id, today + timedelta(days=1), today + timedelta(days=28)
                )
                return sum(len(x) for x in got.values())
        finally:
            await engine.dispose()

    assert VENDORS[16]["calendar"] == "full" and asyncio.run(free(16)) == 0
    assert VENDORS[7]["calendar"] is None and asyncio.run(free(7)) == 28 * 2
    # 반쯤 찬 업체(온새벽지 v4m-01, 반나절에 2칸): 반나절의 반쯤은 칸이 다 차서 닫힌다
    assert VENDORS[1]["calendar"] == "half" and 15 <= asyncio.run(free(1)) <= 41

    # 두 번 돌려도 같다
    before = _counts()
    again = _build()
    assert sum(again.values()) == 0 and _counts() == before

    # 되돌리기: 내 계정 · 행 · 저장소 파일만 지운다
    keys = [
        r["storage_key"]
        for r in query(
            "select f.storage_key from files f join users u on u.id = f.owner_id"
            " where u.email like 'v4m-%'"
        )
    ]
    assert keys and all((Path(settings.files_dir) / k).exists() for k in keys)
    gone = asyncio.run(demo_vendors.undo())
    assert gone["users"] == before["users"] - 2 and gone["files"] == len(keys)
    after = _counts()
    assert after["users"] == 2 and all(
        after[t] == 0 for t in TABLES if t not in ("users", "notifications")
    )
    assert not any((Path(settings.files_dir) / k).exists() for k in keys)

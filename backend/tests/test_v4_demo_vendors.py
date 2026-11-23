"""v4 목업 업체 심기(app/demo_vendors.py, 명세 demo_assets/mock_vendors.json). LLM 없이(유료 호출 0회).

- 명세 수 그대로: 업체 상태별 · 공정별 · 지역, 업체마다 끝낸 공사 · 리뷰 수, 꽉 찬 업체의 실측 달력.
- 두 번 돌려도 같다(멱등), 되돌리기는 v4m-* 계정과 거기 딸린 행 · 파일만 지운다.
- 다른 구 샘플 고객 다섯이 받는 추천 3곳(recommend_vendors, 계산 엔진 점수)이 서로 다르고 점수가 갈린다.
- 고객 · 업체 · 관리자 화면 API가 지난 공사 · 달력 행으로 500을 내지 않는다."""

import asyncio
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app import demo, demo_vendors
from app.assistant.runtime import RefTable
from app.assistant.tools import ToolCtx
from app.assistant.tools.customer import RecommendIn, recommend_vendors
from app.auth import repository as auth_repo
from app.calc import vendor_pick
from app.config import settings
from app.db import SessionLocal, engine
from app.project.models import Project
from app.shared.clock import now_utc, today_seoul
from app.visit import service as visit_service
from tests.conftest import query
from tests.helpers import PASSWORD, make_admin, signup

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


async def _picks(email: str) -> tuple[list[str], list[float], list[dict]]:
    """샘플 고객 한 명의 추천(비서 도구 그대로)과 같은 후보의 계산 엔진 점수"""
    async with SessionLocal() as s:
        user = await auth_repo.user_by_email(s, email)
        pid = await s.scalar(select(Project.id).where(Project.owner_id == user.id))
        lst = await visit_service.vendors_for(s, user, pid, "dobae")
    tc = ToolCtx(
        user=user,
        surface="customer",
        turn_id=uuid.uuid4(),
        chat_id=uuid.uuid4(),
        project_id=pid,
        visit_id=None,
        today=today_seoul(),
        now=now_utc(),
        refs=RefTable(uuid.uuid4()),
        mode="free",
    )
    out = await recommend_vendors(tc, RecommendIn(trade="dobae"))
    cands = [
        vendor_pick.Candidate(
            vendor_id=str(c.vendor_id),
            name=c.name,
            local=True,
            estimate_total=c.estimate_total,
            vs_standard_pct=None if c.vs_standard_pct is None else int(c.vs_standard_pct),
            rating=None if c.rating is None else float(c.rating),
            review_count=c.review_count or 0,
            done_count=c.done_count or 0,
            instant=bool(c.instant_badge),
        )
        for c in lst.local
        if c.state == "ok"
    ]
    ranked = vendor_pick.pick(cands, n=len(cands))
    return [p["name"] for p in out.data["picks"]], [p.score for p in ranked], out.data["picks"]


def test_sample_customers_get_different_picks_and_screens_work(api):
    make_admin(api)
    _build()
    got = {}
    for c in SPEC["customers"]:
        try:
            got[c["sgg"]] = asyncio.run(_picks(demo_vendors.mail(c["local"])))
        finally:
            asyncio.run(engine.dispose())
    tops = {sgg: names for sgg, (names, _, _) in got.items()}
    assert all(len(names) == 3 for names in tops.values()), tops
    assert len({tuple(n) for n in tops.values()}) == 5  # 구마다 다른 세 곳
    assert len({n[0] for n in tops.values()}) >= 4  # 1위도 구마다 거의 다르다
    for sgg, (names, scores, picks) in got.items():
        assert len(set(scores[:3])) == 3, sgg  # 세 곳의 점수가 갈린다
        assert all(p["estimate_won"] > 0 for p in picks)
    every = [x for _, scores, _ in got.values() for x in scores]
    assert max(every) - min(every) >= 0.3  # 후보 점수가 넓게 퍼진다
    # 합지 집(송파 c02): 합지를 빼는 실크 전문 업체는 고르지 않는다
    silk_only = {
        v["biz"]
        for v in SPEC["vendors"]
        if v.get("dobae_prices") and ["paper_hapji", "excluded"] in v["dobae_prices"]
    }
    assert not silk_only & set(tops["송파구"])

    # 고객 화면: 업체 목록(가견적 없음 업체 포함) · 업체 자세히(별점 · 답 시간 · 개업 · 사진 · 자주 묻는 답) · 리뷰
    _login(api, demo_vendors.mail("c03"))
    pid = str(query(
        "select p.id from projects p join users u on u.id = p.owner_id where u.email = $1",
        demo_vendors.mail("c03"),
    )[0]["id"])  # fmt: skip
    r = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    states = Counter(c["state"] for c in r.json()["local"])
    assert states["ok"] >= 3 and states["no_estimate"] >= 1
    top = next(c for c in r.json()["local"] if c["name"] == tops["강서구"][0])
    r = api.get(f"/projects/{pid}/vendors/{top['vendor_id']}", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rating"]["count"] > 0 and d["reply_hours"] and d["years_open"] is not None
    assert d["profile"]["faqs"] and d["profile"]["portfolio"] and d["estimate_v3"]
    r = api.get(f"/projects/{pid}/vendors/{top['vendor_id']}/reviews")
    assert r.status_code == 200, r.text
    assert r.json()["items"] and any(x["reply"] for x in r.json()["items"])

    # 업체 화면: 꽉 찬 업체 · 지난 공사가 많은 업체로 로그인해 작업함 · 달력 · 리뷰 · 지난 공사
    span = {"from": str(today_seoul()), "to": str(today_seoul() + timedelta(days=42))}
    for no in (16, 7):
        _login(api, demo_vendors.vendor_mail(no))
        for path in ("/vendor/visits/summary", "/vendor/reviews", "/vendor/profile"):
            r = api.get(path)
            assert r.status_code == 200, (no, path, r.text)
        r = api.get("/vendor/schedule", params=span)
        assert r.status_code == 200, r.text
    deal = query(
        "select d.id from deals d join users u on u.id = d.vendor_id where u.email = $1 limit 1",
        demo_vendors.vendor_mail(7),
    )[0]["id"]
    assert api.get(f"/vendor/jobs/{deal}").status_code == 200

    # 관리자 화면: 심사 기다림 4(다시 보냄 · 다시 신청 표시) · 보완 2 · 멈춘 업체
    admin = query("select email from users where role = 'admin'")[0]["email"]
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": admin, "password": PASSWORD})
    assert r.status_code == 200, r.text
    pend = {
        x["biz_name"]: x for x in api.get("/admin/vendors", params={"status": "pending"}).json()
    }
    assert {"새봄도배", "다정벽지", "단비도배인테리어", "참좋은도배"} <= set(pend)
    assert pend["단비도배인테리어"]["resubmitted"] and pend["참좋은도배"]["resubmitted"]
    assert len(api.get("/admin/vendors", params={"status": "needs_info"}).json()) == 2
    r = api.get(f"/admin/vendors/{_vid(40)}")
    assert r.status_code == 200 and r.json()["suspend_scope"] == "all"

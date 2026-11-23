"""v4 목업 업체 심기. 명세는 demo_assets/mock_vendors.json: 업체 48곳(승인 38 · 승인 뒤 멈춤 2 · 심사 단계 8),
업체마다 지난 공사 · 리뷰 · 실측 달력, 다른 구 샘플 고객 5명. 로컬 개발 · 시험(APP_ENV local · test)에서만 돈다.

  돌리기:   uv run python -m app.demo_vendors          (DATABASE_URL · FILES_DIR은 그 DB를 쓰는 API와 같게)
  되돌리기: uv run python -m app.demo_vendors --undo   (v4m-*@mitjip.test 계정과 거기 딸린 행 · 파일만 지운다)
  계정: 업체 v4m-01~48 · 샘플 고객 v4m-c01~c05 · 지난 공사 고객 v4m-h001~h600(기록용) · 관리자가 없을 때만 v4m-admin.
  비밀번호는 app/demo.py의 demo_password()다. 화면 · 로그에 찍지 않는다.

넣는 법
- 업체: 화면이 부르는 service(가입 신청 → 관리자 결정 → 업체 정보 · 시공 사진 · 단가 확인 · 외부 리뷰 링크, 보완해서 다시
  보냄 · 거절 뒤 다시 신청, 관리자 멈춤)를 그 업체가 들어온 날로 옮긴 시계로 부른다(app/demo.py의 _at · _fill_now).
- 지난 공사(별점 · 끝낸 공사 · 답 시간): 공사 → 실측 요청(업체 확정) · 기간 답 → 견적서 → 업체 확정(끝) → 리뷰 · 답글을
  지난 시각으로 바로 넣는다. 알림 · 기한 일(jobs)을 만들지 않아 worker의 먼저 말 걸기(LLM)가 이 행을 보지 않는다.
  견적서 공급가 · 부가세는 계산 엔진(calc.common.from_entered), 공사 날은 calc.schedule.workdays다.
- 실측 달력(calendar full · half): 앞으로 6주 반나절에 확정한 실측 칸(visit_holds)을 넣는다. 견적서 기한은 비운다.
- 샘플 고객: 다른 구 · 다른 집 기본 정보만. 공사 · 표준견적서는 20일 전 시각이다(담기 없음 알림 기간 밖).
다시 돌리면: 있는 계정은 빠진 단계만 채우고, 지난 공사 · 달력은 모자란 만큼만 더한다(같은 날 다시 돌리면 그대로).
"""

import asyncio
import io
import json
import random
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, event, func, select, text
from sqlalchemy.orm import Session

from app.auth import repository as auth_repo
from app.auth import service as auth_service
from app.auth.models import User
from app.calc import deadline
from app.calc.common import from_entered
from app.calc.schedule import workdays
from app.config import settings
from app.db import SessionLocal, engine
from app.demo import (
    DEMO_ENVS,
    PRICE_PDF,
    _at,
    _fill_now,
    _fresh_redis,
    _kst,
    _put,
    _upload,
    demo_password,
)
from app.files import service as files_service
from app.files.models import File
from app.notify import service as notify_service
from app.project import service as project_service
from app.project.models import Project, ProjectTrade
from app.project.schemas import HomeInfoIn
from app.quote import service as quote_service
from app.quote.models import VendorQuote
from app.refprice.holidays import days_off
from app.report import service as report_service
from app.report.models import AdminAction
from app.review import service as review_service
from app.review.models import TAGS, Review, ReviewReply
from app.schedule.models import Deal
from app.seed import LICENSE
from app.shared.clock import SEOUL, now_utc
from app.shared.ids import uuid7
from app.shared.regions import region_label
from app.vendor import repository as vendor_repo
from app.vendor import service as vendor_service
from app.vendor.models import Vendor, VendorPortfolio
from app.vendor.schemas import (
    AreaIn,
    ConfirmPricesIn,
    FaqIn,
    PortfolioIn,
    PriceFileIn,
    PriceLineIn,
    PriceLineV3In,
    PriceSetIn,
    ProfileIn,
    ReapplyIn,
    ResubmitIn,
    ReviewIn,
    ReviewLinkIn,
    ReviewLinksIn,
    VendorSignupIn,
)
from app.visit.models import Visit, VisitHold, VisitWindow

SPEC = Path(__file__).parent / "demo_assets" / "mock_vendors.json"
MINE = "v4m-%@mitjip.test"  # 이 파일이 만든 계정(되돌리기가 이것만 지운다)
POOL = 600  # 지난 공사 · 실측 달력 고객 수
CAL_DAYS = 42  # 실측 달력: 앞으로 6주
CAL_FULL_DAYS = 28  # 꽉 찬 업체: 4주는 칸을 모두 채우고 그 뒤 2주는 반쯤
# 지난 공사 집(공급 ㎡): 명세 history.quote_won의 순서와 같다
HOMES = tuple(Decimal(x) for x in ("59.9", "84.9", "105.8", "134.0"))
HOME_WEIGHTS = (25, 40, 25, 10)
WORK_DAYS = {"dobae": (2, 2, 3, 3), "mokgong": (1, 1, 2, 2)}  # 집 크기마다 공사 일수
MOK_ITEMS = (["molding", "base"], ["door"], ["molding"], ["molding", "base", "door"])
IP_NET = "198.51.100."  # 문서용 주소(TEST-NET-2): 가입 요청 한도를 업체마다 따로 센다
# 명세 상태 → 관리자 결정(보완해서 다시 보냄 · 거절 뒤 다시 신청은 결정 뒤 업체가 한 번 더 낸다)
DECIDE = {
    "approved": "approve",
    "suspended": "approve",
    "needs_info": "needs_info",
    "rejected": "reject",
    "resubmitted": "needs_info",
    "reapplied": "reject",
}
WORKING = ("approved", "suspended")  # 업체 정보 · 지난 공사가 있는 상태


def mail(local: str) -> str:
    return f"v4m-{local}@mitjip.test"


def vendor_mail(no: int) -> str:
    return mail(f"{no:02d}")


def load_spec(path: Path = SPEC) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _phone(no: int) -> str:
    return f"0100004{no:04d}"  # 시험용 번호(실제로 없는 010-0004-xxxx)


def _biz_no(no: int) -> str:
    return f"9990004{no:03d}"  # 시험용 사업자번호(실제로 없는 10자리)


def _area(text: str) -> AreaIn:
    sido, sgg = text.split("/", 1)
    return AreaIn(sido=sido, sgg=sgg)


def _when(now: datetime, days_ago: int, hh: int, mm: int = 0) -> datetime:
    """오늘(서울)에서 days_ago일 전 hh:mm. 지금보다 뒤면 지금 30분 전"""
    day = now.astimezone(SEOUL).date() - timedelta(days=max(days_ago, 0))
    return min(_kst(day, hh, mm), now - timedelta(minutes=30))


def _room_jpeg(seed: int, size: tuple[int, int] = (1080, 810)) -> bytes:
    """시연용 방 그림(벽지 무늬 · 창 · 몰딩 · 걸레받이 · 나무 바닥). 실제 집 사진이 아니다"""
    from PIL import Image, ImageDraw

    rnd = random.Random(seed)
    w, h = size
    wall = rnd.choice(((238, 234, 226), (226, 232, 236), (240, 236, 228), (232, 228, 236),
                       (228, 236, 230), (244, 240, 232)))  # fmt: skip
    img = Image.new("RGB", size, wall)
    d = ImageDraw.Draw(img)
    top, floor_y = int(h * 0.07), int(h * 0.7)
    line = tuple(c - 12 for c in wall)
    pattern = rnd.choice(("stripe", "dot", "grid", "plain"))
    if pattern == "stripe":
        for x in range(0, w, rnd.randint(28, 60)):
            d.line([(x, top), (x, floor_y)], fill=line, width=3)
    elif pattern == "dot":
        for y in range(top + 20, floor_y, 46):
            for x in range((y // 46) % 2 * 23, w, 46):
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=line)
    elif pattern == "grid":
        for x in range(0, w, 90):
            d.line([(x, top), (x, floor_y)], fill=line, width=1)
        for y in range(top, floor_y, 90):
            d.line([(0, y), (w, y)], fill=line, width=1)
    d.rectangle([0, 0, w, top], fill=tuple(min(c + 8, 255) for c in wall))  # 천장
    d.rectangle([0, top, w, top + 12], fill=(250, 250, 247))  # 몰딩
    wx, wy, ww, wh = rnd.randint(w // 12, w // 2), int(h * 0.17), int(w * 0.3), int(h * 0.33)
    d.rectangle([wx, wy, wx + ww, wy + wh], fill=(252, 252, 250))
    d.rectangle([wx + 14, wy + 14, wx + ww - 14, wy + wh - 14], fill=(198, 222, 238))
    d.line([(wx + ww // 2, wy + 14), (wx + ww // 2, wy + wh - 14)], fill=(252, 252, 250), width=8)
    wood = rnd.choice(((196, 160, 118), (172, 134, 98), (214, 190, 156), (152, 122, 94)))
    d.rectangle([0, floor_y, w, h], fill=wood)
    for x in range(-200, w + 200, 140):
        d.line([(x, floor_y), (x - 90, h)], fill=tuple(c - 16 for c in wood), width=2)
    d.rectangle([0, floor_y - 16, w, floor_y], fill=(248, 248, 245))  # 걸레받이
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


# ---- 관리자 · 지난 공사 고객 ----


async def _admin(s, password: str) -> User:
    """업체 결정 · 멈춤을 남길 관리자: v3 시연 관리자 → 가장 먼저 만든 관리자 → 없으면 v4m-admin을 만든다."""
    u = await auth_repo.user_by_email(s, "v3-admin@mitjip.test")
    if u is not None and u.role == "admin":
        return u
    u = await s.scalar(select(User).where(User.role == "admin").order_by(User.created_at).limit(1))
    if u is None:
        u = await auth_service.create_user(
            s, email=mail("admin"), name="믿집 관리자", password=password, role="admin"
        )
        await s.commit()
    return u


def _name(spec: dict, i: int) -> str:
    fam, given = spec["names"]["family"], spec["names"]["given"]
    return fam[i % len(fam)] + given[(i // len(fam) + 3 * i) % len(given)]


async def _pool(s, spec: dict, password: str, now: datetime) -> list[User]:
    """지난 공사 · 달력 고객 h001~h600(기록용, 리뷰 이름은 '김○○'로 보인다). 비밀번호 해시는 첫 계정 것을 같이 쓴다."""
    emails = [mail(f"h{i + 1:03d}") for i in range(POOL)]
    have = {u.email: u for u in (await s.scalars(select(User).where(User.email.in_(emails))))}
    if len(have) < POOL:
        if emails[0] not in have:
            first = await auth_service.create_user(
                s, email=emails[0], name=_name(spec, 0), password=password, role="customer"
            )
            first.created_at = first.updated_at = now - timedelta(days=500)
            await s.commit()
            have[emails[0]] = first
        hashed = have[emails[0]].password_hash
        rows = [
            User(
                id=uuid7(),
                email=e,
                name=_name(spec, i),
                password_hash=hashed,
                role="customer",
                created_at=now - timedelta(days=500) + timedelta(hours=i),
                updated_at=now - timedelta(days=500) + timedelta(hours=i),
            )
            for i, e in enumerate(emails)
            if e not in have
        ]
        s.add_all(rows)
        await s.commit()
        have |= {u.email: u for u in rows}
    return [have[e] for e in emails]


# ---- 업체: 가입 → 결정 → 정보 · 사진 · 단가 · 링크 → 멈춤 ----


async def _signup(s, v: dict, password: str, at: datetime) -> User:
    data = VendorSignupIn(
        biz_name=v["biz"],
        owner_name=v["owner"],
        phone=_phone(v["no"]),
        trades=v["trades"],
        areas=[_area(a) for a in v["areas"]],
        name=v["owner"],
        email=vendor_mail(v["no"]),
        password=password,
        biz_no=_biz_no(v["no"]),
    )
    lic = _upload("사업자등록증.pdf", LICENSE, "application/pdf")
    with _at(at):
        user, _ = await vendor_service.signup(s, data, lic, f"{IP_NET}{v['no']}")
        if v.get("review_links"):
            links = [ReviewLinkIn(label=a, url=b) for a, b in v["review_links"]]
            await vendor_service.save_review_links(s, user, ReviewLinksIn(links=links))
    return user


async def _vendor(s, v: dict, password: str, admin: User, now: datetime) -> tuple[User, bool]:
    """업체 한 곳. 돌려주는 값: (회원, 이번에 바꾼 것이 있는지). 있는 업체는 빠진 단계만 한다."""
    joined = v["joined_days_ago"]
    user = await auth_repo.user_by_email(s, vendor_mail(v["no"]))
    touched = user is None
    if user is None:
        user = await _signup(s, v, password, _when(now, joined, 10))
    acts = {r.action for r, _ in await vendor_repo.reviews_of(s, user.id)}
    state = v["state"]
    want = DECIDE.get(state)
    if want and want not in acts:
        at = _when(now, joined - (2 if state == "reapplied" else 1), 11)
        d = v.get("decision") or {}
        opened = date.fromisoformat(v["opened_on"]) if want == "approve" else None
        data = ReviewIn(action=want, code=d.get("code"), note=d.get("note"), opened_on=opened)
        with _at(at):
            await vendor_service.review(s, admin, user.id, data, at.astimezone(SEOUL).date())
        touched = True
    if state == "resubmitted" and "resubmit" not in acts:
        with _at(_when(now, joined - 3, 9, 30)):
            await vendor_service.resubmit(s, user, ResubmitIn(**v["fix"]))
        touched = True
    if state == "reapplied" and "reapply" not in acts:
        fix = v["fix"]
        data = ReapplyIn(
            biz_name=fix.get("biz_name", v["biz"]),
            owner_name=fix.get("owner_name", v["owner"]),
            phone=_phone(v["no"]),
            trades=v["trades"],
            areas=[_area(a) for a in fix.get("areas", v["areas"])],
        )
        with _at(_when(now, joined - 7, 9, 30)):
            await vendor_service.reapply(s, user, data)
        touched = True
    if state in WORKING:
        touched |= await _profile(s, v, user, admin, now)
    row = await s.get(Vendor, user.id, populate_existing=True)
    if state == "suspended" and row.suspended_at is None:
        sp = v["suspend"]
        with _at(_when(now, 9, 14)):
            await report_service.suspend_vendor(s, admin, user.id, sp["scope"], sp["note"])
        touched = True
    return user, touched


def _profile_in(v: dict, updated_at) -> ProfileIn:
    first = v["areas"][0].split("/", 1)
    return ProfileIn(
        updated_at=updated_at,
        phone=_phone(v["no"]),
        address=f"{region_label(*first)} (시연용 주소)",
        trades=v["trades"],
        areas=[_area(a) for a in v["areas"]],
        contact_method=v["contact"],
        contact_url=v["contact_url"],
        call_start=time.fromisoformat(v["call"][0]),
        call_end=time.fromisoformat(v["call"][1]),
        visit_fee=v["visit_fee"],
        visit_fee_refund=v["visit_fee_refund"],
        tax_kind=v["tax_kind"],
        instant_default=v["instant"],
        visit_capacity=v["capacity"],
        intro=v["intro"],
        interior_license=v["interior_license"],
        insurance=v["insurance"],
        faqs=[FaqIn(key=k, answer=a) for k, a in v["faqs"].items()],
    )


def _v3_line(ln: list) -> PriceLineV3In:
    key, mode, *rest = ln
    return PriceLineV3In(
        key=key,
        mode=mode,
        unit_price=rest[0] if mode == "price" else None,
        included_in=rest[0] if mode == "included" else None,
    )


async def _profile(s, v: dict, user: User, admin: User, now: datetime) -> bool:
    """승인 업체의 정보 · 시공 사진 · 단가 확인 · 외부 리뷰 링크 확인(관리자). 빠진 것만. 바꿨으면 True"""
    at = _when(now, v["joined_days_ago"] - 1, 15)
    day = at.astimezone(SEOUL).date()
    changed = False
    prof = await vendor_service.get_profile(s, user)
    if prof.updated_at is None:
        with _at(at):
            await vendor_service.save_profile(s, user, _profile_in(v, None), day)
        changed = True
    if v["portfolio"] and not prof.portfolio:
        for i, (title, space, m2, paper) in enumerate(v["portfolio"]):
            with _at(at + timedelta(minutes=5 + i)):
                photo = await asyncio.to_thread(_room_jpeg, v["no"] * 31 + i)
                fid = await _put(s, user, "portfolio", photo, "image/jpeg", f"시공-{i + 1}.jpg")
                case = PortfolioIn(
                    title=title,
                    space=space,
                    area_m2=Decimal(m2),
                    area_basis="supply",
                    paper=paper,
                    taken_on=day - timedelta(days=35 * (i + 1)),
                    file_id=fid,
                )
                await vendor_service.add_portfolio(s, user, case, day)
        changed = True
    if v["dobae_prices"]:
        sets = await vendor_repo.price_sets(s, [user.id], "dobae", ("confirmed",))
        if not any(x.rows_ver == vendor_service.V3 for x in sets):
            data = ConfirmPricesIn(base_version=0, lines=[_v3_line(x) for x in v["dobae_prices"]])
            with _at(at + timedelta(minutes=30)):
                await vendor_service.confirm_prices_v3(s, user, "dobae", data)
            changed = True
    if v["mokgong_prices"] and not await vendor_repo.price_sets(
        s, [user.id], "mokgong", ("confirmed",)
    ):
        with _at(at + timedelta(minutes=40)):
            if not await vendor_repo.price_files(s, [user.id], "mokgong"):
                fid = await _put(
                    s, user, "price_doc", PRICE_PDF, "application/pdf", "목공단가표.pdf"
                )
                await vendor_service.add_price_file(
                    s, user, PriceFileIn(file_id=fid, trade="mokgong")
                )
            lines = [PriceLineIn(key=k, unit_price=p) for k, _, p in v["mokgong_prices"]]
            await vendor_service.save_prices(s, user, "mokgong", PriceSetIn(lines=lines))
            await vendor_service.confirm_prices(s, user, "mokgong")
        changed = True
    links = await vendor_service.review_links(s, user)
    for link in links:  # 승인 업체의 외부 리뷰 링크는 관리자가 열어 보고 '보여요'로 확인했다
        if link.status == "checking":
            await vendor_service.set_review_link_status(
                s, user.id, link.sort, "shown", by=admin.id, at=at + timedelta(hours=2)
            )
            changed = True
    await s.commit()
    return changed


# ---- 지난 공사(별점 · 끝낸 공사 · 답 시간) ----


async def _seq(s, name: str, n: int) -> list[int]:
    """번호표(project_code_seq · vendor_quote_code_seq)에서 n개"""
    if n <= 0:
        return []
    q = text(f"select nextval('{name}') from generate_series(1, :n)")  # 이름은 이 파일의 상수
    return [int(x) for x in (await s.scalars(q, {"n": n}))]


def _money(amount: int, tax_kind: str):
    """업체가 적은 낼 금액(부가세 포함) → 공급가 · 부가세 · 합계(계산 엔진). 간이과세는 부가세를 따로 붙이지 않는다
    (quote.service와 같은 규칙, L02). 돌려주는 값: (부가세 방식, Money)"""
    if tax_kind == "exempt":
        return "exempt", from_entered(amount, "exempt")
    if tax_kind == "simplified":
        return "included", from_entered(amount, "included", rate=Decimal(0))
    return "included", from_entered(amount, "included")


def _plan_jobs(v: dict, now: datetime, off: frozenset[date]) -> list[dict]:
    """지난 공사 계획(업체마다 같은 값): 공사 시작일 · 공정 · 집 · 별점. j가 작을수록 오래된 공사"""
    h = v["history"]
    n = h["done"]
    rnd = random.Random(f"v4m-{v['no']}-reviews")
    stars = [5 - i for i, k in enumerate(h["stars"]) for _ in range(k)]
    rated = sorted(rnd.sample(range(n), len(stars)))
    rnd.shuffle(stars)
    rating = dict(zip(rated, stars, strict=True))
    today = now.astimezone(SEOUL).date()
    last = today - timedelta(days=14)
    # 요청이 업체가 들어온 뒤에 오게: 공사 시작은 들어온 날 + 24일부터(요청 = 시작 - 22일)
    first = max(today - timedelta(days=v["joined_days_ago"] - 24), today - timedelta(days=600))
    if first >= last:
        first = last - timedelta(days=30)
    span = (last - first).days
    areas = [a.split("/", 1) for a in v["areas"]]
    econ = h["economy_share"]  # 합지 공사 몫(합지를 빼는 업체는 0)
    out = []
    for j in range(n):
        rng = random.Random(f"v4m-{v['no']}-{j}")
        trade = "mokgong" if rng.random() < h["mok_share"] else "dobae"
        k = rng.choices(range(len(HOMES)), weights=HOME_WEIGHTS)[0]
        grade = None
        if trade == "dobae":
            grade = "economy" if rng.random() < econ else "basic"
        start = workdays(first + timedelta(days=span * (2 * j + 1) // (2 * n)), 1, off)[0]
        out.append(
            {
                "j": j,
                "rng": rng,
                "trade": trade,
                "home": k,
                "grade": grade,
                "area": areas[j % len(areas)],
                "start": start,
                "days": workdays(start, WORK_DAYS[trade][k], off),
                "rating": rating.get(j),
            }
        )
    return out


async def _history(s, spec: dict, v: dict, vendor: User, pool: list[User], now, off) -> int:
    """지난 공사를 명세 수(history.done)만큼 맞춘다. 이번에 더한 공사 수"""
    h = v["history"]
    if h["done"] <= 0:
        return 0
    have = await s.scalar(
        select(func.count())
        .select_from(Deal)
        .join(Project, Project.id == Deal.project_id)
        .join(User, User.id == Project.owner_id)
        .where(Deal.vendor_id == vendor.id, Deal.status == "done", User.email.like(mail("h%")))
    )
    jobs = _plan_jobs(v, now, off)[have:]
    if not jobs:
        return 0
    codes = await _seq(s, "project_code_seq", len(jobs))
    qcodes = await _seq(s, "vendor_quote_code_seq", len(jobs))
    lo, hi = h["reply_hours"]
    texts, replies = spec["reviews"], spec["replies"]
    rows: list = []
    for x, no, qno in zip(jobs, codes, qcodes, strict=True):
        rng, trade, start, days = x["rng"], x["trade"], x["start"], x["days"]
        sido, sgg = x["area"]
        cust = pool[(v["no"] * 37 + x["j"]) % POOL]
        p_at = _kst(start - timedelta(days=24), 20, rng.randint(0, 59))
        asked = _kst(start - timedelta(days=22), 21, rng.randint(0, 59))
        answered = asked + timedelta(minutes=rng.randint(lo * 60, hi * 60))
        booked = workdays(start - timedelta(days=16), 1, off)[0]
        half = "am" if rng.random() < 0.55 else "pm"
        sent = _kst(booked + timedelta(days=1), 10, rng.randint(0, 50))
        dealt = _kst(booked + timedelta(days=3), 14, rng.randint(0, 50))
        pid, vid, qid, did = uuid7(), uuid7(), uuid7(), uuid7()
        rows += [
            Project(
                id=pid,
                owner_id=cust.id,
                sido=sido,
                sgg=sgg,
                house_type="apt",
                built_year=rng.randint(1988, 2022),
                area_m2=HOMES[x["home"]],
                area_basis="supply",
                balcony_ext=False,
                start_kind="date",
                start_date=start,
                occupied=rng.random() < 0.25,
                code=f"MJ-{p_at:%y%m}-{no:04d}",
                rev=1,
                locked_at=asked,
                created_at=p_at,
                emd=rng.choice(spec["emd"][sgg]) if sgg in spec["emd"] else None,
                source="member",
            ),
            ProjectTrade(
                project_id=pid,
                trade=trade,
                items=list(rng.choice(MOK_ITEMS)) if trade == "mokgong" else [],
                grade=x["grade"],
            ),
            Visit(
                id=vid,
                project_id=pid,
                trade=trade,
                vendor_id=vendor.id,
                vendor_name=v["biz"],
                slot=1,
                status="chosen",
                attempt=1,
                wish_start=booked - timedelta(days=5),
                wish_end=booked + timedelta(days=9),
                work_wish_on=start,
                reply_due_at=asked + timedelta(hours=48),
                booked_day=booked,
                booked_half=half,
                quote_due_at=deadline.quote_due(booked),
                vendor_seen_at=max(asked + timedelta(minutes=5), answered - timedelta(minutes=10)),
                visited_at=_kst(booked, 11 if half == "am" else 16, 30),
                quote_ver=1,
                grade=x["grade"],
                created_at=asked,
            ),
            VisitWindow(
                visit_id=vid,
                start_date=booked - timedelta(days=2),
                end_date=booked + timedelta(days=5),
                instant=v["instant"],
                answered_at=answered,
                pick_due_at=answered + timedelta(days=7),
            ),
        ]
        won = h["quote_won"]["mokgong" if trade == "mokgong" else x["grade"]][x["home"]]
        mode, money = _money(won, v["tax_kind"])
        rows.append(
            VendorQuote(
                id=qid,
                visit_id=vid,
                code=f"Q-{sent:%y%m}-{qno:04d}",
                version=1,
                sent_at=sent,
                measured_on=booked,
                entered_amount=won,
                vat_mode=mode,
                supply=money.supply,
                vat=money.vat,
                total=money.total,
                days=len(days),
                valid_until=booked + timedelta(days=14),
                created_at=sent - timedelta(hours=1),
                updated_at=sent,
                incl_removal=trade == "dobae",
                incl_waste=rng.random() < 0.7,
                warranty_months=12,
            )
        )
        done_at = _kst(days[-1], 18, rng.randint(0, 40))
        rows.append(
            Deal(
                id=did,
                project_id=pid,
                trade=trade,
                vendor_id=vendor.id,
                vendor_name=v["biz"],
                visit_id=vid,
                quote_id=qid,
                status="done",
                dates_due_at=dealt + timedelta(days=2),
                start_date=days[0],
                end_date=days[-1],
                work_days=days,
                work_done_on=days[-1],
                done_posted_at=done_at,
                created_at=dealt,
            )
        )
        if x["rating"] is not None:
            rows += _review(x, v, did, pid, vendor, cust, sgg, done_at, texts, replies)
    await _insert(s, rows)
    return len(jobs)


# 모델에 relationship이 없어 ORM이 표 순서를 모른다: FK 순서대로 표마다 넣는다
ORDER = (
    Project,
    ProjectTrade,
    Visit,
    VisitWindow,
    VendorQuote,
    Deal,
    Review,
    ReviewReply,
    VisitHold,
)


async def _insert(s, rows: list) -> None:
    for cls in ORDER:
        part = [r for r in rows if type(r) is cls]
        if part:
            s.add_all(part)
            await s.flush()
    await s.commit()


def _review(x, v, did, pid, vendor, cust, sgg, done_at, texts, replies) -> list:
    """리뷰 한 개(+ 업체 답글). 글은 명세의 글 묶음 · 그 업체 말에서 고른다(별점이 낮으면 아쉬운 글)."""
    rng, rating, trade = x["rng"], x["rating"], x["trade"]
    lines = v["history"]["lines"]
    body = None
    if rng.random() < 0.85:
        if rating >= 4 and lines and rng.random() < 0.45:
            body = rng.choice(lines)
        else:
            body = rng.choice(texts[trade][str(rating)])
    tags = sorted(rng.sample(TAGS, {5: 3, 4: 2, 3: 1}.get(rating, 0)), key=TAGS.index)
    if rating == 5 and rng.random() < 0.5:
        tags = tags[:2]
    at = done_at + timedelta(days=rng.randint(1, 5), hours=rng.randint(-6, 4))
    rid = uuid7()
    out: list = [
        Review(
            id=rid,
            deal_id=did,
            vendor_id=vendor.id,
            project_id=pid,
            author_id=cust.id,
            rating=rating,
            tags=tags,
            body=body,
            context_label=review_service.context_label(sgg, trade, x["grade"]),
            status="shown",
            created_at=at,
        )
    ]
    rate = v["history"]["reply_rate"] if rating >= 4 else min(v["history"]["reply_rate"] + 0.3, 1)
    if rng.random() < rate:
        out.append(
            ReviewReply(
                review_id=rid,
                vendor_id=vendor.id,
                body=rng.choice(replies["good" if rating >= 4 else "bad"]),
                created_at=at + timedelta(hours=rng.randint(4, 60)),
            )
        )
    return out


# ---- 실측 달력: 앞으로 6주 반나절에 확정한 실측 ----


def _cal_want(v: dict, today: date) -> list[tuple[date, str, int]]:
    """잡을 칸(날, 반나절, 칸 번호). 고른 반나절은 칸을 모두 채운다(고객 달력에서 그 반나절이 닫히게).
    full: 4주는 모든 반나절 · 그 뒤 2주는 반, half: 반나절의 반. 날 · 반나절마다 같은 값(멱등)"""
    kind, cap = v["calendar"], v["capacity"]
    out = []
    for n in range(1, CAL_DAYS + 1):
        day = today + timedelta(days=n)
        for half in ("am", "pm"):
            p = 1.0 if kind == "full" and n <= CAL_FULL_DAYS else 0.5
            if random.Random(f"v4m-{v['no']}-{day}-{half}-1").random() < p:
                out += [(day, half, seat) for seat in range(1, cap + 1)]
    return out


async def _calendar(s, v: dict, vendor: User, pool: list[User], now: datetime) -> int:
    """꽉 찬 · 반쯤 찬 업체의 실측 칸. 이미 잡힌 칸(누가 잡았든)은 건너뛴다. 이번에 잡은 칸 수"""
    if not v.get("calendar"):
        return 0
    today = now.astimezone(SEOUL).date()
    taken = {
        (d, h, seat)
        for d, h, seat in (
            await s.execute(
                select(VisitHold.day, VisitHold.half, VisitHold.seat).where(
                    VisitHold.vendor_id == vendor.id,
                    VisitHold.status == "active",
                    VisitHold.day > today,
                )
            )
        ).all()
    }
    want = [w for w in _cal_want(v, today) if w not in taken]
    if not want:
        return 0
    codes = await _seq(s, "project_code_seq", len(want))
    lo, hi = v["history"]["reply_hours"]
    rows: list = []
    for (day, half, seat), no in zip(want, codes, strict=True):
        rng = random.Random(f"v4m-{v['no']}-{day}-{half}-{seat}-visit")
        cust = pool[(v["no"] * 53 + day.toordinal() * 2 + (half == "pm") + seat * 97) % POOL]
        asked = max(
            min(_kst(day - timedelta(days=12), 20, rng.randint(0, 59)), now - timedelta(days=1)),
            now - timedelta(days=20),
        )
        answered = min(
            asked + timedelta(minutes=rng.randint(lo * 60, hi * 60)), now - timedelta(hours=3)
        )
        answered = max(answered, asked + timedelta(minutes=10))
        pid, vid = uuid7(), uuid7()
        rows += [
            Project(
                id=pid,
                owner_id=cust.id,
                sido=v["areas"][0].split("/", 1)[0],
                sgg=v["areas"][0].split("/", 1)[1],
                house_type="apt",
                built_year=rng.randint(1990, 2022),
                area_m2=HOMES[rng.choices(range(len(HOMES)), weights=HOME_WEIGHTS)[0]],
                area_basis="supply",
                balcony_ext=False,
                start_kind="date",
                start_date=day + timedelta(days=21),
                occupied=rng.random() < 0.3,
                code=f"MJ-{asked:%y%m}-{no:04d}",
                rev=1,
                locked_at=asked,
                created_at=asked - timedelta(days=2),
                source="member",
            ),
            ProjectTrade(project_id=pid, trade="dobae", items=[], grade="basic"),
            Visit(
                id=vid,
                project_id=pid,
                trade="dobae",
                vendor_id=vendor.id,
                vendor_name=v["biz"],
                slot=1,
                status="booked",
                attempt=1,
                wish_start=day - timedelta(days=4),
                wish_end=day + timedelta(days=6),
                work_wish_on=day + timedelta(days=21),
                reply_due_at=asked + timedelta(hours=48),
                booked_day=day,
                booked_half=half,
                vendor_seen_at=asked + timedelta(minutes=5),
                grade="basic",
                created_at=asked,
            ),
            VisitWindow(
                visit_id=vid,
                start_date=day - timedelta(days=2),
                end_date=day + timedelta(days=4),
                instant=v["instant"],
                answered_at=answered,
                pick_due_at=answered + timedelta(days=7),
            ),
            VisitHold(
                vendor_id=vendor.id,
                visit_id=vid,
                day=day,
                half=half,
                seat=seat,
                kind="booked",
                status="active",
                created_at=answered + timedelta(minutes=30),
            ),
        ]
    await _insert(s, rows)
    return len(want)


# ---- 샘플 고객: 다른 구 · 다른 집 기본 정보만 ----


async def _customer(s, c: dict, password: str, now: datetime) -> bool:
    email = mail(c["local"])
    if await auth_repo.user_by_email(s, email) is not None:
        return False
    at = now - timedelta(days=20)
    day = at.astimezone(SEOUL).date()
    with _at(at):
        user = await auth_service.create_user(
            s, email=email, name=c["name"], password=password, role="customer"
        )
        await s.commit()
        home = HomeInfoIn(
            sido=c["sido"],
            sgg=c["sgg"],
            area_m2=Decimal(c["area_m2"]),
            area_basis="supply",
            occupied=c["occupied"],
            grade=c["grade"],
            start_date=now.astimezone(SEOUL).date() + timedelta(days=45),
        )
        p = await project_service.create(s, user, home, day)
        await quote_service.ensure_standard(s, p)
    return True


# ---- 돌리기 · 되돌리기 ----


async def build(password: str, now: datetime | None = None, spec: dict | None = None) -> Counter:
    """명세대로 심는다(있는 것은 빠진 만큼만). 돌려주는 값: 이번에 만든 수(업체 · 공사 · 실측 칸 · 샘플 고객)"""
    if settings.app_env not in DEMO_ENVS:  # staging · production에서는 만들지 않는다
        raise SystemExit("목업 업체는 로컬 개발(APP_ENV=local · test)에서만 만들어요.")
    spec = spec or load_spec()
    now = now or now_utc()
    today = now.astimezone(SEOUL).date()
    off = days_off(today - timedelta(days=700), today + timedelta(days=CAL_DAYS + 60))
    made: Counter = Counter()
    await _fresh_redis()  # 앞선 이벤트 루프에서 연 연결을 이 루프에서 쓰지 않게
    event.listen(Session, "before_flush", _fill_now)  # 넣는 동안만: 옮긴 시계로 DB 기본 시각 채우기
    try:
        async with SessionLocal() as s:
            admin = await _admin(s, password)
            pool = await _pool(s, spec, password, now)
            users: dict[int, User] = {}
            for v in spec["vendors"]:
                user, touched = await _vendor(s, v, password, admin, now)
                users[v["no"]] = user
                made["vendors"] += touched
                if v["state"] in WORKING:
                    made["jobs"] += await _history(s, spec, v, user, pool, now, off)
                    made["holds"] += await _calendar(s, v, user, pool, now)
                if touched:  # 지난 일 알림(가입 승인 · 멈춤)은 읽음으로 둔다
                    await notify_service.mark_all_read(s, user.id)
            for c in spec["customers"]:
                made["customers"] += await _customer(s, c, password, now)
    finally:  # 한 번 돌고 끝나는 스크립트 · 시험이 이벤트 루프를 새로 만든다: 이 루프에서 연 연결을 닫는다
        event.remove(Session, "before_flush", _fill_now)
        await engine.dispose()
        await _fresh_redis()
    return made


async def undo() -> dict[str, int]:
    """이 파일이 만든 계정(v4m-*@mitjip.test)과 거기 딸린 행(업체 · 공사 · 리뷰 · 파일 행은 FK로 같이)을 지우고,
    그 계정을 가리키는 관리자 처리 기록 · 저장소 파일 내용도 지운다. 다른 계정 · 행은 건드리지 않는다
    (다른 고객이 목업 업체와 한 요청 · 확정은 남고 업체 칸만 비어요: visits · deals.vendor_id SET NULL).
    지우는 순서: ON DELETE가 없는 FK(deals.quote_id · vendor_portfolio.file_id · vendors.license_file_id)를
    가리키는 쪽부터 지운다(한 문장의 연쇄 삭제에서는 확인 순서가 앞설 수 있다)."""
    if settings.app_env not in DEMO_ENVS:
        raise SystemExit("목업 업체는 로컬 개발(APP_ENV=local · test)에서만 지워요.")
    await _fresh_redis()
    try:
        async with SessionLocal() as s:
            mine = select(User.id).where(User.email.like(MINE))
            homes = select(Project.id).where(Project.owner_id.in_(mine))
            keys = list(await s.scalars(select(File.storage_key).where(File.owner_id.in_(mine))))
            acts = await s.execute(delete(AdminAction).where(AdminAction.target_user_id.in_(mine)))
            await s.execute(delete(Deal).where(Deal.project_id.in_(homes)))
            await s.execute(delete(VendorPortfolio).where(VendorPortfolio.vendor_id.in_(mine)))
            await s.execute(delete(Project).where(Project.owner_id.in_(mine)))
            await s.execute(delete(Vendor).where(Vendor.user_id.in_(mine)))
            users = await s.execute(delete(User).where(User.email.like(MINE)))
            await s.commit()
        for key in keys:
            await files_service.remove_stored(key)
    finally:
        await engine.dispose()
        await _fresh_redis()
    return {"users": users.rowcount, "admin_actions": acts.rowcount, "files": len(keys)}


LABELS = {"vendors": "업체", "jobs": "지난 공사", "holds": "실측 칸", "customers": "샘플 고객"}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if "--undo" in argv:
        got = asyncio.run(undo())
        print(
            f"지웠어요: 계정 {got['users']} · 관리자 처리 기록 {got['admin_actions']} · 파일 {got['files']}"
        )
        return
    password = demo_password()  # 로컬 · 테스트가 아니면 여기서 멈춘다
    got = asyncio.run(build(password))
    print("넣었어요: " + " · ".join(f"{name} {got.get(k, 0)}" for k, name in LABELS.items()))


if __name__ == "__main__":
    main()

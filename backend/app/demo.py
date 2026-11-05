"""시연용 고객 흐름 데이터를 만든다. 운영(APP_ENV=production)에서는 돌지 않는다.

시연 고객 1명과 시연 업체 6곳(도배 3 · 목공 3, 승인 · 확인한 단가까지)을 만들고,
고객 흐름 단계마다 프로젝트를 하나씩 만든다. 업체 쪽 일(견적서 보내기 · 공사 날짜 내기)은 미리 해 둔다.
  업체 고르기(pick) → 실측 요청(visit_requested) → 견적서 옴(quotes_arrived)
  → 공사 날짜 옴(dates_received) → 확정 공정표(before_work)
다시 돌리면 계정은 그대로 두고 단계별 프로젝트를 한 벌 더 만든다. 시연 안내 화면(/demo)은 단계마다 가장 최근 것을 쓴다.
업체 승인자로 남길 관리자 계정이 먼저 있어야 한다.
비밀번호는 DEMO_PASSWORD에서 읽고 화면에 찍지 않는다. 이미 있는 계정의 비밀번호는 바꾸지 않는다.
돌리기: docker compose exec -T -e DEMO_PASSWORD api python -m app.demo

DEMO_AUTO=true면 worker가 몇 초마다 auto_reply로 시연 업체 일을 대신 한다(아래 '자동 응답').
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import date, time, timedelta
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, or_, select

from app.auth import repository as auth_repo
from app.auth import service as auth_service
from app.auth.models import User
from app.calc.schedule import WEEKEND, workdays
from app.config import settings
from app.db import SessionLocal, engine
from app.files import service as files_service
from app.project import service as project_service
from app.project.schemas import ProjectCreate
from app.quote.schemas import QuoteDraftIn
from app.refprice.holidays import days_off
from app.schedule import service as schedule_service
from app.schedule.models import DateProposal, DateRequest, Deal
from app.schedule.schemas import AcceptIn, ConfirmIn, DatesIn
from app.seed import LICENSE, sample_pdf
from app.shared.clock import now_utc, today_seoul
from app.shared.errors import AppError
from app.vendor import repository as vendor_repo
from app.vendor import service as vendor_service
from app.vendor.models import Vendor, VendorArea, VendorReview, VendorTrade
from app.vendor.schemas import PriceFileIn, PriceLineIn, PriceSetIn
from app.visit import service as visit_service
from app.visit.models import Visit
from app.visit.schemas import VisitCreateIn

log = logging.getLogger(__name__)

CUSTOMER = ("demo@mitjip.test", "시연 고객", "01000000000")  # 실제로 없는 번호
# 이메일 → (담당자, 상호, 대표, 사업자번호, 전화, 공정, 확인한 단가). 단가는 원 · 부가세 빼고
VENDORS = {
    "demo-dobae1@mitjip.test": (
        "김시연",
        "시연도배",
        "김시연",
        "9990000901",
        "01000000901",
        "dobae",
        {"wall": 6650, "ceiling": 6800, "paper_basic": 3400, "paper_economy": 2600},
    ),
    "demo-dobae2@mitjip.test": (
        "이시연",
        "시연벽지",
        "이시연",
        "9990000902",
        "01000000902",
        "dobae",
        {
            "wall": 7000,
            "ceiling": 7200,
            "paper_basic": 3600,
            "paper_economy": 2800,
            "primer": 600,
        },
    ),
    "demo-mok1@mitjip.test": (
        "박시연",
        "시연목공",
        "박시연",
        "9990000903",
        "01000000903",
        "mokgong",
        {
            "frame": 18000,
            "board": 12000,
            "ceiling_mat": 9000,
            "door": 90000,
            "casing": 4500,
            "door_mat": 180000,
            "molding": 3500,
            "molding_mat": 2500,
            "base": 3000,
            "base_mat": 2000,
        },
    ),
    "demo-dobae3@mitjip.test": (
        "최시연",
        "시연한지",
        "최시연",
        "9990000904",
        "01000000904",
        "dobae",
        {"wall": 6900, "ceiling": 7000, "paper_basic": 3300, "paper_economy": 2500},
    ),
    "demo-mok2@mitjip.test": (
        "정시연",
        "시연목수",
        "정시연",
        "9990000905",
        "01000000905",
        "mokgong",
        {
            "frame": 19000,
            "board": 12500,
            "ceiling_mat": 9500,
            "door": 95000,
            "casing": 4800,
            "door_mat": 175000,
            "molding": 3800,
            "molding_mat": 2400,
            "base": 3200,
            "base_mat": 2100,
        },
    ),
    "demo-mok3@mitjip.test": (
        "강시연",
        "시연우드",
        "강시연",
        "9990000906",
        "01000000906",
        "mokgong",
        {
            "frame": 17500,
            "board": 11500,
            "ceiling_mat": 9000,
            "door": 88000,
            "casing": 4300,
            "door_mat": 190000,
            "molding": 3300,
            "molding_mat": 2700,
            "base": 2900,
            "base_mat": 2200,
        },
    ),
}
D1, D2, MOK = list(VENDORS)[:3]
AREA = ("seoul", "노원구")
# 업체마다 보내는 실측 견적서: demo_assets 이미지 · 문서에 적힌 낼 금액 · 부가세 방식 (공사 기간 3일)
ASSETS = Path(__file__).parent / "demo_assets"
QUOTE_DOCS = {
    "demo-dobae1@mitjip.test": ("quote-dobae1.jpg", 3_080_000, "excluded"),
    "demo-dobae2@mitjip.test": ("quote-dobae2.jpg", 3_300_000, "included"),
    "demo-dobae3@mitjip.test": ("quote-dobae3.jpg", 2_980_000, "excluded"),
    "demo-mok1@mitjip.test": ("quote-mok1.jpg", 1_450_000, "excluded"),
    "demo-mok2@mitjip.test": ("quote-mok2.jpg", 1_540_000, "included"),
    "demo-mok3@mitjip.test": ("quote-mok3.jpg", 1_390_000, "excluded"),
}
QUOTE_DAYS = 3
QUOTE_VALID_DAYS = 14
QUOTE_PDF = sample_pdf(b"SAMPLE QUOTE - demo data only")
PRICE_PDF = sample_pdf(b"SAMPLE PRICE LIST - demo data only")


def _project(today: date, both: bool) -> ProjectCreate:
    """노원구 32평(공급 105.8㎡) 빈 집. both면 목공(몰딩 · 걸레받이)도 한다."""
    trades = {"dobae": {"spaces": ["a", "b", "c"], "grade": "basic"}}
    if both:
        trades["mokgong"] = {"spaces": ["a"], "items": ["molding", "base"]}
    return ProjectCreate.model_validate(
        {
            "sido": AREA[0],
            "sgg": AREA[1],
            "built_year": 2009,
            "size": {"basis": "supply", "m2": "105.8"},
            "balcony_ext": False,
            "when": {
                "kind": "date",
                "start": (today + timedelta(days=28)).isoformat(),
                "end": (today + timedelta(days=42)).isoformat(),
            },
            "occupied": False,
            "budget": "500-700",
            "spaces": [
                {"key": "a", "name": "거실"},
                {"key": "b", "name": "안방"},
                {"key": "c", "name": "작은방"},
            ],
            "trades": trades,
        }
    )


async def _user(s, email: str, name: str, password: str, role: str, phone=None) -> User:
    user = await auth_repo.user_by_email(s, email)
    if user is None:
        user = await auth_service.create_user(
            s, email=email, name=name, password=password, role=role, phone=phone
        )
    return user


async def _vendor(s, email: str, password: str, admin: User, today: date) -> User:
    """승인 · 업체 정보 · 확인한 단가까지 갖춘 시연 업체. 이미 있으면 빈 것만 채운다."""
    name, biz, owner, biz_no, phone, trade, prices = VENDORS[email]
    user = await _user(s, email, name, password, "vendor")
    if await s.get(Vendor, user.id) is None:
        lic = files_service.Prepared(
            kind="license", data=LICENSE, content_type="application/pdf", filename="시연용.pdf"
        )
        row = await files_service.persist(s, user.id, lic)
        now = now_utc()
        try:
            s.add(
                Vendor(
                    user_id=user.id,
                    license_file_id=row.id,
                    status="approved",
                    reviewed_by=admin.id,
                    reviewed_at=now,
                    approved_at=now,
                    biz_name=biz,
                    owner_name=owner,
                    biz_no=biz_no,
                    phone=phone,
                    address="서울 노원구 (시연용 주소)",
                    contact_method="phone",
                    call_start=time(9),
                    call_end=time(18),
                    visit_fee=0,
                )
            )
            await s.flush()
            s.add_all(
                [
                    VendorReview(vendor_id=user.id, action="apply", by_id=user.id, at=now),
                    VendorReview(vendor_id=user.id, action="approve", by_id=admin.id, at=now),
                    VendorTrade(vendor_id=user.id, trade=trade),
                    VendorArea(vendor_id=user.id, sido=AREA[0], sgg=AREA[1]),
                ]
            )
            await s.commit()
        except Exception:
            await s.rollback()
            files_service.discard(row)  # 업체 행을 못 만들었으면 등록증 파일도 남기지 않는다
            raise
    else:
        await s.commit()
    if not await vendor_repo.price_sets(s, [user.id], trade, ("confirmed",)):
        if not await vendor_repo.price_files(
            s, [user.id], trade
        ):  # 단가 확인에 꼭 필요한 근거 파일
            doc = files_service.Prepared(
                kind="price_doc",
                data=PRICE_PDF,
                content_type="application/pdf",
                filename="단가표.pdf",
            )
            row = await files_service.persist(s, user.id, doc)
            await s.commit()
            await vendor_service.add_price_file(s, user, PriceFileIn(file_id=row.id, trade=trade))
        lines = [PriceLineIn(key=k, unit_price=v) for k, v in prices.items()]
        if trade == "dobae" and "primer" not in prices:
            lines.append(PriceLineIn(key="primer", included_in="paper_basic"))
        await vendor_service.save_prices(s, user, trade, PriceSetIn(lines=lines))
        await vendor_service.confirm_prices(s, user, trade)
    return user


async def _ask(s, customer: User, pid, trade: str, vendors: list[User], today: date) -> list:
    """실측 요청(연락처 보냄). 업체 순서대로 요청 id"""
    ids = [v.id for v in vendors]
    data = VisitCreateIn(
        trade=trade,
        vendor_ids=ids,
        share_contact_ids=ids,
        apt_name="시연아파트",
        dong="101",
        ho="1203",
        consent_ver=visit_service.CONSENT_VER,
    )
    out = await visit_service.request_visits(s, customer, pid, data, today)
    if out.failed:
        raise RuntimeError("시연 업체에 실측을 요청하지 못했어요.")
    by_vendor = {v.vendor_id: v.id for v in out.created}
    return [by_vendor[i] for i in ids]


async def _quote(s, vendor: User, visit_id, today: date) -> None:
    """업체가 실측 견적서를 보낸다: 그 업체의 견적서 이미지(없으면 빈 PDF)와 문서에 적힌 금액 그대로."""
    name, amount, vat_mode = QUOTE_DOCS[vendor.email]
    path = ASSETS / name
    if path.exists():
        doc = (await asyncio.to_thread(path.read_bytes), "image/jpeg", "실측견적서.jpg")
    else:
        doc = (QUOTE_PDF, "application/pdf", "실측견적서.pdf")
    f = files_service.Prepared(kind="quote_doc", data=doc[0], content_type=doc[1], filename=doc[2])
    row = await files_service.persist(s, vendor.id, f)
    await s.commit()
    data = QuoteDraftIn(
        file_ids=[row.id],
        measured_on=today,
        entered_amount=amount,
        vat_mode=vat_mode,
        days=QUOTE_DAYS,
        valid_until=today + timedelta(days=QUOTE_VALID_DAYS),
    )
    await visit_service.save_quote(s, vendor, visit_id, data, today)
    await visit_service.send_quote(s, vendor, visit_id, today)


async def _dates(s, customer: User, pid, visit_id, vendor: User, days: list[date], today: date):
    """확정 → 업체가 공사 날짜 냄. (확정 id, 낸 날짜 id)"""
    deal = (
        await schedule_service.confirm(s, customer, pid, visit_id, ConfirmIn(seen_ver=1), today)
    ).deal
    dates = DatesIn(start=days[0], end=days[-1], crew=2, method="app")
    job = await schedule_service.propose_dates(s, vendor, deal.id, dates, today)
    return deal.id, job.proposal.id


LOCK = "demo:auto_reply"  # worker 자동 응답이 한 번 도는 동안 · 시연 데이터를 만드는 동안 잡는다


@asynccontextmanager
async def _paused():
    """시연 데이터를 만드는 동안 자동 응답을 멈춘다 (업체 일을 build가 직접 한다). Redis가 없으면 그냥 간다."""
    r = Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)
    held = False
    try:
        for _ in range(30):  # 자동 응답이 도는 중이면 끝날 때까지 기다린다
            if held := bool(await r.set(LOCK, "build", nx=True, ex=600)):
                break
            await asyncio.sleep(1)
    except RedisError:
        pass
    try:
        yield
    finally:
        if held:
            with suppress(RedisError):
                await r.delete(LOCK)
        await r.aclose()


async def build(password: str, today: date) -> dict[str, str]:
    """단계 코드 → 새로 만든 프로젝트 번호(MJ-…)"""
    try:
        async with _paused(), SessionLocal() as s:
            first_admin = select(User).where(User.role == "admin").order_by(User.created_at)
            admin = await s.scalar(first_admin.limit(1))
            if admin is None:
                raise RuntimeError("업체 승인자로 남길 관리자 계정이 먼저 있어야 해요.")
            email, name, phone = CUSTOMER
            customer = await _user(s, email, name, password, "customer", phone)
            await s.commit()
            vendors = {e: await _vendor(s, e, password, admin, today) for e in VENDORS}
            d1, d2, mok = vendors[D1], vendors[D2], vendors[MOK]
            off = days_off(today, today + timedelta(days=400))
            made = {}

            async def new(stage: str, both: bool = False):
                p = await project_service.create(s, customer, _project(today, both), today)
                made[stage] = p.code
                return p.id

            await new("pick", both=True)

            pid = await new("visit_requested")
            for vendor, visit_id in zip(
                (d1, d2), await _ask(s, customer, pid, "dobae", [d1, d2], today), strict=True
            ):  # 업체가 열어 본 요청은 자동 응답이 건드리지 않는다 (이 단계를 그대로 보여 준다)
                await visit_service.mark_seen(s, vendor, visit_id)

            pid = await new("quotes_arrived")
            va, vb = await _ask(s, customer, pid, "dobae", [d1, d2], today)
            await _quote(s, d1, va, today)
            await _quote(s, d2, vb, today)

            pid = await new("dates_received")
            (va,) = await _ask(s, customer, pid, "dobae", [d1], today)
            await _quote(s, d1, va, today)
            await _dates(
                s, customer, pid, va, d1, workdays(today + timedelta(days=28), 3, off), today
            )

            pid = await new("before_work", both=True)
            (vm,) = await _ask(s, customer, pid, "mokgong", [mok], today)
            (vd,) = await _ask(s, customer, pid, "dobae", [d1], today)
            await _quote(s, mok, vm, today)
            await _quote(s, d1, vd, today)
            mok_days = workdays(today + timedelta(days=28), 2, off)
            dobae_days = workdays(mok_days[-1] + timedelta(days=3), 3, off)
            seen = 0
            for visit_id, vendor, days in ((vm, mok, mok_days), (vd, d1, dobae_days)):
                deal_id, prop_id = await _dates(s, customer, pid, visit_id, vendor, days, today)
                out = await schedule_service.accept_dates(
                    s, customer, pid, deal_id, prop_id, AcceptIn(seen_version=seen), today
                )
                seen = out.final_version
    finally:
        await engine.dispose()  # 한 번 돌고 끝나는 스크립트 · 시험이 이벤트 루프를 새로 만든다
    return made


# ---- 자동 응답: 시연 업체 3곳이 할 일을 업체가 누르는 것과 같은 service 함수로 대신 한다 ----
# 실측 요청(업체가 아직 안 열어 봄) → 그 업체의 견적서 이미지 · 문서 금액으로 실측 견적서 보내기
# 확정 → 예상 공정표 자리에 공사 날짜 내기, 고객이 다른 날짜 · 바꾸기를 요청 → 고른 첫 시작일로 다시 내기
# 날짜는 계산 엔진, 금액은 업체 문서에 적힌 값(QUOTE_DOCS)을 그대로 쓰고, 여기서 셈하지 않는다.


def _span(first: date, days: int, weekend: tuple[int, ...]) -> tuple[date, date]:
    """first부터 일하는 날 days개의 첫날 · 끝날"""
    got = workdays(first, max(days, 1), days_off(first, first + timedelta(days=400)), weekend)
    return got[0], got[-1]


async def _reply_quote(s, vendor: User, visit_id, today: date) -> None:
    await _quote(s, vendor, visit_id, today)


async def _reply_dates(s, vendor: User, deal_id, today: date) -> None:
    job = await schedule_service.job_for(s, vendor, deal_id, today)
    weekend = () if job.weekend_work else WEEKEND
    tomorrow = today + timedelta(days=1)
    if job.dates_state == "waiting":
        crew = job.need.crew
        start, end = _span(max(job.plan_start or tomorrow, tomorrow), job.need.days, weekend)
        fit = (
            await schedule_service.preview_dates(s, vendor, deal_id, start, end, crew, today)
        ).fit
        if fit.conflicts and fit.start_from and fit.start_from > start:  # 앞 공정이 끝난 뒤로
            start, end = _span(fit.start_from, job.need.days, weekend)
        data = DatesIn(start=start, end=end, crew=crew, method="app")
    elif job.dates_state == "requested" and job.request and job.proposal:
        start, end = _span(min(job.request.wish_dates), job.proposal.workdays, weekend)
        data = DatesIn(
            start=start, end=end, crew=job.proposal.crew, method="app", request_id=job.request.id
        )
    elif job.dates_state == "change_requested" and job.request and job.request_options:
        o = job.request_options[0]
        data = DatesIn(
            start=o.start,
            end=o.end,
            crew=job.accepted_crew or job.need.crew,
            method="app",
            kind="change",
            request_id=job.request.id,
        )
    else:
        return
    await schedule_service.propose_dates(s, vendor, deal_id, data, today)


async def _todo(s, vendor_ids: list) -> list[tuple]:
    """할 일 (종류, id, 업체 id, 열린 날짜 요청 id): 안 열어 본 실측 요청 · 날짜를 낼 확정"""
    visits = select(Visit.id, Visit.vendor_id).where(
        Visit.vendor_id.in_(vendor_ids),
        Visit.status == "requested",
        Visit.vendor_seen_at.is_(None),
    )
    pending = (
        select(DateProposal.id)
        .where(DateProposal.deal_id == Deal.id, DateProposal.status == "pending")
        .exists()
    )
    asked = (
        select(DateRequest.id)
        .where(DateRequest.deal_id == Deal.id, DateRequest.status == "open")
        .limit(1)
        .scalar_subquery()
    )
    deals = select(Deal.id, Deal.vendor_id, asked).where(
        Deal.vendor_id.in_(vendor_ids),
        or_(
            and_(Deal.status == "confirmed", ~pending, asked.is_(None)),
            and_(Deal.status.in_(("confirmed", "scheduled")), asked.is_not(None)),
        ),
    )
    out = [("quote", i, vid, None) for i, vid in (await s.execute(visits)).all()]
    return out + [("dates", i, vid, r) for i, vid, r in (await s.execute(deals)).all()]


REPLY = {"quote": _reply_quote, "dates": _reply_dates}


async def auto_reply(today: date, skip: set) -> int:
    """한 번 돌면서 한 일의 수. 실패한 건은 skip에 넣어 같은 상태로는 다시 시도하지 않는다."""
    done = 0
    async with SessionLocal() as s:
        q = select(User).where(User.email.in_(list(VENDORS)), User.role == "vendor")
        vendors = {u.id: u for u in (await s.scalars(q)).all()}
        if not vendors:
            return 0
        for kind, row_id, vendor_id, req in await _todo(s, list(vendors)):
            key = (kind, row_id, req)
            if key in skip:
                continue
            try:
                await REPLY[kind](s, vendors[vendor_id], row_id, today)
                done += 1
            except AppError as exc:  # 그사이 고객이 바꿨거나 낼 수 없는 날짜 (로그에는 코드만)
                await s.rollback()
                skip.add(key)
                log.warning("시연 자동 응답을 건너뛰었어요: %s %s %s", kind, row_id, exc.code)
            except Exception:
                await s.rollback()
                skip.add(key)
                log.exception("시연 자동 응답이 실패했어요: %s %s", kind, row_id)
    return done


LABEL = {
    "pick": "업체 고르기",
    "visit_requested": "실측 요청",
    "quotes_arrived": "견적서 옴",
    "dates_received": "공사 날짜 옴",
    "before_work": "확정 공정표",
}


def main() -> None:
    if settings.app_env == "production":
        raise SystemExit("시연 데이터는 운영(APP_ENV=production)에서 만들지 않아요.")
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 8:
        raise SystemExit("DEMO_PASSWORD에 8자 이상 비밀번호를 넣어 주세요.")
    made = asyncio.run(build(password, today_seoul()))
    for stage, label in LABEL.items():
        print(f"만들었어요: {label} {made[stage]}")


if __name__ == "__main__":
    main()

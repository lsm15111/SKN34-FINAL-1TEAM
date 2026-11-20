"""로그인 전 표준견적서 계산 (dev-03, C57 · J1).

DB에 쓰지 않고 입력을 로그에 남기지 않는다. 숫자는 가입 뒤 표준견적서와 같은 계산 엔진(calc.dobae.standard_v3)이
만든다(화면이 보낸 금액은 믿지 않음). 지역 · 동 · 희망일 검사는 공사 만들기와 같은 project.schemas.check_home.
"""

from datetime import date

from app.calc import dobae
from app.calc.common import FORMULA_VERSION
from app.calc.quote_diff import budget_fit
from app.calc.space_share import ROOM_KINDS, ROOMS_MAX, ROOMS_MIN, SPACE_SHARE_ROOMS_2026_11
from app.guest.schemas import GuestLineOut, GuestStandardOut, RoomBandOut, RoomRuleOut
from app.project.schemas import HomeInfoIn, check_home
from app.refprice.book import DOBAE_DEFAULT, DOBAE_PROFILES
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market


def room_rule() -> RoomRuleOut:
    """GET /guest/room-rule: 방 개수 칸의 범위 · 평형 기본값 표 (계산 엔진 판 그대로)"""
    p = DOBAE_DEFAULT  # 방 개수 표는 두 기준 판이 같다
    return RoomRuleOut(
        price_ver=p.version,
        share_ver=SPACE_SHARE_ROOMS_2026_11.version,
        min=ROOMS_MIN,
        max=ROOMS_MAX,
        fallback=p.room_fallback,
        bands=[RoomBandOut(area_basis=b, min_m2=m, rooms=n) for b, m, n in dobae.room_bands_m2(p)],
        room_kinds=list(ROOM_KINDS),
    )


async def standard(data: HomeInfoIn, today: date) -> GuestStandardOut:
    """POST /guest/standard: 기본 정보 → 표준견적서 v3(줄 · 합계 · 예상 일수 · 품 · 예산 안/밖 · 가정).
    지역 밖 · 지난 희망일은 422 invalid(fields)."""
    check_home(data, today)
    h = dobae.HomeV3(
        data.area_m2,
        data.area_basis,
        data.grade,
        data.occupied,
        data.scope,
        tuple(data.spaces),
        tuple(data.faces),
        rooms=data.rooms,
    )
    # 손님은 도배만 넣어요(목공 · 모은 조건 없음). 기준은 계산 엔진이 고른다(ADR 0004: 도배만 하는 공사)
    pick = dobae.pick_profile(dobae.WorkFacts())
    p = DOBAE_PROFILES[pick.profile]
    v = dobae.standard_v3(
        h, p, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2, pick.why
    )
    q = v.quote
    return GuestStandardOut(
        formula_ver=FORMULA_VERSION,
        price_ver=q.version,
        market_ver=v.market_ver,
        share_ver=v.share_ver,
        scope=data.scope,
        area_m2=data.area_m2,
        area_basis=data.area_basis,
        pyeong=v.pyeong,
        rooms=v.rooms or data.rooms,
        lines=[
            GuestLineOut(
                key=ln.key,
                name=ln.name,
                qty=ln.qty,
                unit=ln.unit,
                unit_price=ln.unit_price,
                amount=ln.amount,
                state=ln.state,
                basis=ln.basis,
                source=ln.source,
            )
            for ln in q.lines
        ],
        supply=q.subtotal,
        vat=q.vat,
        total=q.total,
        days=q.days,
        man_day=q.man_days,
        budget_fit=budget_fit(q.total, data.budget_won),
        assumptions=list(q.assumptions),
        profile=p.profile.key if p.profile else None,
        profile_name=p.profile.name if p.profile else None,
    )

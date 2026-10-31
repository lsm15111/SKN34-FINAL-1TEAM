"""받는 길 고르기 (코드 규칙). 업체마다 가견적을 받을 길 하나와 비용 표시를 정한다. 순수 함수만 둔다.

| 업체 | 조건 | 길 |
| --- | --- | --- |
| 앱 승인 업체 | 그 공정 · 시군구를 맡음 | app_request: 앱 안 가견적 요청 (무료) |
| 외부 업체 | 동의한 연락처 + 수신거부 아님 + 대신 연락 켜짐 | proxy: 믿집이 대신 요청 |
| 외부 업체 | 공개 견적 창구(홈페이지의 견적 · 문의 링크) | link: 링크 + 요청문 복사 |
| 외부 업체 | 공개 대표 전화(공공 등록 정보의 사무실 번호) | phone: 통화 체크리스트 |
| 외부 업체 | 그 밖 | reference: 포트폴리오 · 등록 정보만 |

비용: 앱 요청은 무료. 외부 업체는 업체가 공지한 출장비가 있으면 그 값(0이면 무료), 없으면 '확인 필요'.
금액은 업체가 공지한 입력값을 그대로 보여 줄 뿐 여기서 계산하지 않는다.
"""

from dataclasses import dataclass
from typing import Literal

from app.calc.common import BASIS_LABEL
from app.directory.industry import TRADE_LABEL
from app.project.schemas import ProjectOut, WhenIn

Route = Literal["app_request", "proxy", "link", "phone", "reference"]
CostKind = Literal["free", "vendor_fee", "unknown"]

ROUTE_LABEL: dict[str, str] = {
    "app_request": "믿집에서 가견적 요청",
    "proxy": "믿집이 대신 요청",
    "link": "업체 견적 창구로 요청",
    "phone": "전화로 물어보기",
    "reference": "정보만 보기",
}
PROXY_OFF = "대신 요청은 아직 꺼져 있어요."


@dataclass(frozen=True)
class Facts:
    """길을 고르는 데 쓰는 사실만"""

    is_app: bool
    has_consented_contact: bool = False
    opted_out: bool = False
    quote_url: str | None = None
    phone: str | None = None
    visit_fee: int | None = None


@dataclass(frozen=True)
class Choice:
    route: Route
    cost: CostKind
    fee: int | None  # vendor_fee일 때 업체가 공지한 금액(원)
    proxy_off: bool  # 동의한 연락처가 있는데 대신 연락이 꺼져 있어 못 쓰는 경우


def choose(f: Facts, *, proxy_enabled: bool) -> Choice:
    if f.is_app:
        return Choice("app_request", "free", None, False)
    can_proxy = f.has_consented_contact and not f.opted_out
    route: Route
    if can_proxy and proxy_enabled:
        route = "proxy"
    elif f.quote_url:
        route = "link"
    elif f.phone:
        route = "phone"
    else:
        route = "reference"
    if f.visit_fee is None:
        cost, fee = "unknown", None
    elif f.visit_fee == 0:
        cost, fee = "free", None
    else:
        cost, fee = "vendor_fee", f.visit_fee
    return Choice(route, cost, fee, can_proxy and not proxy_enabled)


def cost_label(c: Choice) -> str:
    if c.route == "app_request":
        return "무료"
    if c.cost == "free":
        return "무료 (업체 공지)"
    if c.cost == "vendor_fee":
        return f"출장비 {c.fee:,}원 (업체 공지)"
    return "확인 필요"


# 전화로 물어볼 때 쓸 체크리스트. 공정별 항목은 업체가 가견적 전에 꼭 묻는 것(조사 자료)에서 골랐다
_CHECK_COMMON = [
    "믿집에서 정리한 집 정보를 읽어 주고, 이 정보로 가견적을 받을 수 있는지 물어봐요.",
    "가견적이나 실측에 출장비가 드는지 물어봐요.",
    "실측 가능한 날짜를 물어봐요.",
    "견적서를 공정 줄마다 나눠서 받을 수 있는지 물어봐요.",
]
_CHECK_TRADE = {
    "dobae": [
        "벽지 종류(합지 · 실크)와 천장 포함 여부를 말해요.",
        "기존 벽지 철거와 짐 옮기기가 가견적에 들어 있는지 물어봐요.",
    ],
    "mokgong": [
        "몰딩 · 걸레받이가 교체인지 새로 하는지, 철거 · 폐기가 들어 있는지 물어봐요.",
        "방문은 몇 개인지, 문틀도 바꾸는지 말해요.",
    ],
}


def call_checklist(trades: list[str]) -> list[str]:
    return _CHECK_COMMON + [x for t in trades for x in _CHECK_TRADE.get(t, [])]


# ── 업체에 건넬 집 정보 (요청문 · 받은편지함에 같이 쓴다). 고객 이름 · 연락처 · 동 · 호수는 넣지 않는다 ──

GRADE_LABEL = {"economy": "저가형", "basic": "기본형"}
MOK_LABEL = {
    "molding": "천장 몰딩",
    "base": "걸레받이",
    "door": "방문 교체",
    "flatten": "천장 평탄화",
}
WHEN_LABEL = {"months": "1~2달 안에", "unknown": "아직 몰라요"}


def project_trades(p: ProjectOut) -> list[str]:
    return [key for key, t in p.trades if t is not None]


def when_text(w: WhenIn) -> str:
    if w.kind == "date":
        return f"{w.start} 시작" + (f", {w.end}까지" if w.end else "")
    if w.kind == "movein":
        return f"{w.start} 이사 전까지"
    return WHEN_LABEL[w.kind]


def size_text(p: ProjectOut) -> str:
    if p.size.band:
        return "50평 이상 (공급)" if p.size.band == "50" else f"{p.size.band}평대 (공급)"
    return f"{BASIS_LABEL[p.size.basis]} {p.size.m2}㎡"


def request_facts(p: ProjectOut, trades: list[str] | None = None) -> list[str]:
    """공정 · 지역 · 집 · 시기 · 거주를 한 줄씩. 숫자는 고객이 넣은 값 그대로다."""
    names = {sp.id: sp.name for sp in p.spaces}
    out: list[str] = []
    for key, t in p.trades:
        if t is None or (trades is not None and key not in trades):
            continue
        detail = []
        if getattr(t, "grade", None):
            detail.append(GRADE_LABEL[t.grade])
        if getattr(t, "items", None):
            detail.append(" · ".join(MOK_LABEL[i] for i in t.items))
        spaces = " · ".join(names[i] for i in t.spaces if i in names)
        if spaces:
            detail.append(spaces)
        out.append(f"{TRADE_LABEL[key]}: " + ", ".join(detail))
    house = ["아파트", size_text(p)]
    house += [f"{p.built_year}년 준공"] if p.built_year else []
    house += ["발코니 확장"] if p.balcony_ext else []
    return out + [
        f"지역: {p.region}",
        "집: " + ", ".join(house),
        "시기: " + when_text(p.when),
        "거주: " + ("살면서 공사" if p.occupied else "빈집"),
    ]

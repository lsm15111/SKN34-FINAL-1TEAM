"""공정 의견 사례 입력 → 계산 엔진 입력 · 견적 · 공정 에이전트 입력 글.

상담 코드가 곧 공정 플러그인(TradeSpec)으로 바뀌므로 에이전트 입력 글(card_text)을 만드는 부분을
평가 쪽에 얇게 둔다. 출처: backend/app/consult/service.py 의 DEFAULTS · CHECK_NAMES · MOK_LABEL ·
_common_text · _check_text · card_text · mokgong_text · inputs (커밋 56c9b01).
TradeSpec.card_text · to_input이 생기면 이 파일의 해당 함수만 그것을 부르도록 바꾼다.

계산 엔진 · 기준 단가는 표준 라이브러리만 쓰는 순수 함수라 그대로 불러 쓴다.
에이전트 모듈(app.agent.*)은 anthropic · pydantic이 필요해서 render · module 안에서만 불러온다.
backend 폴더가 sys.path에 있어야 한다 (실행 스크립트 · tests/conftest.py가 넣는다).
"""

from decimal import Decimal

from app.calc import dobae, mokgong
from app.calc.common import BASIS_LABEL
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2

AGENTS = ("wallpaper", "carpentry")
TRADE = {"wallpaper": "dobae", "carpentry": "mokgong"}
OTHER = {"wallpaper": "mokgong", "carpentry": "dobae"}
TRADE_LABEL = {"dobae": "도배", "mokgong": "목공"}
# 에이전트 입력 글의 '고객이 몰라 기본값으로 둔 칸'에 나오는 칸 (consult.service.card_text · mokgong_text)
CHECK_FIELDS = {
    "wallpaper": ("area_basis", "grade", "include_ceiling"),
    "carpentry": ("area_basis", "doors", "door_frame"),
}
# 아래 셋은 consult.service와 같게 둔다
DEFAULTS: dict[str, object] = {
    "area_basis": "supply",
    "grade": "basic",
    "include_ceiling": True,
    "doors": 3,
    "door_frame": True,
}
CHECK_NAMES = {
    "area_basis": "면적 기준",
    "grade": "등급",
    "include_ceiling": "천장 포함",
    "doors": "방문 개수",
    "door_frame": "문틀 교체",
}
MOK_LABEL = {"molding": "천장 몰딩", "base": "걸레받이", "door": "방문", "flatten": "천장 평탄화"}
ITEMS = mokgong.ITEMS


def calc_input(agent: str, inp: dict) -> dobae.DobaeInput | mokgong.MokgongInput:
    """consult.service.inputs와 같은 규칙으로 계산 엔진 입력을 만든다."""
    c = inp["common"]
    area = Decimal(c["area_m2"])
    if agent == "wallpaper":
        t = inp["trades"]["dobae"]
        return dobae.DobaeInput(
            area_m2=area,
            area_basis=c["area_basis"],
            grade=t["grade"],
            include_ceiling=t["include_ceiling"],
            occupied=c["occupied"],
            balcony_ext=c["balcony_ext"],
        )
    t = inp["trades"]["mokgong"]
    return mokgong.MokgongInput(
        area_m2=area,
        area_basis=c["area_basis"],
        items=tuple(t["items"]),
        occupied=c["occupied"],
        doors=t.get("doors") or 0,
        door_frame=t.get("door_frame") is not False,
    )


def quote(agent: str, inp: dict) -> dobae.DobaeQuote | mokgong.MokgongQuote:
    if agent == "wallpaper":
        return dobae.quote(calc_input(agent, inp), DOBAE_2026H2)
    return mokgong.quote(calc_input(agent, inp), MOKGONG_2026H2)


def facts(q: dobae.DobaeQuote | mokgong.MokgongQuote) -> dict[str, list[str]]:
    """견적에서 기대 검사에 쓰는 것: 공정표 단계 키, '실측 후' 줄 키, '안 함' 줄 키"""
    return {
        "step_keys": [s.key for s in q.steps],
        "after_visit": [ln.key for ln in q.lines if ln.state == "after_visit"],
        "excluded": [ln.key for ln in q.lines if ln.state == "excluded"],
    }


def _common_rows(c: dict) -> list[str]:
    rows = [
        f"면적: {BASIS_LABEL[c['area_basis']]} {c['area_m2']}㎡",
        f"사는 집에서 공사: {'예' if c['occupied'] else '아니요(빈집)'}",
        f"발코니 확장: {'예' if c['balcony_ext'] else '아니요'}",
    ]
    if c.get("built_year"):
        rows.append(f"준공 연도: {c['built_year']}")
    return rows


def _check_rows(to_check: list[str], fields: tuple[str, ...]) -> list[str]:
    names = [CHECK_NAMES[f] for f in to_check if f in fields]
    return ["고객이 몰라 기본값으로 둔 칸: " + ", ".join(names)] if names else []


def card_text(agent: str, inp: dict) -> str:
    """공정 에이전트에 넘기는 집 정보 (consult.service.card_text · mokgong_text와 같은 글)"""
    c, other = inp["common"], inp.get("other_trades", [])
    rows = _common_rows(c)
    if agent == "wallpaper":
        t = inp["trades"]["dobae"]
        rows += [
            f"도배 등급: {'기본형(실크)' if t['grade'] == 'basic' else '저가형(합지)'}",
            f"천장: {'포함' if t['include_ceiling'] else '안 함'}",
        ]
        if "mokgong" in other:
            rows.append("목공을 같이 해요 (목공이 끝난 뒤 도배)")
    else:
        t = inp["trades"]["mokgong"]
        rows.append("목공 항목: " + ", ".join(MOK_LABEL[i] for i in t["items"]))
        if t.get("spaces"):
            rows.append("목공 공간: " + ", ".join(t["spaces"]))
        if "door" in t["items"]:
            rows.append(f"방문: {'문틀까지' if t['door_frame'] else '문짝만'} 바꿔요")
        if "dobae" in other:
            rows.append("도배를 같이 해요 (목공이 먼저)")
    return "\n".join(rows + _check_rows(inp.get("to_check", []), CHECK_FIELDS[agent]))


def module(agent: str):
    """공정 에이전트 모듈 (plan · validate · SKILL · SOURCES · PROMPT_VERSION)"""
    if agent == "wallpaper":
        from app.agent import wallpaper

        return wallpaper
    from app.agent import carpentry

    return carpentry


def render(agent: str, inp: dict, q=None) -> str:
    """공정 에이전트가 받는 사용자 글 그대로 (app.agent.trade.render)"""
    from app.agent import trade

    return trade.render(card_text(agent, inp), q if q is not None else quote(agent, inp))

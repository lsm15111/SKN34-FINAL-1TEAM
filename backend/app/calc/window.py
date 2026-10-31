"""창호(샷시) 표준견적서와 예상 공정표. 항목은 창틀 · 창짝, 창호 설치, 복층유리와 끼우기, 창 둘레 실리콘이다.

창호 설치 · 유리 · 실리콘은 공공 단가가 있지만 가장 큰 비용인 창틀 자재는 공공 가격이 없어 팀 가정값이다.
실측 전이라 창 개수 · 크기는 전용면적과 발코니 확장 여부에서 추정하고, 그 가정은 결과의 assumptions에
그대로 남긴다. 금액은 원 정수이고 반올림은 won() 한 곳에서만 한다.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.calc.common import COUNTED, AreaBasis, Line, Step, half_days, half_up, m2, won

Scope = Literal["all", "some"]
Frame = Literal["pvc", "system"]
Glass = Literal["low_e", "clear"]
SCOPES: tuple[Scope, ...] = ("all", "some")
FRAMES: tuple[Frame, ...] = ("pvc", "system")
GLASSES: tuple[Glass, ...] = ("low_e", "clear")
FRAME_NAME = {"pvc": "PVC 이중창", "system": "알루미늄 시스템창"}
GLASS_NAME = {"low_e": "로이 복층유리", "clear": "일반 복층유리"}
MAX_WINDOWS = 30


@dataclass(frozen=True)
class WindowPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    frame: dict[str, int]  # 창틀 · 창짝 원/㎡ (PVC는 자재만, 시스템창은 자재 · 설치)
    pvc_install: int  # PVC 미서기 이중창 설치 원/개소
    glass: dict[str, int]  # 복층유리 종류별 원/㎡
    glass_install: int  # 복층유리 끼우기 원/㎡
    caulk: int  # 창 둘레 실리콘 원/m
    window_m2: Decimal  # 창 하나 평균 크기 ㎡ (가정값)
    m2_per_window: Decimal  # 전용 몇 ㎡에 창 하나 (가정값)
    ext_fewer: int  # 발코니를 확장한 집에서 없어지는 안쪽 창 수 (가정값)
    glass_share: Decimal  # 창 면적 중 유리 비율 (가정값)
    glass_layers: dict[str, int]  # 창 종류별 유리 겹 수
    seal_m: Decimal  # 창 하나 둘레 실리콘 m (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    md_remove: Decimal  # 철거 품 인/개소 (가정값)
    md_frame: dict[str, Decimal]  # 창틀 설치 품 인/개소
    md_glass: Decimal  # 유리 끼우기 품 인/㎡
    crew: int  # 하루 들어가는 창호 기사 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class WindowInput:
    area_m2: Decimal
    area_basis: AreaBasis
    occupied: bool
    balcony_ext: bool = False
    scope: Scope = "all"
    count: int = 0  # 일부일 때 바꿀 창 개수
    frame: Frame = "pvc"
    glass: Glass = "low_e"


@dataclass(frozen=True)
class WindowQuote:
    version: str
    windows: int
    frame_m2: Decimal  # 창 면적 합
    glass_m2: Decimal  # 유리 면적 합
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 창호 기사 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _check(inp: WindowInput) -> None:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in ("supply", "exclusive"):
        raise ValueError("면적 기준이 잘못됐어요")
    if inp.scope not in SCOPES or inp.frame not in FRAMES or inp.glass not in GLASSES:
        raise ValueError("창호 범위나 창 · 유리 종류가 잘못됐어요")
    if inp.scope == "some" and not 1 <= inp.count <= MAX_WINDOWS:
        raise ValueError(f"바꿀 창은 1~{MAX_WINDOWS}개예요")


def _after(key: str, name: str, src: dict[str, str]) -> Line:
    return Line(key, name, None, "식", None, None, "after_visit", src["none"], "none")


def quote(inp: WindowInput, p: WindowPrices) -> WindowQuote:
    _check(inp)
    src = p.sources
    if inp.area_basis == "exclusive":
        exclusive = inp.area_m2
    else:
        exclusive = m2(inp.area_m2 / p.supply_per_exclusive)
    if inp.scope == "all":
        n = int((exclusive / p.m2_per_window).to_integral_value(rounding=ROUND_HALF_UP))
        n = max(n - (p.ext_fewer if inp.balcony_ext else 0), 1)
    else:
        n = inp.count
    pvc = inp.frame == "pvc"
    area = m2(p.window_m2 * n)
    glass = m2(area * p.glass_share * p.glass_layers[inp.frame])
    seal = m2(p.seal_m * n)

    frame_price = p.frame[inp.frame]
    lines = [
        Line(
            "frame",
            f"창틀 · 창짝 ({FRAME_NAME[inp.frame]}, {'자재' if pvc else '자재 · 설치'})",
            area,
            "㎡",
            frame_price,
            won(area * frame_price),
            "included",
            src[f"frame_{inp.frame}"],
            "assumed",
        )
    ]
    if pvc:
        lines.append(
            Line(
                "frame_install",
                "창호 설치 (PVC 미서기 이중창)",
                Decimal(n),
                "개소",
                p.pvc_install,
                p.pvc_install * n,
                "included",
                src["pvc_install"],
            )
        )
    glass_price = p.glass[inp.glass]
    lines += [
        Line(
            "glass",
            f"유리 ({GLASS_NAME[inp.glass]})",
            glass,
            "㎡",
            glass_price,
            won(glass * glass_price),
            "included",
            src[f"glass_{inp.glass}"],
        ),
        Line(
            "glass_install",
            "복층유리 끼우기",
            glass,
            "㎡",
            p.glass_install,
            won(glass * p.glass_install),
            "included",
            src["glass_install"],
        ),
        Line(
            "seal",
            "창 둘레 실리콘",
            seal,
            "m",
            p.caulk,
            won(seal * p.caulk),
            "included",
            src["seal"],
        ),
        _after("demolish", "기존 창호 철거", src),
        _after("lift", "사다리차 · 장비", src),
        _after("trim", "창 둘레 마감 (단열 보강 · 몰딩 · 도배 보수)", src),
        _after("waste", "폐기물 처리", src),
    ]
    if inp.occupied:
        lines.append(_after("moving", "짐 이동 · 보양", src))

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    md_remove = n * p.md_remove
    md_install = n * p.md_frame[inp.frame] + glass * p.md_glass
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    steps += [
        Step("remove", "기존 창 철거", half_days(md_remove, p.crew)),
        Step("install", "창틀 설치 · 유리 끼우기", half_days(md_install, p.crew)),
        Step("finish", "실리콘 · 정리", 1),
    ]
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if inp.scope == "all":
        if inp.area_basis == "supply":
            assumptions.append(f"전용면적은 공급면적 ÷ {p.supply_per_exclusive}로 환산했어요.")
        assumptions.append(
            f"창 개수는 전용 {p.m2_per_window}㎡에 하나로 잡았어요. 실측 때 창마다 다시 재요."
        )
        if inp.balcony_ext:
            assumptions.append(
                f"발코니를 확장한 집은 거실 · 안방 안쪽 창 {p.ext_fewer}개가 없다고 보고 뺐어요."
            )
    share = int(p.glass_share * 100)
    layers = "이중창은 유리가 두 겹이에요." if pvc else "시스템창은 유리가 한 겹이에요."
    which = "모든" if inp.scope == "all" else "고른"
    assumptions += [
        f"창 하나는 평균 {p.window_m2}㎡로, 유리는 창 면적의 {share}%로 잡았어요. {layers}",
        "창틀 · 창짝 자재는 공공 가격이 없어 팀 가정값이에요. 브랜드 · 등급에 따라 차이가 커요.",
        f"{which} 창을 {FRAME_NAME[inp.frame]}으로 바꾼다고 잡았어요.",
    ]
    if not pvc:
        assumptions.append("시스템창 값은 창틀 설치까지 넣은 팀 가정값이에요.")
    assumptions.append(f"하루 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return WindowQuote(
        version=p.version,
        windows=n,
        frame_m2=area,
        glass_m2=glass,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_remove + md_install),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )

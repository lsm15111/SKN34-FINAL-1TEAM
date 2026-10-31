"""전기 · 조명 표준견적서와 예상 공정표. 항목은 조명 교체 · 콘센트와 스위치 교체 · 배선 추가다.

공공 단가는 신축 공동주택 기준(새 배관 · 새 박스에 다는 값)이라 기존 자리에서 바꾸기만 하는 공사와 다르다.
조명기구는 공공 가격이 없어 팀 가정값이다. 실측 전이라 개수를 모르면 전용면적에서 추정하고, 그 가정은
결과의 assumptions에 그대로 남긴다. 금액은 원 정수이고 반올림은 won() 한 곳에서만 한다.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from app.calc.common import COUNTED, AreaBasis, Line, Step, half_days, half_up, m2, won

Range = Literal["all", "some", "none"]
LightType = Literal["flat", "downlight", "line"]
RANGES: tuple[Range, ...] = ("all", "some", "none")
LIGHT_TYPES: tuple[LightType, ...] = ("flat", "downlight", "line")
LIGHT_NAME = {"flat": "LED 평판 · 방등", "downlight": "다운라이트", "line": "라인 조명"}
MAX_LIGHTS = 100
MAX_DEVICES = 200
MAX_POINTS = 30


@dataclass(frozen=True)
class ElectricPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    light: dict[str, int]  # 조명 종류별 기구 원/개
    light_install: dict[str, int]  # 조명 종류별 설치 원/개
    outlet: int  # 콘센트 자재 원/개
    switch: int  # 스위치 자재 원/개
    device_install: int  # 콘센트 설치 원/개 (신축 공동주택 기준)
    conduit: int  # 전선관 원/m
    cable: int  # 전선 원/m
    box: int  # 콘센트 박스 원/개
    m2_per_light: dict[str, Decimal]  # 전용 몇 ㎡에 조명 하나 (가정값)
    m2_per_outlet: Decimal  # 전용 몇 ㎡에 콘센트 하나 (가정값)
    m2_per_switch: Decimal  # 전용 몇 ㎡에 스위치 하나 (가정값)
    switch_share: int  # 일부 교체일 때 이 개수 중 하나를 스위치로 (가정값)
    run_m: Decimal  # 새 자리 하나에 끄는 배관 길이 m (가정값)
    wires: int  # 배관 하나에 넣는 전선 가닥 수 (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    md_light: dict[str, Decimal]  # 조명 설치 품 인/개 (가정값)
    md_device: Decimal  # 콘센트 · 스위치 설치 품 인/개
    md_point: Decimal  # 새 자리 배선 품 인/개 (가정값)
    crew: int  # 하루 들어가는 전기 기사 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class ElectricInput:
    area_m2: Decimal
    area_basis: AreaBasis
    occupied: bool
    lights: Range = "all"  # 조명 교체 범위
    light_count: int = 0  # 일부일 때 바꿀 조명 개수
    light_type: LightType = "flat"  # 주로 달 조명
    outlets: Range = "all"  # 콘센트 · 스위치 교체 범위
    outlet_count: int = 0  # 일부일 때 바꿀 콘센트 · 스위치 개수 (합)
    new_points: int = 0  # 배선을 새로 끌어 늘리는 콘센트 자리 수


@dataclass(frozen=True)
class ElectricQuote:
    version: str
    lights: int
    outlets: int
    switches: int
    new_points: int
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 전기 기사 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _ceil(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _check(inp: ElectricInput) -> None:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in ("supply", "exclusive"):
        raise ValueError("면적 기준이 잘못됐어요")
    if inp.lights not in RANGES or inp.outlets not in RANGES or inp.light_type not in LIGHT_TYPES:
        raise ValueError("전기 · 조명 범위나 조명 종류가 잘못됐어요")
    if inp.lights == "some" and not 1 <= inp.light_count <= MAX_LIGHTS:
        raise ValueError(f"바꿀 조명은 1~{MAX_LIGHTS}개예요")
    if inp.outlets == "some" and not 1 <= inp.outlet_count <= MAX_DEVICES:
        raise ValueError(f"바꿀 콘센트 · 스위치는 1~{MAX_DEVICES}개예요")
    if not 0 <= inp.new_points <= MAX_POINTS:
        raise ValueError(f"새로 늘릴 자리는 0~{MAX_POINTS}개예요")
    if inp.lights == "none" and inp.outlets == "none" and inp.new_points == 0:
        raise ValueError("전기 · 조명 항목을 하나 이상 골라야 해요")


def _after(key: str, name: str, src: dict[str, str]) -> Line:
    return Line(key, name, None, "식", None, None, "after_visit", src["none"], "none")


def quote(inp: ElectricInput, p: ElectricPrices) -> ElectricQuote:
    _check(inp)
    src = p.sources
    kind = inp.light_type
    if inp.area_basis == "exclusive":
        exclusive = inp.area_m2
    else:
        exclusive = m2(inp.area_m2 / p.supply_per_exclusive)

    lights = {"all": _ceil(exclusive / p.m2_per_light[kind]), "some": inp.light_count}
    n_light = lights.get(inp.lights, 0)
    if inp.outlets == "all":
        n_outlet = _ceil(exclusive / p.m2_per_outlet)
        n_switch = _ceil(exclusive / p.m2_per_switch)
    elif inp.outlets == "some":
        n_switch = inp.outlet_count // p.switch_share
        n_outlet = inp.outlet_count - n_switch
    else:
        n_outlet = n_switch = 0
    points = inp.new_points
    n_outlet += points  # 새로 늘린 자리에도 콘센트를 단다

    lines: list[Line] = []
    if n_light:
        lines += [
            Line(
                "light",
                f"조명 기구 ({LIGHT_NAME[kind]})",
                Decimal(n_light),
                "개",
                p.light[kind],
                p.light[kind] * n_light,
                "included",
                src[f"light_{kind}"],
                "assumed",
            ),
            Line(
                "light_install",
                "조명 설치 (기존 등 떼고 달기)",
                Decimal(n_light),
                "개",
                p.light_install[kind],
                p.light_install[kind] * n_light,
                "included",
                src["light_install"],
                "assumed",
            ),
        ]
    if n_outlet:
        price = p.outlet + p.device_install
        lines.append(
            Line(
                "outlet",
                "콘센트 (2구, 자재 · 설치)",
                Decimal(n_outlet),
                "개",
                price,
                price * n_outlet,
                "included",
                src["outlet"],
            )
        )
    if n_switch:
        price = p.switch + p.device_install
        lines.append(
            Line(
                "switch",
                "스위치 (자재 · 설치)",
                Decimal(n_switch),
                "개",
                price,
                price * n_switch,
                "included",
                src["switch"],
                "assumed",
            )
        )
    if points:
        pipe = m2(p.run_m * points)
        wire = m2(pipe * p.wires)
        lines += [
            Line(
                "conduit",
                "배선 추가 · 전선관",
                pipe,
                "m",
                p.conduit,
                won(pipe * p.conduit),
                "included",
                src["conduit"],
            ),
            Line(
                "cable",
                "배선 추가 · 전선",
                wire,
                "m",
                p.cable,
                won(wire * p.cable),
                "included",
                src["cable"],
            ),
            Line(
                "box",
                "배선 추가 · 콘센트 박스",
                Decimal(points),
                "개",
                p.box,
                p.box * points,
                "included",
                src["box"],
            ),
        ]
    if n_light and kind != "flat":
        lines.append(
            _after("ceiling_patch", "천장 타공 · 기존 등 자리 보수 (목공 · 도배와 같이)", src)
        )
    if points:
        lines.append(_after("panel", "분전반 · 차단기 점검 (용량 늘리기는 따로)", src))
    if n_light:
        lines.append(_after("waste", "떼어 낸 등 · 폐기물 처리", src))
    if inp.occupied:
        lines.append(_after("moving", "짐 이동 · 보양", src))

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    md_wire = points * p.md_point
    md_fit = n_light * p.md_light[kind] + (n_outlet + n_switch) * p.md_device
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    if points:
        steps.append(Step("wire", "배선 추가 (1차)", half_days(md_wire, p.crew)))
    parts = [n for n, k in (("조명", n_light), ("콘센트", n_outlet), ("스위치", n_switch)) if k]
    steps.append(Step("fixture", f"{' · '.join(parts)} 달기 (2차)", half_days(md_fit, p.crew)))
    steps.append(Step("finish", "점등 · 작동 확인 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if inp.area_basis == "supply" and "all" in (inp.lights, inp.outlets):
        assumptions.append(f"전용면적은 공급면적 ÷ {p.supply_per_exclusive}로 환산했어요.")
    if inp.lights == "all":
        assumptions.append(
            f"조명은 전용 {p.m2_per_light[kind]}㎡에 하나({LIGHT_NAME[kind]})로 잡았어요. "
            "실측 때 방마다 다시 세요."
        )
    if inp.outlets == "all":
        assumptions.append(
            f"콘센트는 전용 {p.m2_per_outlet}㎡에 하나, 스위치는 {p.m2_per_switch}㎡에 하나로 "
            "잡았어요. 실측 때 다시 세요."
        )
    elif inp.outlets == "some":
        assumptions.append(
            f"고른 개수는 {p.switch_share}개 중 하나를 스위치, 나머지를 콘센트로 나눴어요."
        )
    if n_outlet or n_switch:
        assumptions.append(
            "콘센트 · 스위치 설치 단가와 품은 새 아파트를 지을 때 기준이라, "
            "기존 자리에서 바꾸기만 하면 업체 견적이 더 낮고 짧을 수 있어요."
        )
    if n_light:
        assumptions.append("조명 기구와 설치는 공공 단가가 없어 보급형 제품 기준 팀 가정값이에요.")
    if points:
        assumptions.append(
            f"새 자리 하나에 배관 {p.run_m}m · 전선 {p.wires}가닥을 끄는 것으로 잡았어요. "
            "새 자리에는 콘센트를 단다고 봤어요."
        )
    assumptions.append(f"하루 전기 기사 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return ElectricQuote(
        version=p.version,
        lights=n_light,
        outlets=n_outlet,
        switches=n_switch,
        new_points=points,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_wire + md_fit),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )

"""전기 · 조명 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

콘센트 설치 · 전선관 · 전선 · 박스는 표준시장단가 공동주택(신축) 값이고, 콘센트 · 스위치 자재는 조달청 값이다.
조명기구와 그 설치, 스위치 설치는 공공 단가가 없어 팀 가정값이다(스위치 설치는 콘센트 설치 단가를 준용).
"""

from decimal import Decimal

from app.calc.electric import ElectricPrices

_WAGE_ELECTRICIAN = 276_108  # 내선전공 2026.9.1 시중노임단가 (대한건설협회)

ELECTRIC_2026H2 = ElectricPrices(
    version="2026H2",
    light={"flat": 60_000, "downlight": 15_000, "line": 50_000},
    light_install={"flat": 20_000, "downlight": 15_000, "line": 30_000},
    outlet=1_502,
    switch=1_887,
    device_install=23_595,  # 재료 2,482 + 노무 21,113
    conduit=8_953,  # 재료 422 + 노무 8,531
    cable=2_763,  # 재료 612 + 노무 2,151
    box=36_761,  # 재료 2,519 + 노무 34,242
    m2_per_light={"flat": Decimal("6.0"), "downlight": Decimal("2.5"), "line": Decimal("4.0")},
    m2_per_outlet=Decimal("2.5"),
    m2_per_switch=Decimal("5.0"),
    switch_share=3,
    run_m=Decimal(6),
    wires=3,
    supply_per_exclusive=Decimal("1.2"),
    md_light={"flat": Decimal("0.15"), "downlight": Decimal("0.1"), "line": Decimal("0.15")},
    md_device=Decimal(21_113) / Decimal(_WAGE_ELECTRICIAN),
    md_point=Decimal("0.3"),
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "light_flat": "팀 가정값 (조명기구는 공공 가격이 없어요 · LED 평판 보급형 기준)",
        "light_downlight": "팀 가정값 (조명기구는 공공 가격이 없어요 · 다운라이트 보급형 기준)",
        "light_line": "팀 가정값 (조명기구는 공공 가격이 없어요 · 라인 조명 한 줄 기준)",
        "light_install": "팀 가정값 (조명 설치는 공공 단가가 없어요)",
        "outlet": "조달청 가격정보 2026-10 · 콘센트 매입 접지 2구 + 표준시장단가 2026 하반기 · "
        "공동주택 콘센트 2구 설치 (신축 기준)",
        "switch": "조달청 가격정보 2026-10 · 스위치 2구 + 팀 가정 설치 (공공 단가가 없어 "
        "콘센트 설치 단가를 준용)",
        "conduit": "표준시장단가 2026 하반기 · 공동주택 합성수지제 가요전선관 CD 16㎜ 매입 (신축 기준)",
        "cable": "표준시장단가 2026 하반기 · 공동주택 절연전선 HFIX 2.5㎟ 구내 (신축 기준)",
        "box": "표준시장단가 2026 하반기 · 공동주택 콘센트 박스 PVC 54mm (신축 기준)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)

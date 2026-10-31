"""창호 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

PVC 창호 설치 · 복층유리 · 유리 끼우기 · 실리콘은 공공 단가가 있다. 가장 큰 비용인 창틀 · 창짝 자재와
알루미늄 시스템창(자재 · 설치)은 공공 가격이 없어 팀 가정값이다.
"""

from decimal import Decimal

from app.calc.window import WindowPrices

# 2026.9.1 시중노임단가 (대한건설협회)
_WAGE_WINDOW = 248_547  # 창호공
_WAGE_GLASS = 258_602  # 유리공

WINDOW_2026H2 = WindowPrices(
    version="2026H2",
    frame={"pvc": 100_000, "system": 400_000},
    pvc_install=103_673,  # 재료 3,111 + 노무 100,562
    glass={"low_e": 51_645, "clear": 35_721},
    glass_install=25_807,  # 재료 775 + 노무 25,032
    caulk=3_713,
    window_m2=Decimal("4.3"),
    m2_per_window=Decimal("10.0"),
    ext_fewer=2,
    glass_share=Decimal("0.75"),
    glass_layers={"pvc": 2, "system": 1},
    seal_m=Decimal("8.4"),
    supply_per_exclusive=Decimal("1.2"),
    md_remove=Decimal("0.2"),
    md_frame={"pvc": Decimal(100_562) / Decimal(_WAGE_WINDOW), "system": Decimal("0.6")},
    md_glass=Decimal(25_032) / Decimal(_WAGE_GLASS),
    crew=4,
    vat_rate=Decimal("0.1"),
    sources={
        "frame_pvc": "팀 가정값 (PVC 창틀 · 창짝 자재는 공공 가격이 없어요 · 보급형 기준)",
        "frame_system": "팀 가정값 (알루미늄 시스템창은 공공 단가가 없어요 · 자재 · 설치 포함)",
        "pvc_install": "표준시장단가 2026 하반기 · 합성수지 창호 설치 미서기 이중창 3.0~6.0㎡",
        "glass_low_e": "조달청 가격정보 2026-10 · 복층유리 로이 24mm",
        "glass_clear": "조달청 가격정보 2026-10 · 복층유리 투명 24mm",
        "glass_install": "표준시장단가 2026 하반기 · 복층유리 설치 공동주택 24mm 이하",
        "seal": "표준시장단가 2026 하반기 · 수밀코킹 삼각 폭 15mm 이하 (재료 제외)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)

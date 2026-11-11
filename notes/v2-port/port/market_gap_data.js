const PUB_EQ = { // 공공 기준과 같은 값: '다른 이유'를 한 단계씩 바꿔 볼 출발점
  dobae: { area_factor: { silk: 2.5, hapji: 2.5 }, ceiling_share: 0.25, labor_mult: { silk: 1, hapji: 1 }, paper: { silk: 3325, hapji: 1300 }, sub_per_py: { silk: 2200, hapji: 2200 }, occupied_mult: 0.169, min_job: 0 },
  mokgong: { molding_m: 11468, base_m: 5837, door_set: 365942, door_leaf: 191170, doors_default: (py) => roomsFor(py), base_only_min: 0, removal_lump: 0, overhead: 0 }
};
const GAP_STEPS = {
  dobae: [
    ["area_factor", "도배 면적", "공공은 공급면적 × 2.5로 잡고, 시장은 실제 롤 수 관행(평당 0.5롤 정도)으로 잡아요."],
    ["ceiling_share", "천장 비중", "벽 · 천장 롤이 나뉜 견적을 보면 천장이 37% 정도예요(공공 25%). 천장은 시공비가 비싸요."],
    ["labor_mult", "시공 품", "합지는 실크보다 빨리 붙여서 시장 품이 절반 정도예요. 공공 기준은 벽지 종류를 나누지 않아요."],
    ["paper", "벽지 값", "실크는 시장 도매가가 조달청 가격보다 낮고, 합지는 비슷해요."],
    ["sub_per_py", "초배 · 풀 · 부자재", "시장 견적의 부자재가 공공 초배지 계산보다 많아요."],
    ["occupied_mult", "짐 있는 집", "공공 기준은 노무비를 16.9% 올리지만, 실견적에서는 짐 있다고 크게 더 받지 않았어요."],
    ["min_job", "최소 금액", "작은 집은 업체마다 최소 금액이 있어요."]
  ],
  mokgong: [
    ["molding_m", "몰딩 m당 값", "시장 평몰딩은 시공 + 자재 m당 1만~1.6만 원이에요."],
    ["door_set", "방문 한 짝 값", "문틀 포함 시장가는 30만~46만 원(가운데 40만 원)이에요."],
    ["door_leaf", "문짝만 값", "문짝만은 17만~25만 원이에요."],
    ["doors_default", "방문 개수", "표준견적서는 방 문만 세고, 시장 견적은 욕실 문까지 세요."],
    ["base_only_min", "걸레받이만 할 때 최소 금액", "걸레받이만 하면 35만~50만 원을 최소로 받아요."]
  ]
};

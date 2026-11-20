// 믿집 백과 용어 사전 데이터(자동 생성 · 손으로 고치지 않아요).
// 원본: 용어집 백업(backup-20261120-glossary, wt-guide feat-quote-guide) + 고칠 표시 36개를 고친 것.
// 그림은 AI로 그린 이해용 그림이에요(화면에 그렇게 적어요). 출처는 공공 기관 · 법령 · 제조사만 보여요.
import type { Term } from "./types";

export const TERMS: Term[] = [
 {
  "id": "초배",
  "term": "초배",
  "aliases": [
   "밑바름",
   "초배지 바르기"
  ],
  "trade": "dobae",
  "easy": "겉 벽지를 붙이기 전에 바탕에 먼저 붙이는 종이 · 부직포",
  "tip": "겉 벽지 밑작업이에요. 실크는 부직포 초배가 꼭 필요하고, 합지는 기존 합지 위면 생략하기도 해요.",
  "detail": "벽 요철과 이음을 고르고 겉 벽지가 잘 붙게 하는 밑작업이에요. 실크는 부직포 초배가 필수이고, 합지는 기존 합지 위라면 생략할 수 있어요.",
  "use": "겉 벽지 아래에 깔아 벽 요철을 고르고 벽지가 잘 붙게 해요.",
  "images": [
   {
    "src": "/guide-img/terms/underlay_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/underlay_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   },
   {
    "title": "[초급] 벽지 시공 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/109"
   }
  ]
 },
 {
  "id": "정배",
  "term": "정배",
  "aliases": [
   "정배지",
   "겉지 바르기"
  ],
  "trade": "dobae",
  "easy": "눈에 보이는 마지막 벽지를 붙이는 작업",
  "tip": "마지막 벽지를 붙이는 작업이에요. 보통 천장을 먼저, 벽을 나중에 붙여요.",
  "detail": "초배가 끝난 뒤 실제 벽지를 붙이는 단계예요. 천장을 먼저, 벽을 나중에 붙이는 것이 일반적이고 붙이면서 솔이나 롤러로 공기를 빼요.",
  "use": "초배를 끝낸 벽 · 천장에 눈에 보이는 마지막 벽지를 붙일 때 해요.",
  "images": [
   {
    "src": "/guide-img/terms/jeongbae_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/jeongbae_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   }
  ]
 },
 {
  "id": "띄움-시공",
  "term": "띄움 시공",
  "aliases": [
   "공간 초배",
   "공간 붙임",
   "갓둘레 붙임",
   "띄움 초배"
  ],
  "trade": "dobae",
  "easy": "가장자리만 풀을 발라 벽에서 살짝 띄워 붙이는 초배 방법",
  "tip": "초배를 띄워 붙이는 방법이에요. 실크 · 평탄화한 천장 · 간접조명 아래면 이 방법으로 해요.",
  "detail": "부직포 가장자리(표준시방서 좌우 70~100mm, 현장 교재 약 10cm)에만 풀을 발라요. 벽 요철이 덜 비치고, 간접조명 아래나 평탄화한 천장에는 특히 필요해요.",
  "use": "벽 요철이 비치지 않게 할 때 써요. 실크 · 평탄화한 천장 · 간접조명 아래에 특히 필요해요.",
  "images": [
   {
    "src": "/guide-img/terms/floating_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/floating_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   },
   {
    "title": "라이프데일리코리아 도배 공정 가이드",
    "publisher": "라이프데일리코리아(공테)",
    "url": "https://lifedailykorea.com/process/dobae/"
   },
   {
    "title": "얼마드나 우물천장 비용 단가표",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/coffered-ceiling-cost"
   }
  ]
 },
 {
  "id": "밀착-초배",
  "term": "밀착 초배",
  "aliases": [
   "온통 붙임",
   "온통풀칠 초배",
   "베다 초배"
  ],
  "trade": "dobae",
  "easy": "초배지 전체에 풀을 발라 바탕에 바짝 붙이는 방법",
  "tip": "초배지를 바짝 붙이는 방법이에요. 주로 합지 시공에 쓰고, 실크는 띄움 시공을 해요.",
  "detail": "바탕 전체에 초배지를 밀착해 붙여요. 합지 시공에 주로 쓰고, 밀착이라 벽 요철이 그대로 드러나기 쉬워요.",
  "use": "합지를 바를 때 초배지를 벽에 바짝 붙여 바탕을 만들 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/full_adhesion_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   },
   {
    "title": "시공백과 열여섯번째: 도배 공사",
    "publisher": "디자인 담결",
    "url": "https://www.damgyeol.com/5/?bmode=view&idx=86952313"
   }
  ]
 },
 {
  "id": "봉투-바름",
  "term": "봉투 바름",
  "aliases": [
   "봉투 붙임",
   "물바름",
   "미쯔바리",
   "이중풀칠"
  ],
  "trade": "dobae",
  "easy": "작은 초배지의 가장자리 위주로 풀을 발라 붙이는 초배 공법",
  "tip": "작은 초배지를 가장자리 위주로 붙이는 방법이에요. 요철 있는 바탕을 평평하게 만들 때 써요.",
  "detail": "표준시방서는 300×450mm 종이 네 변에 3~5mm 폭으로 접착제를 바른다고 하고, 현장 교재는 가장자리 10~13cm 되풀칠 · 속 물칠로 설명해 자료마다 달라요. 요철이 있어도 평활면을 얻기 쉬워요.",
  "use": "요철이 있는 바탕에서도 평평한 면을 얻으려고 작은 초배지를 붙일 때 써요.",
  "ask": "봉투 바름으로 하나요? 풀은 어디까지 바르나요?",
  "images": [
   {
    "src": "/guide-img/terms/envelope_paste_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/envelope_paste_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   }
  ]
 },
 {
  "id": "갈램막이",
  "term": "갈램막이",
  "aliases": [
   "틈막이 초배",
   "틈·갈램막이"
  ],
  "trade": "dobae",
  "easy": "석고보드 이음이나 틈에만 좁게 붙이는 초배",
  "tip": "석고보드 이음만 막는 초배예요. 보드 이음이 있는 벽 · 천장에 해요.",
  "detail": "보드 조인트와 구멍에 한지 · 부직포를 띠처럼 붙여 이음을 막아요. 폭은 표준시방서 60~70mm, 현장 교재 겉지 8~10cm로 자료마다 조금 달라요.",
  "use": "석고보드 이음과 구멍을 막아 벽지에 이음 자국이 비치지 않게 할 때 써요.",
  "ask": "석고보드 이음은 어떤 초배로 막나요?",
  "images": [
   {
    "src": "/guide-img/terms/joint_strip_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/joint_strip_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   },
   {
    "title": "2026 건설공사 표준품셈(건축 5-3-7 도배바름·유지관리 도배 해체·교체)",
    "publisher": "국토교통부(한국표준품셈정보원 배포)",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=64699193400142&pgno=1"
   }
  ]
 },
 {
  "id": "운용지",
  "term": "운용지",
  "aliases": [
   "단지",
   "싱",
   "심걸이"
  ],
  "trade": "dobae",
  "easy": "부직포 위 이음매 자리에 세로로 덧대는 보강 종이",
  "tip": "실크 이음 밑 보강지예요. 부직포 초배를 할 때 이음 자리에 덧대요.",
  "detail": "실크 이음매 밑을 보강해 이음 벌어짐과 배꼽짐을 줄여요. LH 시방서는 노출콘크리트 벽에 실크를 바를 때 폭 20cm 한지 초배로 정해요.",
  "use": "실크 이음매 밑을 보강해 이음 벌어짐과 풀 자국을 줄일 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/seam_backer_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/seam_backer_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   },
   {
    "title": "도배의 민족 고양캠프(부직포 vs 텍스, 배꼽짐)",
    "publisher": "도배의 민족",
    "url": "https://altgoodsave.co.kr/new-%EC%86%8C%EC%8B%9D/?pageid=4&mod=document&uid=8"
   }
  ]
 },
 {
  "id": "부직포-초배",
  "term": "부직포 초배",
  "aliases": [
   "부직포"
  ],
  "trade": "dobae",
  "easy": "천처럼 생긴 부직포를 실크 밑에 띄워 붙이는 초배",
  "tip": "실크 밑 초배예요. 실크를 고르면 이 방식으로 해요.",
  "detail": "실크 벽지 밑에 띄워 붙여 벽 요철을 덜 보이게 해요. LH 시방서는 40g/㎡ 부직포를 기준으로 하고, 이음부에는 운용지를 덧대요.",
  "use": "실크 벽지 밑에 띄워 붙여 벽 요철이 덜 보이게 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/nonwoven_b.webp",
    "kind": "입체 그림"
   }
  ],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   },
   {
    "title": "도배의 민족 고양캠프(부직포 vs 텍스, 배꼽짐)",
    "publisher": "도배의 민족",
    "url": "https://altgoodsave.co.kr/new-%EC%86%8C%EC%8B%9D/?pageid=4&mod=document&uid=8"
   }
  ]
 },
 {
  "id": "삼중지",
  "term": "삼중지",
  "aliases": [
   "보수 초배",
   "건식삼중지"
  ],
  "trade": "dobae",
  "easy": "몰딩 아래 · 걸레받이 라인의 단차를 고르는 보수 초배지",
  "tip": "몰딩 · 걸레받이 라인 보수 초배예요. 퍼티보다 빠른 보수라 요즘은 건식삼중지를 주로 써요.",
  "detail": "천장 몰딩 바로 아래에 가로로 붙여 위아래 요철을 보수해요. 퍼티보다 빠른 보수 방법으로 쓰이고, 요즘은 습식이중지 대신 건식삼중지를 주로 써요.",
  "use": "천장 몰딩 아래 · 걸레받이 라인의 단차를 빠르게 고를 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/repair_paper_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/repair_paper_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "시공백과 열여섯번째: 도배 공사",
    "publisher": "디자인 담결",
    "url": "https://www.damgyeol.com/5/?bmode=view&idx=86952313"
   }
  ]
 },
 {
  "id": "네바리",
  "term": "네바리",
  "aliases": [
   "습식이중지",
   "뜸막이 초배"
  ],
  "trade": "dobae",
  "easy": "현장에서 두 가지 뜻으로 쓰는 도배 초배 용어",
  "tip": "현장 초배 용어예요. 뜻이 두 가지라 업체가 쓰면 어느 뜻인지 물어봐요.",
  "detail": "자료에 따라 ① 습식이중지(장마철에 잘 들떠 요즘은 건식삼중지를 주로 씀) ② 보수 · 틈막이 · 뜸막이 초배를 뜻해요. 업체가 이 말을 쓰면 어느 뜻인지 확인해요.",
  "use": "",
  "ask": "말씀하신 네바리가 습식이중지인가요, 틈막이 초배인가요?",
  "images": [],
  "sources": []
 },
 {
  "id": "합지",
  "term": "합지",
  "aliases": [
   "합지벽지",
   "종이 벽지"
  ],
  "trade": "dobae",
  "easy": "종이 두 겹을 붙여 만든 저렴한 벽지",
  "tip": "종이 벽지예요. 비용을 줄이거나 짧게 살 집이면 보통 합지를 골라요.",
  "detail": "겹침 시공이라 이음 줄이 보일 수 있고 물걸레 청소에 약해요. 기존 합지 위라면 덧방할 수 있어 철거 · 퍼티 · 초배를 줄일 수 있어요.",
  "use": "도배 비용을 줄이고 싶을 때나 짧게 살 집에 많이 써요.",
  "images": [
   {
    "src": "/guide-img/terms/paper_vs_silk_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/paper_vs_silk_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "[초급] 벽지 시공 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/109"
   }
  ]
 },
 {
  "id": "소폭-합지",
  "term": "소폭 합지",
  "aliases": [
   "소폭",
   "53cm 합지"
  ],
  "trade": "dobae",
  "easy": "폭 약 53cm의 좁은 합지",
  "tip": "가장 싼 합지예요. 이음 줄이 약 50cm마다 보여요.",
  "detail": "가장 저렴하지만 이음이 많아 약 50cm 간격으로 겹친 줄이 보여요.",
  "use": "가장 싸게 도배할 때 써요. 이음 줄이 촘촘히 보여요.",
  "images": [
   {
    "src": "/guide-img/terms/narrow_vs_wide_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/narrow_vs_wide_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/narrow_vs_wide_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "라이프데일리코리아 도배 공정 가이드",
    "publisher": "라이프데일리코리아(공테)",
    "url": "https://lifedailykorea.com/process/dobae/"
   }
  ]
 },
 {
  "id": "광폭-합지",
  "term": "광폭 합지",
  "aliases": [
   "광폭",
   "광폭합지",
   "93cm 합지"
  ],
  "trade": "dobae",
  "easy": "폭 약 93cm의 넓은 합지",
  "tip": "넓은 합지예요. 합지를 고를 때 이음 줄을 줄이고 싶으면 이쪽을 골라요.",
  "detail": "소폭보다 이음이 적어 겹친 줄이 약 90cm 간격으로 보여요. LX 제품 기준 93cm×17.75m, 롤당 약 16.5㎡예요.",
  "use": "합지를 쓰되 이음 줄을 줄이고 싶을 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/narrow_vs_wide_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/narrow_vs_wide_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/narrow_vs_wide_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 합지 휘앙세93 49605-01",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/101019"
   }
  ]
 },
 {
  "id": "실크-벽지",
  "term": "실크 벽지",
  "aliases": [
   "실크",
   "실크벽지",
   "PVC 벽지"
  ],
  "trade": "dobae",
  "easy": "종이 위에 PVC를 코팅한 벽지(실크 성분은 없어요)",
  "tip": "코팅 벽지예요. 오래 살고 물걸레 청소가 중요하면 보통 실크를 골라요.",
  "detail": "맞댐 시공이라 이음이 거의 안 보이고 물걸레 청소가 돼요. 기존 벽지 철거, 퍼티, 부직포 띄움 초배가 필요해 합지보다 공정이 길어요.",
  "use": "이음이 덜 보이고 물걸레로 닦을 수 있는 마감을 원할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/paper_vs_silk_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/paper_vs_silk_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 실크 베스띠 샌드스톤 82558-02",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/101329"
   },
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   }
  ]
 },
 {
  "id": "프리미엄-실크",
  "term": "프리미엄 실크",
  "aliases": [
   "딥엠보 실크",
   "고급 실크"
  ],
  "trade": "dobae",
  "easy": "무늬층이 깊고 두꺼운 고급 실크",
  "tip": "두꺼운 고급 실크예요. 시공은 일반 실크와 같고, 질감 · 내구성을 원할 때 골라요.",
  "detail": "두께감 덕분에 벽면 커버리지가 좋다고 소개되고 표면이 단단해 생활 스크래치가 덜해요. 시공 방식은 일반 실크와 같다고 보고, 가격은 제조사가 공개하지 않아요.",
  "use": "두께감 있는 무늬와 단단한 표면을 원할 때 일반 실크 대신 골라요.",
  "images": [
   {
    "src": "/guide-img/terms/premium_silk_b.webp",
    "kind": "입체 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 디아망 모던회벽 PR028-01",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/13396"
   },
   {
    "title": "LX Z:IN 관리하기 쉬운 벽지 선택 기준",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/8949?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "천장지",
  "term": "천장지",
  "aliases": [
   "천정지",
   "천장 벽지"
  ],
  "trade": "dobae",
  "easy": "천장에 따로 쓰는 벽지",
  "tip": "천장용 벽지예요. 보통 벽과 따로 천장지를 써요.",
  "detail": "천장은 벽과 따로 천장지를 쓰는 관행이 있어요. 실크라도 천장은 밀착, 벽은 띄움으로 시공한다고 밝힌 업체가 있어요.",
  "use": "벽과 따로 천장에 붙이는 벽지예요. 밝고 무늬가 적은 것을 많이 써요.",
  "images": [
   {
    "src": "/guide-img/terms/ceiling_paper_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "당근 비즈프로필 '구름도배'",
    "publisher": "당근",
    "url": "https://daangn.com/kr/local-profile/%EA%B5%AC%EB%A6%84%EB%8F%84%EB%B0%B0-eqqqokh8dmr1/"
   },
   {
    "title": "LX Z:IN 실크벽지 카테고리",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/category/a070000?mcate=a070300"
   }
  ]
 },
 {
  "id": "뮤럴-벽지",
  "term": "뮤럴 벽지",
  "aliases": [
   "벽화 벽지",
   "그림 벽지",
   "전폭 벽지"
  ],
  "trade": "dobae",
  "easy": "큰 그림을 여러 폭에 나눠 인쇄해 한 벽을 채우는 벽지",
  "tip": "큰 그림 벽지예요. 한 벽 포인트로 쓰고, 주문 생산이라 미리 발주해요.",
  "detail": "LX 뮤럴은 3m×2.4m 세트를 주문생산해요. 리드타임이 있어 발주를 앞당기고, 그림 순서대로 맞춰 붙여요.",
  "use": "거실 한 벽을 큰 그림으로 꾸미고 싶을 때 써요. 주문 생산이라 미리 발주해요.",
  "images": [
   {
    "src": "/guide-img/terms/mural_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/mural_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 뮤럴 범내려온다 M534-01",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/13901"
   },
   {
    "title": "[초급] 벽지 시공 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/109"
   }
  ]
 },
 {
  "id": "방염-벽지",
  "term": "방염 벽지",
  "aliases": [
   "방염지"
  ],
  "trade": "dobae",
  "easy": "불이 잘 번지지 않게 처리한 벽지",
  "tip": "불이 덜 번지는 벽지예요. 아파트는 의무가 아니라 필요할 때만 골라요.",
  "detail": "호텔 · 병원 같은 다중이용시설에 쓰는 제품이에요. 아파트 세대는 방염 의무 대상이 아니어서 선택 기능으로 봐요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "한국화재보험협회 자료(방염 대상)",
    "publisher": "한국화재보험협회",
    "url": "https://kfpa.or.kr/mem/pdf_file/H/130/H130_18.pdf"
   },
   {
    "title": "[초급] 벽지 시공 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/109"
   }
  ]
 },
 {
  "id": "수입-벽지",
  "term": "수입 벽지",
  "aliases": [
   "수입지",
   "패브릭 벽지"
  ],
  "trade": "dobae",
  "easy": "해외에서 만든 벽지로, 롤당 면적이 작은 편",
  "tip": "해외 벽지예요. 롤 수가 약 3배 들고 전문 시공자가 필요해 비용이 높아요.",
  "detail": "롤당 약 5㎡로 국산(약 16.5㎡)의 3분의 1 수준이라 롤 수가 약 3배 들어요. 풀칠 방식이 제품마다 달라 전문 시공자가 필요해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN [초급] 마감재 소요량 계산법",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/641"
   },
   {
    "title": "Resene Wallpaper information",
    "publisher": "Resene",
    "url": "https://www.resene.co.nz/homeown/Habitat-plus/09-wallpaper-information.htm"
   },
   {
    "title": "Non-woven paste-the-wall 설치 가이드",
    "publisher": "vinylwalls",
    "url": "https://vinylwalls-com.pages.dev/blog/non-woven-wallpaper-paste-wall-installation-guide/"
   }
  ]
 },
 {
  "id": "덧방",
  "term": "덧방",
  "aliases": [
   "겹쳐 바르기",
   "덧대기"
  ],
  "trade": "common",
  "easy": "기존 마감을 뜯지 않고 그 위에 새로 덧대는 것",
  "tip": "기존 마감 위에 새로 덧대는 일이에요. 기존 합지 위 합지는 되지만, 실크 위에는 하지 않아요.",
  "detail": "도배에서는 기존 합지 위에 새 합지를 바르는 것을 말하고, 실크 · 코팅 벽지 위에는 하지 않아요. 목공에서는 기존 벽 · 천장 위에 석고보드를 덧대는 것을 말해요.",
  "use": "기존 마감을 뜯지 않고 그 위에 새로 덧대 비용 · 시간을 줄일 때 해요.",
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "[초급] 벽지의 세계 ② 도배 외 LX 벽지 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/865"
   }
  ]
 },
 {
  "id": "맞댐-시공",
  "term": "맞댐 시공",
  "aliases": [
   "맞대기",
   "맞댄이음",
   "맞댐이음"
  ],
  "trade": "dobae",
  "easy": "벽지 끝을 겹치지 않고 딱 맞대어 붙이는 방법",
  "tip": "이음을 맞대 붙이는 방법이에요. 실크는 기본으로 이렇게 붙여요.",
  "detail": "실크 벽지의 기본 이음 방식이라 이음이 거의 안 보여요. LH 시방서는 맞댄이음을 원칙으로 하고 부득이 겹치면 6mm 이하로 정해요.",
  "use": "실크 벽지를 이음이 안 보이게 붙일 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/butt_vs_overlap_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   },
   {
    "title": "라이프데일리코리아 도배 공정 가이드",
    "publisher": "라이프데일리코리아(공테)",
    "url": "https://lifedailykorea.com/process/dobae/"
   }
  ]
 },
 {
  "id": "겹침-시공",
  "term": "겹침 시공",
  "aliases": [
   "겹침이음",
   "겹쳐 붙이기"
  ],
  "trade": "dobae",
  "easy": "벽지 끝을 조금 겹쳐 붙이는 방법",
  "tip": "이음을 겹쳐 붙이는 방법이에요. 합지는 기본으로 이렇게 붙여요.",
  "detail": "합지의 기본 이음 방식이에요. 겹친 줄이 소폭은 약 50cm, 광폭은 약 90cm 간격으로 보이는 것은 정상이에요.",
  "use": "합지를 붙일 때 기본으로 써요. 겹친 줄이 보이는 건 정상이에요.",
  "images": [
   {
    "src": "/guide-img/terms/butt_vs_overlap_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   }
  ]
 },
 {
  "id": "이음선",
  "term": "이음선",
  "aliases": [
   "이음매",
   "맞물림선",
   "하구찌",
   "맞대음선"
  ],
  "trade": "dobae",
  "easy": "벽지와 벽지가 만나는 선",
  "tip": "벽지 폭이 만나는 선이에요. 합지는 겹친 줄이 보이는 게 정상이고, 실크 이음이 벌어지면 A/S 대상이에요.",
  "detail": "합지는 겹친 줄이, 실크는 맞댄 선이 생겨요. 실크 이음이 눈에 띄게 벌어지거나 들뜨면 A/S 대상으로 봐요.",
  "use": "벽지 두 폭이 만나는 곳이에요. 벌어지거나 들뜨는지 검수할 때 봐요.",
  "images": [
   {
    "src": "/guide-img/terms/seam_line_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/seam_line_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   }
  ]
 },
 {
  "id": "퍼티",
  "term": "퍼티",
  "aliases": [
   "핸디코트"
  ],
  "trade": "common",
  "easy": "벽 구멍 · 요철을 메워 평평하게 만드는 반죽",
  "tip": "벽 요철을 메우는 작업이에요. 부분 퍼티인지 전체(올퍼티)인지 견적에서 확인해요.",
  "detail": "메운 뒤 사포로 갈아 평평하게 해요. LX 공정표는 퍼티 후 도배까지 2일 간격을 두라고 하고, 부분인지 전면인지 범위를 견적에서 확인해요.",
  "use": "도배 · 몰딩 전에 벽 구멍과 요철을 메워 바탕을 평평하게 해요.",
  "images": [
   {
    "src": "/guide-img/terms/putty_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/putty_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/putty_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   },
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   },
   {
    "title": "도배가격",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/도배가격/"
   }
  ]
 },
 {
  "id": "올퍼티",
  "term": "올퍼티",
  "aliases": [
   "전면 퍼티"
  ],
  "trade": "common",
  "easy": "벽 · 천장 전체에 퍼티를 바르는 작업",
  "tip": "벽 · 천장 전체 퍼티 작업이에요. 도장 · 간접조명 벽에 하고, 말리는 만큼 기간이 늘어요.",
  "detail": "도장 마감이나 간접조명으로 벽 굴곡이 드러나는 곳에 필요해요. 퍼티마다 하루씩 말려 범위에 따라 4~7일이 걸린다는 자료가 있어요.",
  "use": "도장 마감이나 간접조명 아래처럼 벽 굴곡이 드러나는 곳을 평평하게 할 때 해요.",
  "images": [
   {
    "src": "/guide-img/terms/full_putty_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/full_putty_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCC 석고보드 표준시방서",
    "publisher": "KCC",
    "url": "https://www.kccworld.co.kr/data/product/KCC_석고보드_시방서.pdf"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "실러",
  "term": "실러",
  "aliases": [
   "에멀션 실러"
  ],
  "trade": "dobae",
  "easy": "바탕에 바르는 접착 보조 도료",
  "tip": "바탕 도료예요. 퍼티한 면이나 흡수가 큰 보드에 벽지 전에 발라요.",
  "detail": "퍼티한 면이나 흡수성이 큰 보드에 얼룩 없이 발라 벽지가 고르게 붙게 해요. 표준시방서는 에멀션형을 원칙으로 해요.",
  "use": "퍼티한 면 · 흡수가 큰 보드에 발라 벽지가 고르게 붙게 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/sealer_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/sealer_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   }
  ]
 },
 {
  "id": "코너비드",
  "term": "코너비드",
  "aliases": [
   "코너 비드"
  ],
  "trade": "common",
  "easy": "모서리를 곧고 단단하게 잡아 주는 보강재",
  "tip": "모서리 보강재예요. 실크 바탕 · 무몰딩 모서리에 함께 써요.",
  "detail": "실크 바탕 만들기나 무몰딩 아웃코너 마감에 퍼티와 함께 써요. 모서리 깨짐과 크랙을 줄여요.",
  "use": "튀어나온 벽 모서리를 곧고 단단하게 잡아 깨짐 · 크랙을 줄여요.",
  "images": [
   {
    "src": "/guide-img/terms/corner_bead_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/corner_bead_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "조인트-테이프",
  "term": "조인트 테이프",
  "aliases": [
   "망사테이프",
   "메쉬테이프"
  ],
  "trade": "common",
  "easy": "석고보드 이음이나 균열 위에 붙이는 보강 테이프",
  "tip": "보드 이음 보강 테이프예요. 석고보드 이음에 붙이고 퍼티로 덮어요.",
  "detail": "이음 위에 붙이고 퍼티(콤파운드)로 덮어 크랙을 막아요. 제조사 시방은 하도 · 중도 · 상도로 여러 번 바르고 충분히 말린 뒤 마감하라고 해요.",
  "use": "석고보드 이음 · 균열 위에 붙여 크랙이 다시 생기지 않게 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/joint_tape_b.webp",
    "kind": "입체 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   },
   {
    "title": "KCC 석고보드 표준시방서",
    "publisher": "KCC",
    "url": "https://www.kccworld.co.kr/data/product/KCC_석고보드_시방서.pdf"
   }
  ]
 },
 {
  "id": "오픈타임",
  "term": "오픈타임",
  "aliases": [
   "풀 오픈타임",
   "불림 시간"
  ],
  "trade": "dobae",
  "easy": "벽지에 풀을 바른 뒤 붙이기까지 허용되는 시간",
  "tip": "풀을 바른 뒤 붙이기까지 시간이에요. 넘기면 울음 · 주름이 생겨요.",
  "detail": "LX 기준 합지는 10~20분, 실크는 10분 안에 붙여요. 시간을 넘기면 울음 · 주름이 생기기 쉬워요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "[초급] 벽지 시공 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/109"
   },
   {
    "title": "라이프데일리코리아 도배 공정 가이드",
    "publisher": "라이프데일리코리아(공테)",
    "url": "https://lifedailykorea.com/process/dobae/"
   }
  ]
 },
 {
  "id": "로트-번호",
  "term": "로트 번호",
  "aliases": [
   "LOT",
   "로트",
   "생산 로트"
  ],
  "trade": "dobae",
  "easy": "벽지가 함께 생산된 묶음 번호",
  "tip": "생산 묶음 번호예요. 같은 로트로 왔는지 반입 때 확인해요.",
  "detail": "로트가 다르면 같은 품번이라도 색이 조금 다를 수 있어요. 같은 로트로 발주하고 반입할 때 라벨과 수량을 확인해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "KCS 41 51 05 도배공사 · KCS 41 51 01 수장공사 일반(2021)",
    "publisher": "국토교통부(대한건축사협회 합본 경유)",
    "url": "https://kirahub.kira.or.kr/KCS%2041%2000%2000%20%EA%B1%B4%EC%B6%95%EA%B3%B5%EC%82%AC%20%ED%91%9C%EC%A4%80%EC%8B%9C%EB%B0%A9%EC%84%9C%20(%ED%95%A9%EB%B3%B8).pdf"
   }
  ]
 },
 {
  "id": "무늬-맞춤",
  "term": "무늬 맞춤",
  "aliases": [
   "패턴 매치",
   "리피트"
  ],
  "trade": "dobae",
  "easy": "이음에서 벽지 무늬가 이어지게 맞추는 것",
  "tip": "무늬를 이어 붙이는 작업이에요. 무늬를 맞추느라 버리는 자재가 생겨요.",
  "detail": "랜덤 · 스트레이트 · 하프드롭 유형이 있고 맞추느라 잘라 내는 양(로스)이 생겨요. 로스 비율은 자료마다 달라요.",
  "use": "무늬 있는 벽지를 이음에서 끊기지 않게 이어 붙일 때 해요.",
  "ask": "무늬를 맞추느라 롤을 얼마나 더 잡았나요?",
  "images": [
   {
    "src": "/guide-img/terms/pattern_match_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/pattern_match_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "Tempaper 무늬 맞춤 유형 차이",
    "publisher": "Tempaper",
    "url": "https://tempaper.com/blogs/news/the-differences-between-wallpaper-match-types"
   },
   {
    "title": "Materio 벽지 계산기",
    "publisher": "Materio",
    "url": "https://materio.co/wallpaper-calculator"
   }
  ]
 },
 {
  "id": "하프드롭",
  "term": "하프드롭",
  "aliases": [
   "하프 드롭",
   "드롭 매치"
  ],
  "trade": "dobae",
  "easy": "폭마다 무늬가 반 리피트씩 어긋나는 패턴",
  "tip": "무늬가 반씩 어긋나는 벽지예요. 맞춤 로스가 커서 롤을 넉넉히 잡아요.",
  "detail": "대각선 흐름이 생기는 무늬라 맞춤 로스가 커요. 해외 업계 자료끼리도 로스를 약 15~20%와 20~30%로 다르게 적어요.",
  "use": "대각선 흐름이 있는 무늬 벽지예요. 맞추느라 자재가 더 들어요.",
  "ask": "하프드롭 무늬라 롤을 얼마나 넉넉히 잡았나요?",
  "images": [
   {
    "src": "/guide-img/terms/half_drop_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/half_drop_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "Tempaper 무늬 맞춤 유형 차이",
    "publisher": "Tempaper",
    "url": "https://tempaper.com/blogs/news/the-differences-between-wallpaper-match-types"
   }
  ]
 },
 {
  "id": "로스",
  "term": "로스",
  "aliases": [
   "여유분",
   "여분",
   "할증"
  ],
  "trade": "common",
  "easy": "재단 · 무늬 맞춤으로 버려지는 자재와 그만큼의 여유 주문",
  "tip": "버려지는 자재와 여유분이에요. 딱 맞게 주문하면 모자라니 여유분을 넣어요.",
  "detail": "표준품셈은 정배지를 ㎡당 1.2㎡(할증 포함)로 잡고, 시장은 1~2롤 · 5% · 10~15% 등 자료마다 달라요. 자재를 딱 맞게 주문하면 모자라 일정이 밀려요.",
  "use": "",
  "ask": "자재 여유분은 얼마나 넣었나요?",
  "images": [],
  "sources": [
   {
    "title": "2026 건설공사 표준품셈(건축 5-3-7 도배바름·유지관리 도배 해체·교체)",
    "publisher": "국토교통부(한국표준품셈정보원 배포)",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=64699193400142&pgno=1"
   },
   {
    "title": "LX Z:IN [고급] 벽지",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5959"
   },
   {
    "title": "숨고 블로그 도배 견적 내는 법",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/도배-견적/"
   },
   {
    "title": "그레이씨어리스튜디오 벽지 물량 계산법",
    "publisher": "그레이씨어리스튜디오",
    "url": "https://graytheorystudio.com/insight/?bmode=view&idx=171161425"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "도배평수",
  "term": "도배평수",
  "aliases": [
   "도배 평수",
   "도배평"
  ],
  "trade": "dobae",
  "easy": "벽과 천장을 합친 도배 면적을 평으로 나타낸 것",
  "tip": "벽+천장 면적이에요. '평당' 견적이면 어느 평인지 꼭 물어봐요.",
  "detail": "업계에서는 집 평수에 곱해 어림하기도 해요. 믿집 표준견적서는 방 개수와 면적으로 벽 · 천장 면적을 따로 세요. '평당' 견적이면 분양 평인지 도배 평인지에 따라 가격의 뜻이 달라져요.",
  "use": "",
  "ask": "평당 가격의 평은 분양 평인가요, 도배 평인가요?",
  "images": [],
  "sources": [
   {
    "title": "숨고 블로그 도배 견적 내는 법",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/도배-견적/"
   },
   {
    "title": "숨고 도배 시공 가격",
    "publisher": "숨고",
    "url": "https://soomgo.com/prices/%EB%8F%84%EB%B0%B0-%EC%8B%9C%EA%B3%B5"
   },
   {
    "title": "도배 견적 내는 법",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/도배-견적/"
   }
  ]
 },
 {
  "id": "배꼽짐",
  "term": "배꼽짐",
  "aliases": [
   "풀 배어 나옴"
  ],
  "trade": "dobae",
  "easy": "부직포 초배에서 풀이 배어 나와 자국이 생기는 현상",
  "tip": "풀 얼룩 하자예요. 부직포 초배 때 운용지를 덧대 줄여요.",
  "detail": "부직포 위 이음부로 풀이 스며 나와 얼룩처럼 보여요. 이음부에 운용지를 덧대면 줄일 수 있다는 업계 설명이 있어요.",
  "use": "부직포 초배 뒤 생길 수 있는 풀 얼룩이에요. 운용지로 줄여요.",
  "images": [
   {
    "src": "/guide-img/terms/paste_stain_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/paste_stain_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "도배의 민족 고양캠프(부직포 vs 텍스, 배꼽짐)",
    "publisher": "도배의 민족",
    "url": "https://altgoodsave.co.kr/new-%EC%86%8C%EC%8B%9D/?pageid=4&mod=document&uid=8"
   }
  ]
 },
 {
  "id": "굽도리",
  "term": "굽도리",
  "aliases": [
   "굽돌이",
   "접착식 걸레받이",
   "굽도리지"
  ],
  "trade": "mokgong",
  "easy": "벽 아래에 붙이는 띠 모양 마감(접착식 걸레받이)",
  "tip": "접착식 걸레받이예요. 셀프로도 붙이지만 모서리부터 들뜨기 쉬워요.",
  "detail": "이형지를 떼어 붙이는 접착식은 셀프로도 하지만 모서리부터 들뜨고 겨울 난방 때 심해져요. 뗄 때 벽지가 같이 뜯길 수 있어요.",
  "use": "벽 아래에 붙이는 접착식 띠 마감이에요. 간단히 걸레받이를 대신할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/adhesive_skirting_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/adhesive_skirting_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "집꾸 걸레받이(굽도리) 교체 비용",
    "publisher": "집꾸",
    "url": "https://jibggu.com/posts/baseboard-cost"
   }
  ]
 },
 {
  "id": "보양",
  "term": "보양",
  "aliases": [
   "보양 작업"
  ],
  "trade": "common",
  "easy": "공사 중 엘리베이터 · 바닥 · 가구를 덮어 보호하는 것",
  "tip": "공사 중 덮어 보호하는 일이에요. 보양비가 견적에 들었는지, 승강기 기준을 관리사무소에 확인해요.",
  "detail": "승강기 보양 기준(올보양 · 하프보양)을 못 맞추면 자재 양중을 거부당할 수 있어요. 보양비가 견적에 들어 있는지 확인해요.",
  "use": "공사 중 승강기 · 바닥 · 문 · 가구를 덮어 흠집과 먼지를 막아요.",
  "images": [
   {
    "src": "/guide-img/terms/protection_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/protection_c.webp",
    "kind": "단면 그림"
   },
   {
    "src": "/guide-img/terms/protection_a.webp",
    "kind": "예시 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   },
   {
    "title": "공사 전 관리사무소 신고부터 엘리베이터 보양까지",
    "publisher": "꾸미고",
    "url": "https://kkumigo.co.kr/space/공사-전-관리사무소-신고부터/"
   }
  ]
 },
 {
  "id": "바탕-습도",
  "term": "바탕 습도",
  "aliases": [
   "바탕 함수율"
  ],
  "trade": "dobae",
  "easy": "도배할 벽 · 천장 바탕에 남은 물기 정도",
  "tip": "벽에 남은 물기예요. 곰팡이 · 결로 벽은 충분히 말린 뒤 도배해요.",
  "detail": "LH 시방서는 전자습도계로 쟀을 때 12% 이하일 때 초배를 시작하라고 해요. 곰팡이 · 결로 벽은 충분히 말린 뒤 도배해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   },
   {
    "title": "(구) 대한주택공사 전문시방서 32940 도배 공사",
    "publisher": "대한주택공사(eom.co.kr 게재)",
    "url": "https://www.eom.co.kr/2.regulation/4.common/ju_tack_kong_sa_sibangseo/construction/32940.htm"
   }
  ]
 },
 {
  "id": "환경표지",
  "term": "환경표지",
  "aliases": [
   "환경마크"
  ],
  "trade": "common",
  "easy": "친환경 제품에 붙는 공공 인증 마크",
  "tip": "친환경 인증 마크예요. 브랜드가 아니라 품번별로 확인해요.",
  "detail": "한국환경산업기술원이 운영하고 공공 시방은 환경표지 제품을 우선 쓰게 해요. 인증은 제품(품번)별이라 견적서 품번으로 확인해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "노루페인트 환경표지 인증서(기관·EL 체계 확인용)",
    "publisher": "노루페인트",
    "url": "https://www.noroopaint.com/kor/file/certificate/환경표지_34905호_NOROOWAY%20CLEAR%203종(260331).pdf"
   },
   {
    "title": "청사 환경 개선 공사 건축 시방서(2025.07)",
    "publisher": "서울특별시 강서도로사업소(나라장터)",
    "url": "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01003466&bidPbancOrd=000&fileType=&fileSeq=1"
   },
   {
    "title": "스케치 제품 페이지",
    "publisher": "KCC신한벽지",
    "url": "https://www.shinhanwall.co.kr/brands/view.html?depth1=1&depth2=5"
   }
  ]
 },
 {
  "id": "HB-마크",
  "term": "HB 마크",
  "aliases": [
   "HB 인증",
   "친환경건축자재 단체표준"
  ],
  "trade": "common",
  "easy": "한국공기청정협회의 실내공기 오염물질 저방출 자재 인증",
  "tip": "실내공기 자재 인증이에요. 등급(최우수 · 우수 · 양호)을 품번으로 확인해요.",
  "detail": "최우수 · 우수 · 양호 3등급이 있고 일반자재 최우수는 TVOC 0.10, HCHO 0.008 mg/㎡ · h 미만이에요. HB를 받으면 환경부 사전적합확인이 면제되고 실내마크를 붙여야 해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "한국공기청정협회 친환경건축자재 단체표준(HB)",
    "publisher": "한국공기청정협회",
    "url": "https://www.kaca.or.kr/web_basic/product/product.php?pagen=559"
   }
  ]
 },
 {
  "id": "환경성적표지",
  "term": "환경성적표지",
  "aliases": [
   "EPD"
  ],
  "trade": "common",
  "easy": "제품의 환경 영향 정보를 공개했다는 표지",
  "tip": "환경 정보 공개 표지예요. 품번별로 확인해요.",
  "detail": "LX 베스띠 · 디아망, 신한벽지 제품 등에 표기돼요. 친환경 표기는 브랜드 전체가 아니라 품번별로 확인해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN 실크 베스띠 샌드스톤 82558-02",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/101329"
   },
   {
    "title": "LX Z:IN 디아망 모던회벽 PR028-01",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/zin/product/13396"
   },
   {
    "title": "신한벽지 인증 및 수상",
    "publisher": "KCC신한벽지",
    "url": "https://www.shinhanwall.co.kr/pr/award.html"
   },
   {
    "title": "스케치 제품 페이지",
    "publisher": "KCC신한벽지",
    "url": "https://www.shinhanwall.co.kr/brands/view.html?depth1=1&depth2=5"
   }
  ]
 },
 {
  "id": "천장-몰딩",
  "term": "천장 몰딩",
  "aliases": [
   "몰딩",
   "상단 몰딩",
   "천정 몰딩"
  ],
  "trade": "mokgong",
  "easy": "벽과 천장이 만나는 선을 덮는 띠 마감재",
  "tip": "천장 둘레를 마감하는 목공이에요. 보통 평몰딩을 많이 고르고, 깔끔한 선을 원하면 마이너스 · 무몰딩을 골라요.",
  "detail": "벽 · 천장의 미세한 오차와 벽지 끝선을 가려 줘요. 견적에서는 천장 몰딩을 '상단', 걸레받이를 '하단'으로 나눠 부르기도 해요.",
  "use": "벽과 천장이 만나는 둘레에 붙여요. 벽지 끝선과 벽 · 천장 틈을 가려 깔끔하게 마감해요.",
  "images": [
   {
    "src": "/guide-img/terms/crown_molding_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/crown_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩이란? 뜻·종류·시공",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/120"
   },
   {
    "title": "내만집 매거진(도배 비용·몰딩 비용·목공 글)",
    "publisher": "내만집",
    "url": "https://nmjib.com/magazine/"
   },
   {
    "title": "마미견적서 '아파트 몰딩 교체 가격은 어떻게 결정되나요'",
    "publisher": "마미견적서",
    "url": "https://mommyestimate.com/reading-contents/65"
   }
  ]
 },
 {
  "id": "평몰딩",
  "term": "평몰딩",
  "aliases": [
   "슬림 몰딩",
   "평 몰딩"
  ],
  "trade": "mokgong",
  "easy": "얇고 평평한 띠 모양 몰딩",
  "tip": "가장 흔한 기본 몰딩이에요. 무난하고 저렴해서 보통 이걸 골라요.",
  "detail": "무난하고 저렴해 가장 흔히 써요.",
  "use": "천장 둘레에 가장 흔히 쓰는 기본 몰딩이에요.",
  "images": [
   {
    "src": "/guide-img/terms/flat_molding_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/flat_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "평몰딩·걸레받이·문선·천정·계단몰딩 목록(우딘 원장)",
    "publisher": "몰딩닷컴",
    "url": "https://m.mol-ding.com/product/list.html?cate_no=343"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "키자드 인테리어 몰딩 종류·시공비",
    "publisher": "키자드",
    "url": "https://keyzard.cc/views/nb/bTE7bWVlbW1ra21qaGZnaGpv"
   }
  ]
 },
 {
  "id": "계단몰딩",
  "term": "계단몰딩",
  "aliases": [
   "계단 몰딩",
   "역계단 몰딩"
  ],
  "trade": "mokgong",
  "easy": "2~3단 계단 모양 단면의 몰딩",
  "tip": "단이 있는 몰딩이에요. 평몰딩보다 입체감을 원할 때 골라요.",
  "detail": "시공 방식은 평몰딩과 같아요. 2계단 몰딩을 거꾸로 붙이는 역계단은 마이너스 몰딩 느낌을 내는 저비용 대안으로 쓰여요.",
  "use": "천장 둘레에 단을 줘 입체감을 내고 싶을 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/step_molding_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/step_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "평몰딩·걸레받이·문선·천정·계단몰딩 목록(우딘 원장)",
    "publisher": "몰딩닷컴",
    "url": "https://m.mol-ding.com/product/list.html?cate_no=343"
   }
  ]
 },
 {
  "id": "갈매기-몰딩",
  "term": "갈매기 몰딩",
  "aliases": [
   "크라운 몰딩",
   "왕관 몰딩"
  ],
  "trade": "mokgong",
  "easy": "왕관 · 갈매기 모양 단면의 장식 몰딩",
  "tip": "장식이 많은 몰딩이에요. 모양이 복잡해 필름보다 도장을 권하고, 떼면 벽 보수비가 붙을 수 있어요.",
  "detail": "형상이 복잡해 페인트 도색이 권장되고 셀프 필름은 피하라는 의견이 있어요. 떼고 무몰딩으로 바꾸면 미장 보수비가 붙을 수 있어요.",
  "use": "천장 둘레에 장식이 있는 클래식한 분위기를 낼 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/gull_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩이란? 뜻·종류·시공",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/120"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "마이너스-몰딩",
  "term": "마이너스 몰딩",
  "aliases": [
   "메지 몰딩",
   "음각 몰딩"
  ],
  "trade": "mokgong",
  "easy": "벽과 천장 사이를 1cm 안팎 띄워 홈처럼 보이게 하는 몰딩",
  "tip": "천장 둘레를 홈처럼 마감하는 몰딩이에요. 일반 몰딩의 2배 이상 들어 깔끔한 선을 꼭 원할 때 골라요.",
  "detail": "천장을 덧방한 뒤 약 10mm 간격을 두고 몰딩을 매립해요. 일반 몰딩의 2배 이상 들고, 벽 · 천장 평탄도가 결과를 좌우해요.",
  "use": "몰딩이 튀어나오지 않고 벽과 천장 사이에 얇은 홈만 보이게 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/minus_molding_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/minus_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   },
   {
    "title": "몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   },
   {
    "title": "몰딩 시공 업체 글(동작구·청주)",
    "publisher": "미소",
    "url": "https://miso.kr/blog/thread/동작구/몰딩-시공-업체-순위"
   }
  ]
 },
 {
  "id": "무몰딩",
  "term": "무몰딩",
  "aliases": [
   "히든 몰딩",
   "몰딩 없는 천장"
  ],
  "trade": "mokgong",
  "easy": "몰딩 없이 벽과 천장을 바로 맞대는 마감",
  "tip": "몰딩을 없애는 작업이에요. 평탄화가 꼭 필요해 비용 · 크랙 위험을 업체와 따져 보고 골라요.",
  "detail": "기존 몰딩 철거와 벽 · 천장 평탄화가 필수예요. 구축 콘크리트 · 조적 벽은 크랙 위험이 커서 도배형 · 목공형(석고 2겹) · 도장형 중 방식을 업체와 정해요.",
  "use": "몰딩 없이 벽과 천장을 바로 맞대 가장 깔끔한 선을 낼 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/no_molding_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/no_molding_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "웨인스코팅",
  "term": "웨인스코팅",
  "aliases": [
   "벽 프레임 몰딩"
  ],
  "trade": "oos",
  "easy": "벽면에 사각 프레임 몰딩을 두르는 장식",
  "tip": "벽에 두르는 장식 몰딩이에요. 도장이나 벽지로 마감해요.",
  "detail": "석고보드로 수직 · 수평을 잡고 양면테이프 · 실리콘으로 몰딩을 붙여요. 도장용 몰딩에 페인트를 칠하거나 래핑 몰딩에 벽지로 마감해요.",
  "use": "벽에 사각 몰딩 장식을 둘러 클래식한 분위기를 낼 때 써요.",
  "oos": true,
  "images": [
   {
    "src": "/guide-img/terms/wainscoting_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/wainscoting_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   },
   {
    "title": "몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "걸레받이",
  "term": "걸레받이",
  "aliases": [
   "하단 몰딩"
  ],
  "trade": "mokgong",
  "easy": "벽 아래쪽과 바닥이 만나는 곳을 덮는 마감재",
  "tip": "벽 아래를 마감하는 목공이에요. 보통 MDF 래핑 제품을 쓰고, 마루를 바꾸면 바닥 공사 뒤에 붙여요.",
  "detail": "청소기 · 발이 닿는 벽지 하단을 보호해요. 표준품셈은 높이 75~120mm를 기준으로 하고, 마루를 깔면 바닥 공사 뒤에 붙이는 경우가 많아요.",
  "use": "벽 아래 둘레에 붙여요. 청소기 · 발에 벽지 아랫단이 상하지 않게 막아요.",
  "images": [
   {
    "src": "/guide-img/terms/baseboard_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/baseboard_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "2026년 하반기 건설공사 표준시장단가(공고 제2026-652호)",
    "publisher": "국토교통부·한국건설기술연구원",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=3756196310142"
   },
   {
    "title": "2026년 건설공사 표준품셈(국토부 공고 제2025-1574호)",
    "publisher": "국토교통부",
    "url": "https://eastca.co.kr/Data/?bmode=view&idx=169205679"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "MDF",
  "term": "MDF",
  "aliases": [
   "중밀도섬유판",
   "MDF 래핑"
  ],
  "trade": "mokgong",
  "easy": "나무 섬유를 압축해 만든 판재",
  "tip": "나무 섬유를 압축한 판재예요. 몰딩 · 걸레받이 · 문선은 보통 MDF에 필름을 감아 써요.",
  "detail": "몰딩 · 걸레받이 · 문선에 필름을 감아(래핑) 많이 써요. 물에 약해 욕실 앞 · 주방처럼 물이 닿는 곳은 PVC가 낫다는 자료가 있어요.",
  "use": "몰딩 · 걸레받이 · 문선의 속 판재로 많이 써요. 물이 닿는 곳은 피해요.",
  "images": [
   {
    "src": "/guide-img/terms/mdf_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/mdf_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "집꾸 걸레받이(굽도리) 교체 비용",
    "publisher": "집꾸",
    "url": "https://jibggu.com/posts/baseboard-cost"
   },
   {
    "title": "평몰딩·걸레받이·문선·천정·계단몰딩 목록(우딘 원장)",
    "publisher": "몰딩닷컴",
    "url": "https://m.mol-ding.com/product/list.html?cate_no=343"
   },
   {
    "title": "부동산모아 걸레받이 시공 종류",
    "publisher": "부동산모아",
    "url": "https://realtymoa.com/%EA%B1%B8%EB%A0%88%EB%B0%9B%EC%9D%B4-%EC%8B%9C%EA%B3%B5-%EC%A2%85%EB%A5%98-3%EA%B0%80%EC%A7%80%EC%97%AD%ED%95%A0-%EC%86%8C%EC%9E%AC-%EA%B0%80%EA%B2%A9-%EA%B5%90%EC%B2%B4-%EC%A0%9C%EA%B1%B0-%ED%8C%81/"
   }
  ]
 },
 {
  "id": "래핑",
  "term": "래핑",
  "aliases": [
   "랩핑",
   "필름 래핑"
  ],
  "trade": "mokgong",
  "easy": "판재 겉면에 필름을 고온 압착해 감싼 마감",
  "tip": "판재를 필름으로 감싼 마감이에요. 몰딩 · 걸레받이 · 문짝에 많이 쓰는 마감이에요.",
  "detail": "몰딩 · 걸레받이 · 문짝 표면에 써요. 문은 옆면(엣지) 공법에 따라 습기를 견디는 정도가 달라요.",
  "use": "MDF 몰딩 · 걸레받이 · 문짝 겉면을 필름으로 감싸 마감할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/wrapping_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/wrapping_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "평몰딩·걸레받이·문선·천정·계단몰딩 목록(우딘 원장)",
    "publisher": "몰딩닷컴",
    "url": "https://m.mol-ding.com/product/list.html?cate_no=343"
   }
  ]
 },
 {
  "id": "ABS-도어",
  "term": "ABS 도어",
  "aliases": [
   "ABS 문",
   "ABS 방문"
  ],
  "trade": "mokgong",
  "easy": "합성수지(ABS) 판재로 만든 방문",
  "tip": "습기에 강한 문이에요. 욕실 · 다용도실 문은 보통 ABS를 골라요.",
  "detail": "습기와 열에 강하고 가벼워 욕실 · 다용도실 문에 많이 써요. 경첩은 주로 이지 경첩을 달아요.",
  "use": "습기에 강해 욕실 · 다용도실 문으로 많이 써요.",
  "images": [
   {
    "src": "/guide-img/terms/abs_door_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/abs_door_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "멤브레인-도어",
  "term": "멤브레인 도어",
  "aliases": [
   "멤브레인 문"
  ],
  "trade": "mokgong",
  "easy": "MDF에 얇은 시트를 고온 · 고압으로 붙인 문",
  "tip": "시트를 붙인 문이에요. 디자인이 많고 저렴해 건조한 방문에 골라요.",
  "detail": "디자인 폭이 넓고 저렴하지만 습기에 약하고 모서리가 잘 들떠요. 건조한 방문에 맞고 단독 시공은 줄어드는 추세예요.",
  "use": "디자인이 다양하고 저렴해서 건조한 방문에 써요.",
  "images": [
   {
    "src": "/guide-img/terms/membrane_door_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/membrane_door_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "문틀",
  "term": "문틀",
  "aliases": [
   "문 프레임"
  ],
  "trade": "mokgong",
  "easy": "문짝을 다는 사각 틀",
  "tip": "문짝을 다는 틀이에요. 문틀까지 바꾸면 주변 벽지가 상해 보통 도배와 묶어서 해요.",
  "detail": "벽 두께 방향 폭을 '110바'처럼 불러요(110~245바). 문틀을 바꾸면 주변 벽지 · 타일이 상해 도배 · 욕실 공정과 묶는 것이 원칙이에요.",
  "use": "방문 둘레에 짜 넣어요. 문짝을 달고 문이 열리고 닫히게 받쳐 줘요.",
  "images": [
   {
    "src": "/guide-img/terms/door_frame_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/door_frame_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "베이직 ABS도어 문틀 세트",
    "publisher": "힐림",
    "url": "https://hillim.co.kr/product/베이직-abs도어-문틀-세트/913/"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "3방틀",
  "term": "3방틀",
  "aliases": [
   "삼방틀"
  ],
  "trade": "mokgong",
  "easy": "위와 양옆 세 면만 있고 아래 문턱이 없는 문틀",
  "tip": "문턱 없는 문틀이에요. 문턱을 없애고 싶은 방문에 고르고, 바닥 높이 차이부터 확인해요.",
  "detail": "하부 문틀이 없어 청소가 쉽고 문턱을 없애고 싶을 때 써요. 바닥 높이 차이가 있는지 먼저 확인해요.",
  "use": "문턱 없이 드나들고 싶은 방문에 써요.",
  "images": [
   {
    "src": "/guide-img/terms/frame_3_4_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/frame_3_4_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "4방틀",
  "term": "4방틀",
  "aliases": [
   "사방틀"
  ],
  "trade": "mokgong",
  "easy": "아래 문턱까지 네 면이 있는 문틀",
  "tip": "문턱까지 있는 문틀이에요. 욕실 · 다용도실 문은 보통 이걸 골라요.",
  "detail": "바닥 높이가 다르거나 방수 · 방음이 필요한 욕실 · 다용도실에 써요. 하부 문틀에 가스켓을 달면 소음 · 바람 · 냄새를 줄여요.",
  "use": "욕실 · 다용도실처럼 바닥 높이가 다르거나 물 · 소음을 막아야 하는 문에 써요.",
  "images": [
   {
    "src": "/guide-img/terms/frame_3_4_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/frame_3_4_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "문선",
  "term": "문선",
  "aliases": [
   "문선 몰딩"
  ],
  "trade": "mokgong",
  "easy": "문틀과 벽 사이 이음을 덮는 테두리 몰딩",
  "tip": "문틀 둘레 테두리예요. 보통 일반 문선을 쓰고, 깔끔한 라인을 원하면 슬림 · 무문선을 골라요.",
  "detail": "일반 문선 외에 인방형 · 평문선형, 9 · 12mm 슬림 문선, 문선을 없앤 무문선이 있어요. 얇을수록 벽 평탄화와 정밀한 맞춤이 중요해요.",
  "use": "문틀 둘레에 붙여요. 문틀과 벽 사이 틈을 덮어 마감해요.",
  "images": [
   {
    "src": "/guide-img/terms/door_casing_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/door_casing_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "평몰딩·걸레받이·문선·천정·계단몰딩 목록(우딘 원장)",
    "publisher": "몰딩닷컴",
    "url": "https://m.mol-ding.com/product/list.html?cate_no=343"
   },
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "트렌드쿨 방 도어 선택 주의사항(히든도어, 9~12mm 문선)",
    "publisher": "트렌드쿨",
    "url": "https://trendkool.com/culture/ex-interior/%eb%b0%a9-%eb%8f%84%ec%96%b4-%ec%a3%bc%eb%ac%b8-%ec%84%a0%ed%83%9d-%ed%9e%88%eb%93%a0-9-12%eb%af%b8%eb%a6%ac-%eb%ac%b8%ec%84%a0/"
   }
  ]
 },
 {
  "id": "슬림-문선",
  "term": "슬림 문선",
  "aliases": [
   "9mm 문선",
   "12mm 문선",
   "9미리 문선"
  ],
  "trade": "mokgong",
  "easy": "테두리를 9mm · 12mm로 얇게 보이게 한 문선",
  "tip": "얇은 문선이에요. 깔끔한 라인을 원할 때 고르고, 벽 평탄화가 더해질 수 있어요.",
  "detail": "업체 설명은 목공 없이 시공이 단순하다지만, 벽 평탄화가 더해져 기간이 늘 수 있다는 자료도 있어 자료마다 달라요. 얇아서 손상에 약해요.",
  "use": "문 테두리를 얇게 보이게 해 깔끔한 문 라인을 원할 때 써요.",
  "ask": "슬림 문선이면 벽 평탄화가 더 필요한가요? 공사 기간이 늘어나나요?",
  "images": [
   {
    "src": "/guide-img/terms/slim_casing_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/slim_casing_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "트렌드쿨 방 도어 선택 주의사항(히든도어, 9~12mm 문선)",
    "publisher": "트렌드쿨",
    "url": "https://trendkool.com/culture/ex-interior/%eb%b0%a9-%eb%8f%84%ec%96%b4-%ec%a3%bc%eb%ac%b8-%ec%84%a0%ed%83%9d-%ed%9e%88%eb%93%a0-9-12%eb%af%b8%eb%a6%ac-%eb%ac%b8%ec%84%a0/"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "무문선",
  "term": "무문선",
  "aliases": [
   "무문선 도어"
  ],
  "trade": "mokgong",
  "easy": "문선을 없애 문틀 라인만 보이게 한 형태",
  "tip": "문선 없는 마감이에요. 히든도어보다 싸게 깔끔한 라인을 원할 때 골라요.",
  "detail": "히든도어보다 싸면서 라인이 깔끔하고 필름 마감이 가능해요. 손때 · 벽지 손상이 쉽고 문 무게를 버틸 ABS 도어와 강한 프레임이 필요해요.",
  "use": "문선 없이 문틀 라인만 보이게 해 히든도어보다 싸게 깔끔함을 낼 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/no_casing_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/no_casing_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "히든도어",
  "term": "히든도어",
  "aliases": [
   "히든 도어"
  ],
  "trade": "mokgong",
  "easy": "문틀 · 몰딩이 안 보이게 벽과 같은 면으로 맞춘 문",
  "tip": "벽처럼 숨긴 문이에요. 전용 문 · 경첩이 필요해 비싸고, 더 싸게는 무문선을 골라요.",
  "detail": "문과 벽 단차가 2mm 이내여야 효과가 있고 35T 이상 도어와 히든 경첩이 필요해요. 벽을 도배 · 필름으로 마감하면 래핑도어, 도장이면 백골도어를 써요.",
  "use": "문을 벽처럼 보이게 숨기고 싶을 때 써요. 벽과 같은 마감으로 맞춰요.",
  "images": [
   {
    "src": "/guide-img/terms/hidden_door_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/hidden_door_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "아정당 히든 도어 시공 장단점(홍보성)",
    "publisher": "아정당",
    "url": "https://www.ajd.co.kr/contents/basic-tip/detail/%ED%9E%88%EB%93%A0_%EB%8F%84%EC%96%B4_%EC%9D%B8%ED%85%8C%EB%A6%AC%EC%96%B4_%EC%8B%9C%EA%B3%B5_%EC%9E%A5%EB%8B%A8%EC%A0%90_%ED%95%9C%EB%88%88%EC%97%90_%EB%B9%84%EA%B5%90_%EA%BF%80%ED%8C%81-83772"
   },
   {
    "title": "트렌드쿨 방 도어 선택 주의사항(히든도어, 9~12mm 문선)",
    "publisher": "트렌드쿨",
    "url": "https://trendkool.com/culture/ex-interior/%eb%b0%a9-%eb%8f%84%ec%96%b4-%ec%a3%bc%eb%ac%b8-%ec%84%a0%ed%83%9d-%ed%9e%88%eb%93%a0-9-12%eb%af%b8%eb%a6%ac-%eb%ac%b8%ec%84%a0/"
   }
  ]
 },
 {
  "id": "포켓도어",
  "term": "포켓도어",
  "aliases": [
   "포켓 슬라이딩",
   "매입형 미닫이"
  ],
  "trade": "mokgong",
  "easy": "문이 벽 속으로 밀려 들어가는 미닫이문",
  "tip": "벽 속으로 들어가는 문이에요. 벽체 목공이 필요해 비싸고 내력벽에는 못 넣어요.",
  "detail": "벽체 목공이 먼저 필요해 비용과 난이도가 높아요. 내력벽에는 넣을 수 없어요.",
  "use": "문이 벽 속으로 들어가 열린 문이 자리를 차지하지 않게 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/pocket_door_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/pocket_door_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "인방",
  "term": "인방",
  "aliases": [
   "람마"
  ],
  "trade": "mokgong",
  "easy": "문 위쪽 벽 부분 또는 그 위 마감재",
  "tip": "문 위쪽 벽이에요. 몰딩 길이를 셀 때 여기도 넣어요.",
  "detail": "문 위에도 벽이 있으면 천장 몰딩 길이에 넣어 계산해요. 문선 · 람마를 세트로 바꾸면 비용을 더 받는 업체가 있어요.",
  "use": "문 위쪽 벽 부분이에요. 몰딩 · 문선 길이를 잴 때 함께 봐요.",
  "images": [
   {
    "src": "/guide-img/terms/lintel_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/lintel_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "우딘 ABS 라인도어(시공가 표)",
    "publisher": "목문닷컴",
    "url": "https://mokmun.com/product/방문교체-문짝-우딘-abs-라인-도어-코로스-셀프시공or시공서비스/98/"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "경첩",
  "term": "경첩",
  "aliases": [
   "이지 경첩",
   "나비경첩",
   "히든 경첩"
  ],
  "trade": "mokgong",
  "easy": "문짝을 문틀에 달아 여닫게 하는 철물",
  "tip": "문을 다는 철물이에요. 문이 처지면 교체 전에 경첩 조정부터 해요.",
  "detail": "일반 · 이지 · 안전 경첩이 있고 히든도어는 히든 경첩을 따로 주문해요. 문이 처지면 상단 경첩 나사 조임과 조정부터 해요.",
  "use": "문짝을 문틀에 달아 여닫게 하는 철물이에요. 문이 처지면 여기부터 조정해요.",
  "images": [
   {
    "src": "/guide-img/terms/hinge_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/hinge_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "도어 구성·종류·소재 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7500?guideTab=AZ01"
   },
   {
    "title": "트렌드쿨 방 도어 선택 주의사항(히든도어, 9~12mm 문선)",
    "publisher": "트렌드쿨",
    "url": "https://trendkool.com/culture/ex-interior/%eb%b0%a9-%eb%8f%84%ec%96%b4-%ec%a3%bc%eb%ac%b8-%ec%84%a0%ed%83%9d-%ed%9e%88%eb%93%a0-9-12%eb%af%b8%eb%a6%ac-%eb%ac%b8%ec%84%a0/"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "연귀맞춤",
  "term": "연귀맞춤",
  "aliases": [
   "연귀"
  ],
  "trade": "mokgong",
  "easy": "몰딩 모서리를 45°로 잘라 맞추는 방법",
  "tip": "몰딩 모서리를 45°로 맞추는 방법이에요. 이음이 벌어지면 하자로 봐요.",
  "detail": "표준시방서(KCS)는 몰딩 모서리 · 꺾임을 연귀맞춤으로 틈 없이 하라고 해요. 이음이 벌어지면 하자 점검 대상이에요.",
  "use": "몰딩이 꺾이는 모서리를 틈 없이 맞출 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/miter_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/miter_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 52 00 천장공사(2021)",
    "publisher": "국토교통부(제3자 미러 경유)",
    "url": "https://nogada.kwoody01.com/604"
   }
  ]
 },
 {
  "id": "다루끼",
  "term": "다루끼",
  "aliases": [
   "각재",
   "각목"
  ],
  "trade": "mokgong",
  "easy": "30×30mm 안팎의 얇은 각목",
  "tip": "얇은 각목이에요. 아파트 천장 메우기는 다루끼 위에 석고보드를 붙이는 경우가 많아요.",
  "detail": "천장 · 벽 바탕틀로 써요. 아파트 우물천장 메우기는 다루끼 지지대 위에 석고보드를 붙이는 사례가 많아요.",
  "use": "천장 · 벽 바탕틀을 짤 때 쓰는 얇은 각목이에요.",
  "images": [
   {
    "src": "/guide-img/terms/batten_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "얼마드나 우물천장 비용 단가표",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/coffered-ceiling-cost"
   }
  ]
 },
 {
  "id": "경량천장틀",
  "term": "경량천장틀",
  "aliases": [
   "M-BAR",
   "엠바",
   "경량철골 천장틀"
  ],
  "trade": "mokgong",
  "easy": "아연도금 철제 부재로 짜는 천장 바탕틀",
  "tip": "철제 천장틀이에요. 표준품셈이 기준으로 삼는 공법이에요.",
  "detail": "캐링채널 · M-BAR · 행거볼트로 짜요.",
  "use": "철제 부재로 천장 바탕틀을 짤 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/steel_ceiling_frame_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/steel_ceiling_frame_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCC 석고보드 표준시방서",
    "publisher": "KCC",
    "url": "https://www.kccworld.co.kr/data/product/KCC_석고보드_시방서.pdf"
   },
   {
    "title": "2026년 건설공사 표준품셈(국토부 공고 제2025-1574호)",
    "publisher": "국토교통부",
    "url": "https://eastca.co.kr/Data/?bmode=view&idx=169205679"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "반자틀",
  "term": "반자틀",
  "aliases": [
   "반자대",
   "목재 반자틀"
  ],
  "trade": "mokgong",
  "easy": "천장판을 붙이려고 짜는 바탕틀",
  "tip": "천장판을 붙이는 바탕틀이에요. 처짐이 걱정되면 간격을 좁게 짜요.",
  "detail": "KCS 목공사 기준 반자대는 450mm 이하 간격이에요. 처짐이 걱정되면 약 30cm 간격으로 짠 현장 사례가 있어요.",
  "use": "천장판(석고보드)을 붙일 바탕틀을 짤 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/wood_ceiling_frame_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/wood_ceiling_frame_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 33 01 목공사 일반(2021)",
    "publisher": "국토교통부(제3자 미러 경유)",
    "url": "https://nogada.kwoody01.com/498"
   }
  ]
 },
 {
  "id": "달대",
  "term": "달대",
  "aliases": [
   "달대볼트",
   "행거볼트"
  ],
  "trade": "mokgong",
  "easy": "천장틀을 위쪽 구조체에 매다는 부재",
  "tip": "천장틀을 매다는 부재예요. 천장이 처졌다면 실측 때 달대 상태부터 봐요.",
  "detail": "달대가 약해지거나 부식되면 천장이 처져요. 실측 때 점검구로 달대 · 각재 상태를 미리 보면 보강 여부를 알 수 있어요.",
  "use": "천장틀을 위쪽 콘크리트에 매달아 처지지 않게 잡아 줘요.",
  "images": [
   {
    "src": "/guide-img/terms/hanger_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/hanger_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "KCS 41 52 00 천장공사(2021)",
    "publisher": "국토교통부(제3자 미러 경유)",
    "url": "https://nogada.kwoody01.com/604"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "석고보드",
  "term": "석고보드",
  "aliases": [
   "석고판"
  ],
  "trade": "mokgong",
  "easy": "석고를 종이로 감싼 판으로, 천장 · 벽 바탕재",
  "tip": "천장 · 벽 바탕판이에요. 도배로 마감하는 평천장은 보통 1겹이에요.",
  "detail": "KS F 3504 규격으로 두께 9.5 · 12.5 · 15mm가 있고 일반 · 방수 · 방화 등 종류가 나뉘어요. 도배로 마감하는 평천장은 바탕용 1겹이 기준이에요.",
  "use": "천장 · 벽의 바탕판으로 써요. 그 위에 도배 · 도장을 해요.",
  "images": [
   {
    "src": "/guide-img/terms/gypsum_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "Komachine 석고보드 제품(KS F 3504)",
    "publisher": "코머신",
    "url": "https://komachine.com/en/companies/byucksan/products/137224"
   },
   {
    "title": "KCC 석고보드 표준시방서",
    "publisher": "KCC",
    "url": "https://www.kccworld.co.kr/data/product/KCC_석고보드_시방서.pdf"
   },
   {
    "title": "2026년 하반기 건설공사 표준시장단가(공고 제2026-652호)",
    "publisher": "국토교통부·한국건설기술연구원",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=3756196310142"
   }
  ]
 },
 {
  "id": "석고보드-2겹",
  "term": "석고보드 2겹",
  "aliases": [
   "2P",
   "2Ply",
   "석고 2겹"
  ],
  "trade": "mokgong",
  "easy": "석고보드를 두 겹으로 엇갈려 붙이는 시공",
  "tip": "보드를 두 겹으로 붙이는 시공이에요. 무몰딩 · 도장 마감이면 보통 2겹을 권해요.",
  "detail": "이음이 엇갈려 크랙 · 처짐에 유리해 무몰딩 · 도장 마감에 권해요. 하루 시공량이 1겹보다 줄어(천장 45→35㎡) 품이 늘어요.",
  "use": "무몰딩 · 도장 마감처럼 크랙 · 처짐을 더 막아야 할 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/gypsum_double_b.webp",
    "kind": "입체 그림"
   }
  ],
  "sources": [
   {
    "title": "2026년 건설공사 표준품셈(국토부 공고 제2025-1574호)",
    "publisher": "국토교통부",
    "url": "https://eastca.co.kr/Data/?bmode=view&idx=169205679"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 매거진(도배 비용·몰딩 비용·목공 글)",
    "publisher": "내만집",
    "url": "https://nmjib.com/magazine/"
   }
  ]
 },
 {
  "id": "우물천장",
  "term": "우물천장",
  "aliases": [
   "우물 천장"
  ],
  "trade": "mokgong",
  "easy": "천장 일부가 '井'자로 오목하게 들어간 형태",
  "tip": "가운데가 오목한 천장이에요. 층고 낮은 구축 · 소형은 평천장이 낫다는 의견이 있어 메우기도 해요.",
  "detail": "주거에서는 목공으로 짠 경우가 많아요. 층고 2.3m대 구축이나 소형 평형은 평천장이 유리하다는 업계 판단이 있어요.",
  "use": "거실 천장 가운데를 오목하게 높여 조명과 함께 꾸밀 때 써요.",
  "images": [
   {
    "src": "/guide-img/terms/tray_ceiling_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/tray_ceiling_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "우물천장 VS 평천장",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5135"
   },
   {
    "title": "얼마드나 우물천장 비용 단가표",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/coffered-ceiling-cost"
   }
  ]
 },
 {
  "id": "등박스",
  "term": "등박스",
  "aliases": [
   "등 박스"
  ],
  "trade": "mokgong",
  "easy": "천장 가운데 조명을 달려고 낸 단이나 박스",
  "tip": "조명용 천장 박스예요. 천장 평탄화 때 없애는 경우가 많고, 등박스만 없애면 비용이 크게 줄어요.",
  "detail": "우물천장을 평탄화할 때 함께 철거해요. 등박스만 없애면 우물 전체 평탄화보다 비용이 절반 이하라는 자료가 있어요.",
  "use": "천장에 조명을 달거나 간접조명을 숨기려고 만들어요.",
  "images": [
   {
    "src": "/guide-img/terms/light_box_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/light_box_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "우물천장 VS 평천장",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/5135"
   },
   {
    "title": "얼마드나 우물천장 비용 단가표",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/coffered-ceiling-cost"
   }
  ]
 },
 {
  "id": "천장-평탄화",
  "term": "천장 평탄화",
  "aliases": [
   "우물 메우기",
   "평천장 만들기"
  ],
  "trade": "mokgong",
  "easy": "우물천장 · 등박스를 없애 천장을 평평하게 만드는 목공",
  "tip": "천장을 평평하게 다시 만드는 목공이에요. 유형에 따라 비용이 크게 달라 사진으로 유형부터 맞춰요.",
  "detail": "등박스형, 우물 메우기, 거실 전체 재시공, 처짐 보강 네 유형으로 범위와 비용이 크게 달라요. 끝나면 석고 이음이 안 보이게 띄움 도배를 해요.",
  "use": "등박스 · 우물천장을 없애 천장을 평평하게 만들고 싶을 때 해요.",
  "images": [
   {
    "src": "/guide-img/terms/ceiling_flat_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/ceiling_flat_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "얼마드나 우물천장 비용 단가표",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/coffered-ceiling-cost"
   }
  ]
 },
 {
  "id": "점검구",
  "term": "점검구",
  "aliases": [
   "천장 점검구"
  ],
  "trade": "mokgong",
  "easy": "천장 속을 볼 수 있게 낸 작은 구멍과 덮개",
  "tip": "천장 속을 보는 덮개예요. 위치는 목공 전에 정해 두는 게 좋아요.",
  "detail": "실측 때 점검구로 달대 · 각재 · 누수 · 배관 높이를 보면 처짐 보강이 필요한지 미리 알 수 있어요. 점검구 · 에어컨 배관 위치는 목공 전에 정해요.",
  "use": "천장 속 배관 · 누수 · 구조를 확인하고 손볼 수 있게 남겨 두는 덮개예요.",
  "images": [
   {
    "src": "/guide-img/terms/access_panel_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/access_panel_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "티엠티티 '반셀프 인테리어 실전 #4 목공'",
    "publisher": "티엠티티",
    "url": "https://tmtt.ghost.io/carpentry/"
   }
  ]
 },
 {
  "id": "커튼박스",
  "term": "커튼박스",
  "aliases": [
   "커튼 박스"
  ],
  "trade": "mokgong",
  "easy": "커튼 · 블라인드 레일을 천장에 숨기는 박스",
  "tip": "커튼 레일을 숨기는 박스예요. 매립형은 목공 때 만들어야 해서 미리 정해요.",
  "detail": "매립형은 목공 단계에서 만들어야 하고 도배 뒤에 추가하면 2배 이상 든다고 해요. 깊이는 단커튼 150mm, 이중커튼 200mm가 기준선이에요.",
  "use": "창 위 천장에 만들어요. 커튼 · 블라인드 레일을 숨겨 깔끔하게 보이게 해요.",
  "images": [
   {
    "src": "/guide-img/terms/curtain_box_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/curtain_box_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "타카",
  "term": "타카",
  "aliases": [
   "타카핀",
   "에어 타카"
  ],
  "trade": "mokgong",
  "easy": "공기압으로 핀을 박는 목공 공구",
  "tip": "핀을 박는 목공 공구예요. 도배 전에 튀어나온 핀을 정리했는지 봐요.",
  "detail": "컴프레서와 함께 목공 소음의 주범이에요. 도배 전에 튀어나온 타카핀을 정리해야 벽지가 깨끗하게 붙어요.",
  "use": "몰딩 · 각재 · 보드를 핀으로 고정할 때 쓰는 목공 공구예요.",
  "images": [
   {
    "src": "/guide-img/terms/nailer_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/nailer_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "먹매김",
  "term": "먹매김",
  "aliases": [
   "먹줄",
   "레벨 잡기"
  ],
  "trade": "mokgong",
  "easy": "시공 기준선을 벽 · 천장에 표시하는 작업",
  "tip": "기준선을 표시하는 작업이에요. 요즘은 레이저로 수평 · 수직선을 잡아요.",
  "detail": "요즘은 레이저로 수평 · 수직선을 잡아요. 표준품셈에 먹매김 항목이 따로 있어요.",
  "use": "몰딩 · 천장틀 같은 것을 곧게 달려고 기준선을 표시할 때 해요.",
  "images": [
   {
    "src": "/guide-img/terms/layout_line_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/layout_line_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "2026년 건설공사 표준품셈(국토부 공고 제2025-1574호)",
    "publisher": "국토교통부",
    "url": "https://eastca.co.kr/Data/?bmode=view&idx=169205679"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "코킹",
  "term": "코킹",
  "aliases": [
   "실리콘 마감",
   "실링"
  ],
  "trade": "mokgong",
  "easy": "틈을 탄성 실리콘으로 메우는 마감",
  "tip": "틈을 실리콘으로 메우는 마감이에요. 몰딩 · 걸레받이 틈 마감 상태를 검수할 때 봐요.",
  "detail": "몰딩 · 걸레받이와 벽 사이 틈을 메워요. 걸레받이는 바닥 공사 뒤 실리콘 마감 상태를 검수해요.",
  "use": "몰딩 · 걸레받이와 벽 사이 틈을 메워 마감할 때 해요.",
  "images": [
   {
    "src": "/guide-img/terms/caulking_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/caulking_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   },
   {
    "title": "LX Z:IN 몰딩이란? 뜻·종류·시공",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/120"
   }
  ]
 },
 {
  "id": "함수율",
  "term": "함수율",
  "aliases": [
   "목재 함수율"
  ],
  "trade": "mokgong",
  "easy": "목재나 마감재 속 수분 비율",
  "tip": "목재 속 수분 비율이에요. 덜 마른 목재는 나중에 몰딩 틈이 생길 수 있어요.",
  "detail": "KCS는 내장 마감 목재 15% 이하(필요하면 12%), 목제 창호 18% 이하를 요구해요. 덜 마르면 수축으로 몰딩 틈이 생길 수 있어요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "KCS 41 33 01 목공사 일반(2021)",
    "publisher": "국토교통부(제3자 미러 경유)",
    "url": "https://nogada.kwoody01.com/498"
   },
   {
    "title": "KCS 41 55 01 창호공사 일반 · 41 55 05 목제 창호공사(2021)",
    "publisher": "국토교통부(제3자 미러 경유)",
    "url": "https://nogada.kwoody01.com/610"
   }
  ]
 },
 {
  "id": "품",
  "term": "품",
  "aliases": [
   "1품"
  ],
  "trade": "common",
  "easy": "기능공 1명이 하루 동안 하는 일의 양",
  "tip": "하루 일의 양이에요. 견적서에 몇 명이 며칠인지 적혀 있는지 봐요.",
  "detail": "견적은 '몇 품'으로 짜고 시중노임은 1일 8시간 기준이에요. 견적서에 투입 인원×일수가 적혀 있는지 확인해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "2026년 하반기 적용 건설업 임금실태조사 보고서(지정통계 제365004호)",
    "publisher": "대한건설협회",
    "url": "https://www.cak.or.kr/lay1/bbs/S1T41C42/A/14/view.do?article_seq=160598"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "표준품셈",
  "term": "표준품셈",
  "aliases": [
   "품셈",
   "건설공사 표준품셈"
  ],
  "trade": "common",
  "easy": "공사 종류별로 필요한 인력 · 자재량을 정한 공공 기준",
  "tip": "공공 공사의 작업량 기준이에요. 참고 기준이라 업체 견적과는 다를 수 있어요.",
  "detail": "국토부가 매년 공고해요. 예를 들어 도배바름은 도배공 2명과 보통인부 1명이 하루 95㎡(콘크리트면)를 기준으로 해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "2026 건설공사 표준품셈(건축 5-3-7 도배바름·유지관리 도배 해체·교체)",
    "publisher": "국토교통부(한국표준품셈정보원 배포)",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=64699193400142&pgno=1"
   },
   {
    "title": "2026년 건설공사 표준품셈(국토부 공고 제2025-1574호)",
    "publisher": "국토교통부",
    "url": "https://eastca.co.kr/Data/?bmode=view&idx=169205679"
   }
  ]
 },
 {
  "id": "표준시장단가",
  "term": "표준시장단가",
  "aliases": [
   "시장단가"
  ],
  "trade": "common",
  "easy": "공공 공사 실적을 바탕으로 정한 공종별 기준 단가",
  "tip": "공공 공사 기준 단가예요. 시장 가격과 차이가 있어 참고용으로 봐요.",
  "detail": "국토부 · 한국건설기술연구원이 반기마다 공고해요. 공공 대형공사 예정가격용이고 주재료비가 빠진 항목이 많아 시장 가격과 차이가 있어요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "2026년 하반기 건설공사 표준시장단가(공고 제2026-652호)",
    "publisher": "국토교통부·한국건설기술연구원",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=3756196310142"
   },
   {
    "title": "2026년 하반기 건설공사 표준시장단가(도배지바름)",
    "publisher": "국토교통부·한국건설기술연구원",
    "url": "https://www.kseis.co.kr/bbs/data/dataDetail.do?bbs_seq=3756196310142&pgno=1"
   }
  ]
 },
 {
  "id": "시중노임단가",
  "term": "시중노임단가",
  "aliases": [
   "노임단가",
   "건설업 임금실태조사"
  ],
  "trade": "common",
  "easy": "직종별 하루 노임의 공식 통계",
  "tip": "공식 일당 통계예요. 시장에서 받는 일당과는 차이가 있어요.",
  "detail": "대한건설협회가 1월 · 9월에 공표하고 1일 8시간 기준이에요. 시장에서 받는 일당과는 차이가 있어요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "2026년 하반기 적용 건설업 임금실태조사 보고서(지정통계 제365004호)",
    "publisher": "대한건설협회",
    "url": "https://www.cak.or.kr/lay1/bbs/S1T41C42/A/14/view.do?article_seq=160598"
   },
   {
    "title": "2026년 하반기 적용 건설업 임금실태조사 보고서",
    "publisher": "대한건설협회",
    "url": "https://info.cak.or.kr/lay1/bbs/S1T41C42/A/14/view.do?article_seq=160598"
   }
  ]
 },
 {
  "id": "일식",
  "term": "일식",
  "aliases": [
   "1식"
  ],
  "trade": "common",
  "easy": "여러 작업을 한 묶음 금액으로 적은 표기",
  "tip": "여러 일을 한 금액으로 적은 표기예요. 비교하려면 항목 · 수량별로 나눠 달라고 해요.",
  "detail": "세부 수량이 안 보여 업체끼리 비교하기 어려워요. 항목 · 수량별로 나눠 달라고 요청해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   }
  ]
 },
 {
  "id": "부가세-별도",
  "term": "부가세 별도",
  "aliases": [
   "VAT 별도"
  ],
  "trade": "common",
  "easy": "적힌 금액에 부가세 10%가 따로 붙는다는 뜻",
  "tip": "부가세 10%가 따로 붙는다는 뜻이에요. 믿집 화면의 금액은 부가세 포함이라, 업체 견적과 견줄 때 부가세 포함 총액으로 맞춰요.",
  "detail": "견적끼리 견줄 때는 부가세 포함 총액으로 맞춰요. '현금가 할인'은 세금계산서 · 현금영수증을 끊지 않는다는 뜻일 수 있어 지급 증빙이 약해져요.",
  "use": "",
  "ask": "이 금액은 부가세 포함인가요?",
  "images": [],
  "sources": [
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   },
   {
    "title": "모모랩디자인 스토리(계약·무등록·부가세·하자 접수 등)",
    "publisher": "모모랩디자인",
    "url": "https://momolabdesign.com/story/"
   }
  ]
 },
 {
  "id": "가견적",
  "term": "가견적",
  "aliases": [
   "예상 견적",
   "온라인 견적"
  ],
  "trade": "common",
  "easy": "실측 전에 업체가 확인한 단가로 계산한 예상 금액",
  "tip": "실측 전 금액이에요. 믿집 가견적은 업체가 확인한 단가에 믿집이 센 수량을 곱해 계산해요.",
  "detail": "업체마다 단가가 달라 같은 집이라도 가견적이 달라요. 실측 뒤에는 업체가 집을 보고 실측 견적서를 다시 내서 금액이 달라질 수 있어요.",
  "use": "",
  "ask": "실측 뒤 금액이 바뀐다면 어떤 항목이 바뀌나요?",
  "images": [],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "실측-견적서",
  "term": "실측 견적서",
  "aliases": [
   "실측 견적서",
   "실측 견적"
  ],
  "trade": "common",
  "easy": "업체가 집에 와서 재 본 뒤 내는 견적서",
  "tip": "집을 보고 낸 견적이에요. 믿집에서는 업체가 자기 양식 파일로 내고, 금액 · 부가세 방식 · 공사 기간 · 유효기간을 칸에 적어요.",
  "detail": "천장 속 · 벽 상태처럼 현장을 봐야 아는 조건이 반영돼 가견적과 달라질 수 있어요. 자재명 · 단가 · 수량이 적힌 상세견적서로 받아 견줘요.",
  "use": "",
  "ask": "가견적과 달라진 줄은 어느 것이고 왜 달라졌나요?",
  "images": [],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "소비자분쟁해결기준(공정위 고시 제2025-14호) 실내건축공사업",
    "publisher": "공정거래위원회",
    "url": "https://www.law.go.kr/행정규칙/소비자분쟁해결기준"
   }
  ]
 },
 {
  "id": "상세견적서",
  "term": "상세견적서",
  "aliases": [
   "내역서"
  ],
  "trade": "common",
  "easy": "자재명 · 단가 · 수량이 구체적으로 적힌 견적서",
  "tip": "자재 · 단가 · 수량이 적힌 견적서예요. 계약 전에 꼭 받아 보관해요.",
  "detail": "소비자분쟁해결기준은 이런 상세견적서를 계약서로 간주해요. 계약 전에 꼭 받아 보관해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "소비자분쟁해결기준(공정위 고시 제2025-14호) 실내건축공사업",
    "publisher": "공정거래위원회",
    "url": "https://www.law.go.kr/행정규칙/소비자분쟁해결기준"
   }
  ]
 },
 {
  "id": "별도",
  "term": "별도",
  "aliases": [
   "별도 항목",
   "내역 외 별도"
  ],
  "trade": "common",
  "easy": "견적 총액에 들어 있지 않아 따로 내야 하는 항목",
  "tip": "총액 밖 항목이에요. 믿집 표준견적서는 줄마다 포함 · 묶음 포함 · 따로 계산 · 선택 · 실측 후 · 안 함으로 보여 줘요.",
  "detail": "폐기물 · 양중 · 보양 · 부가세가 '별도'로 빠져 총액이 낮아 보이는 경우가 많아요. 업체 견적끼리 견줄 때는 항목마다 포함 · 별도 · 빠짐을 표시해요.",
  "use": "",
  "ask": "총액에 들지 않은 별도 항목은 무엇인가요?",
  "images": [],
  "sources": [
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "실측-후",
  "term": "실측 후",
  "aliases": [
   "조건부",
   "현장 확인 후"
  ],
  "trade": "common",
  "easy": "현장을 봐야 정할 수 있어 나중에 금액이 정해지는 항목",
  "tip": "현장을 보고 정하는 항목이에요. 믿집 표준견적서에서 '실측 후' 줄은 합계에 들어가지 않아요.",
  "detail": "곰팡이 · 철거량 · 천장 속 상태처럼 실측이나 철거 뒤에 알 수 있는 항목이에요. '현장 상황에 따라 추가' 문구가 있으면 항목과 단가를 미리 받아 둬요.",
  "use": "",
  "ask": "실측 뒤에 정할 항목과 그 단가는 무엇인가요?",
  "images": [],
  "sources": [
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "양중",
  "term": "양중",
  "aliases": [
   "양중비"
  ],
  "trade": "common",
  "easy": "자재를 위층으로 올리거나 내리는 운반",
  "tip": "자재를 올리고 내리는 일이에요. 엘리베이터를 못 쓰면 사다리차 비용이 따로 붙는지 확인해요.",
  "detail": "엘리베이터를 쓰기 어려우면 사다리차 · 인력 양중비가 따로 붙어요. 견적에서 자주 빠지는 항목이에요.",
  "use": "엘리베이터를 쓰기 어려울 때 사다리차 · 사람이 자재를 올리고 내리는 일이에요.",
  "images": [
   {
    "src": "/guide-img/terms/hoisting_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/hoisting_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   }
  ]
 },
 {
  "id": "예치금",
  "term": "예치금",
  "aliases": [
   "공사 예치금"
  ],
  "trade": "common",
  "easy": "공사 전에 관리사무소에 맡기는 보증금",
  "tip": "관리사무소 보증금이에요. 금액보다 돌려받는 조건을 확인해요.",
  "detail": "공용부 훼손에 대비해 받고 단지마다 금액이 달라요. 금액보다 환급 시점 · 조건이 중요하고 착공 전 복도 · 승강기 사진을 남겨요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   },
   {
    "title": "공사 전 관리사무소 신고부터 엘리베이터 보양까지",
    "publisher": "꾸미고",
    "url": "https://kkumigo.co.kr/space/공사-전-관리사무소-신고부터/"
   }
  ]
 },
 {
  "id": "공사장-생활폐기물",
  "term": "공사장 생활폐기물",
  "aliases": [
   "5톤 미만 폐기물"
  ],
  "trade": "common",
  "easy": "한 공사에서 5톤 미만으로 나오는 공사 폐기물",
  "tip": "작은 공사에서 나온 폐기물이에요. 누가 어떻게 버리는지, 처리비가 견적에 들었는지 확인해요.",
  "detail": "한 공사에서 5톤 이상 나오면 건설폐기물이라 배출자가 폐기물 처리계획서를 구청 등에 신고해요. 5톤 미만은 생활폐기물로 보고, 지자체 조례가 정한 방법으로 버려요. 서울은 버리기 전에 자치구에 신고하게 해서, 자세한 방법은 사는 곳 구청 청소 부서에 확인해요.",
  "use": "인테리어 공사에서 나온 폐기물을 어떻게 버릴지 정할 때 따져요.",
  "images": [],
  "sources": [
   {
    "title": "건설폐기물의 재활용촉진에 관한 법률 제2조 · 제17조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설폐기물의재활용촉진에관한법률/제2조"
   },
   {
    "title": "폐기물관리법 제15조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/폐기물관리법/제15조"
   },
   {
    "title": "소규모 공사장 쓰레기 신고하고 배출하세요",
    "publisher": "서울특별시(자원순환과)",
    "url": "https://news.seoul.go.kr/env/archives/523432"
   }
  ]
 },
 {
  "id": "경미한-행위",
  "term": "경미한 행위",
  "aliases": [
   "경미한 공사(공동주택)"
  ],
  "trade": "common",
  "easy": "구청 허가 · 신고 없이 할 수 있는 세대 내부 공사",
  "tip": "구청 신고 없이 하는 집 안 공사예요. 도배 · 문틀 교체가 여기에 들지만 관리사무소 동의는 받아야 해요.",
  "detail": "창틀 · 문틀 교체, 세대 안 천장 · 벽 · 바닥 마감재 교체, 급 · 배수관 같은 배관설비 교체, 세대 안 난방설비 교체(시설을 부수거나 철거하는 것은 빼요) 등이 들어가요(공동주택관리법 시행규칙 제15조제1항). 그래도 주택 안 구조물 · 설비를 바꾸는 일이라 관리주체(관리사무소) 동의는 받아야 해요(같은 법 시행령 제19조제2항).",
  "use": "도배 · 문틀 교체처럼 구청 신고 없이 하는 공사인지 가릴 때 써요.",
  "images": [],
  "sources": [
   {
    "title": "공동주택관리법 시행규칙 제15조(행위허가 신청 등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행규칙/제15조"
   },
   {
    "title": "공동주택관리법 시행령 제19조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행령/제19조"
   },
   {
    "title": "아파트 입주 전 내부 인테리어 공사를 하려고 합니다. 구청에 신고를 해야 하나요?",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/EasyLawInfoR.laf?csmSeq=1222&easySeq=1641"
   }
  ]
 },
 {
  "id": "관리주체-동의",
  "term": "관리주체 동의",
  "aliases": [
   "관리사무소 동의",
   "공사 신고"
  ],
  "trade": "common",
  "easy": "관리사무소에 공사를 알리고 받는 동의",
  "tip": "관리사무소 동의예요. 서류와 절차가 단지마다 달라 착공 전에 물어봐요.",
  "detail": "도배 · 문틀 교체 같은 경미한 행위로 주택 안 구조물 · 설비를 바꾸거나, 공사 물건을 복도 같은 공용부분에 쌓아 두려면 관리주체 동의를 받아야 해요(공동주택관리법 시행령 제19조제2항). 내는 서류와 절차는 단지 관리규약과 관리사무소 안내를 따라요. 관리규약은 시 · 도가 정한 준칙을 참고해 단지마다 정해요.",
  "use": "도배 · 문틀 교체 같은 집 안 공사를 시작하기 전에 받아요.",
  "images": [],
  "sources": [
   {
    "title": "공동주택관리법 시행령 제19조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행령/제19조"
   },
   {
    "title": "공동주택관리법 제18조(관리규약)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법/제18조"
   },
   {
    "title": "아파트 입주 전 내부 인테리어 공사를 하려고 합니다. 구청에 신고를 해야 하나요?",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/EasyLawInfoR.laf?csmSeq=1222&easySeq=1641"
   },
   {
    "title": "서울특별시 공동주택관리규약 준칙",
    "publisher": "서울특별시",
    "url": "https://openapt.seoul.go.kr/include/mngAgreeInfo.html"
   }
  ]
 },
 {
  "id": "행위허가",
  "term": "행위허가",
  "aliases": [
   "행위신고"
  ],
  "trade": "common",
  "easy": "구조 변경 같은 공사 전에 구청에 받는 허가나 신고",
  "tip": "벽을 헐거나 구조를 바꾸는 공사의 허가 · 신고예요. 도배 · 문틀 교체 같은 마감 교체는 대상이 아니에요.",
  "detail": "공동주택관리법 제35조는 용도 변경, 증축 · 개축 · 대수선, 파손 · 철거, 세대구분형 공동주택 설치, 비내력벽 철거 같은 공사를 하려면 시장 · 군수 · 구청장의 허가를 받거나 신고하게 해요. 시공 업체도 허가 · 신고를 했는지 미리 확인해야 해요. 공사를 마치면 사용검사를 받아요. 처리기간은 구청 민원 안내를 봐요(예: 서울 도봉구 안내는 허가 10일 · 신고 7일).",
  "use": "벽을 헐거나 용도를 바꾸는 공사를 하기 전에 받아요.",
  "images": [],
  "sources": [
   {
    "title": "공동주택관리법 제35조(행위허가 기준 등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법/제35조"
   },
   {
    "title": "공동주택관리법 시행령 제35조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행령/제35조"
   },
   {
    "title": "아파트 입주 > 아파트 구조 변경 공사 > 인테리어 공사",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=1222&ccfNo=2&cciNo=1&cnpClsNo=1"
   },
   {
    "title": "공동주택관리 > 행위허가/신고",
    "publisher": "서울 도봉구청(주택과)",
    "url": "https://www.dobong.go.kr/Contents.asp?code=10009392"
   }
  ]
 },
 {
  "id": "비내력벽",
  "term": "비내력벽",
  "aliases": [
   "비내력 벽"
  ],
  "trade": "common",
  "easy": "건물 무게를 받치지 않는 벽",
  "tip": "무게를 받치지 않는 벽이에요. 헐려면 구청 허가 · 신고와 같은 동 입주자 동의가 필요해요.",
  "detail": "자기 무게만 버티고 바닥 · 지붕 같은 다른 무게는 받지 않는 벽이에요. 아파트에서 비내력벽을 헐려면 구청의 허가를 받거나 신고해야 해요. 철거해도 구조안전에 이상이 없다고 인정되고, 해당 동에 사는 입주자등 2분의 1 이상이 동의해야 해요. 신청할 때 비내력벽임을 증명하는 도면 · 사진과 동의서를 내요.",
  "use": "건물 무게를 받치지 않는 벽이에요. 헐려면 구청 허가 · 신고와 동의가 필요해요.",
  "images": [
   {
    "src": "/guide-img/terms/non_bearing_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/non_bearing_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "공동주택관리법 시행령 제35조 · 별표 3",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행령/제35조"
   },
   {
    "title": "공동주택관리법 시행규칙 제15조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행규칙/제15조"
   },
   {
    "title": "아파트 입주 > 아파트 구조 변경 공사 > 인테리어 공사",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=1222&ccfNo=2&cciNo=1&cnpClsNo=1"
   },
   {
    "title": "소방용어집 > 비내력벽",
    "publisher": "횡성소방서",
    "url": "https://gfsa.gwd.go.kr/hs119/partici/partici_law/partici_law_terms?articleSeq=10003233"
   }
  ]
 },
 {
  "id": "실내건축공사업",
  "term": "실내건축공사업",
  "aliases": [
   "실내건축 면허",
   "인테리어 면허"
  ],
  "trade": "common",
  "easy": "실내 인테리어 공사를 하는 전문건설업 업종",
  "tip": "인테리어 공사의 건설업 업종이에요. 공사예정금액이 1,500만 원 이상이면 건설업 등록 업체인지 확인해요.",
  "detail": "건설산업기본법 시행령 별표 1의 전문공사 업종 가운데 하나예요. 공사예정금액 1,500만 원 미만인 전문공사는 등록 없이 할 수 있고(경미한 건설공사), 그 이상이면 건설업을 등록한 업체만 할 수 있어요. 등록 여부는 KISCON(건설산업지식정보시스템)의 '건설업체정보조회'에서 업체명 · 대표자 · 사업자등록번호로 찾아요.",
  "use": "인테리어 업체가 건설업을 등록했는지 볼 때 확인하는 업종이에요.",
  "images": [],
  "sources": [
   {
    "title": "건설산업기본법 제9조(건설업 등록 등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법/제9조"
   },
   {
    "title": "건설산업기본법 시행령 제8조 · 별표 1",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법시행령/제8조"
   },
   {
    "title": "[피해예방주의보] 인테리어 하자 보수 분쟁 다발, 사업자 선정에 유의해야",
    "publisher": "한국소비자원 대구경북지원",
    "url": "https://www.kca.go.kr/home/sub.do?menukey=4005&mode=view&no=1004580544"
   },
   {
    "title": "건설업체정보조회",
    "publisher": "건설산업지식정보시스템(KISCON)",
    "url": "https://www.kiscon.net/"
   }
  ]
 },
 {
  "id": "경미한-건설공사",
  "term": "경미한 건설공사",
  "aliases": [
   "1,500만원 기준"
  ],
  "trade": "common",
  "easy": "건설업 등록 없이 할 수 있는 작은 공사",
  "tip": "등록 없이 할 수 있는 작은 공사예요. 실내건축 같은 전문공사는 공사예정금액 1,500만 원 미만이 기준이에요.",
  "detail": "건설산업기본법 시행령 제8조는 전문공사는 공사예정금액 1,500만 원 미만, 종합공사는 5,000만 원 미만인 공사를 경미한 건설공사로 정해요. 같은 공사를 여러 계약으로 나눠 맡겨도 금액을 합치고, 고객이 재료를 대면 그 재료의 시장가격과 운임도 더해요.",
  "use": "건설업 등록이 없는 업체에 맡길 수 있는 공사 규모인지 볼 때 따져요.",
  "images": [],
  "sources": [
   {
    "title": "건설산업기본법 제9조(건설업 등록 등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법/제9조"
   },
   {
    "title": "건설산업기본법 시행령 제8조(경미한 건설공사등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법시행령/제8조"
   },
   {
    "title": "[피해예방주의보] 인테리어 하자 보수 분쟁 다발, 사업자 선정에 유의해야",
    "publisher": "한국소비자원 대구경북지원",
    "url": "https://www.kca.go.kr/home/sub.do?menukey=4005&mode=view&no=1004580544"
   }
  ]
 },
 {
  "id": "KISCON",
  "term": "KISCON",
  "aliases": [
   "건설산업지식정보시스템",
   "키스콘"
  ],
  "trade": "common",
  "easy": "건설업체 등록 · 행정처분을 조회하는 공공 시스템",
  "tip": "업체 등록 조회 시스템이에요. 계약 전에 등록 · 처분 이력을 조회해요.",
  "detail": "업체명 · 대표자 · 사업자번호로 등록 여부와 행정처분 · 폐업 · 벌점을 확인해요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "KISCON 건설산업지식정보시스템 건설업체 정보조회",
    "publisher": "국토교통부 건설산업지식정보시스템",
    "url": "https://www.kiscon.net/"
   }
  ]
 },
 {
  "id": "하자담보책임기간",
  "term": "하자담보책임기간",
  "aliases": [
   "하자보수 기간",
   "하자기간"
  ],
  "trade": "common",
  "easy": "시공 하자를 업체가 책임지는 기간",
  "tip": "하자 책임 기간이에요. 인테리어(실내건축)는 1년이 기준이라 계약서에 기간을 적어 둬요.",
  "detail": "건설산업기본법은 업체가 공사를 마친 날과 집을 쓰기 시작한 날 가운데 먼저 온 날부터, 공사 종류별로 정한 기간에 생긴 하자를 책임지게 해요. 기간은 시행령 별표 4에 있고, 등록 건설업자가 시공한 인테리어(실내건축)는 1년이에요. 여러 공사가 섞이면 책임을 나눌 수 없는 경우가 아니면 공사 종류마다 따로 적용해요. 계약에서 기간을 따로 정하면 그 기간과 이유를 계약서에 적어요.",
  "use": "계약서에 하자 보수 기간을 적을 때 기준으로 써요.",
  "images": [],
  "sources": [
   {
    "title": "건설산업기본법 제28조(건설공사 수급인 등의 하자담보책임)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법/제28조"
   },
   {
    "title": "건설산업기본법 시행령 제30조 · 별표 4",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법시행령/제30조"
   },
   {
    "title": "커피전문점 창업ㆍ운영 > 창업준비 > 영업시설 > 인테리어 공사",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=706&ccfNo=3&cciNo=3&cnpClsNo=1"
   },
   {
    "title": "정책Q&A 건설공사 하자담보책임제도",
    "publisher": "국토교통부(건설정책과)",
    "url": "https://www.molit.go.kr/USR/policyTarget/m_24066/dtl.jsp?idx=832"
   }
  ]
 },
 {
  "id": "하자이행보증증권",
  "term": "하자이행보증증권",
  "aliases": [
   "하자보수보증",
   "하자이행보증"
  ],
  "trade": "common",
  "easy": "업체의 하자 보수를 보증기관이 보증하는 증권",
  "tip": "하자 보수를 보증하는 증권이에요. 계약 전에 발급할 수 있는지, 보증 범위와 기간을 물어봐요.",
  "detail": "건설업 공제조합은 조합원 업체에 하자보수보증을 해 줘요(건설산업기본법 제56조). 한국소비자원은 공사로 인한 경제적 피해를 줄이려면 하자보증보험에 가입한 업체를 고르라고 권해요. 계약에서 하자담보책임기간을 따로 정하면, 그 때문에 더 드는 하자보수보증 수수료도 계약서에 적어요(시행령 제30조제2항).",
  "use": "계약 전에 업체가 하자보수 보증서를 낼 수 있는지 물을 때 써요.",
  "images": [],
  "sources": [
   {
    "title": "건설산업기본법 제56조(공제조합의 사업)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법/제56조"
   },
   {
    "title": "건설산업기본법 시행령 제30조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법시행령/제30조"
   },
   {
    "title": "주택 리모델링 소비자피해, 부실시공과 계약불이행이 절반 이상",
    "publisher": "한국소비자원(경기지원 주택공산품팀)",
    "url": "https://www.kca.go.kr/home/sub.do?menukey=4002&mode=view&no=1002951945"
   }
  ]
 },
 {
  "id": "표준계약서",
  "term": "표준계약서",
  "aliases": [
   "실내건축·창호 공사 표준계약서",
   "표준약관 제10079호"
  ],
  "trade": "common",
  "easy": "공정거래위원회가 만든 실내건축 · 창호 공사 계약서 양식",
  "tip": "공정위 계약서 양식이에요. 소비자원도 이 양식으로 공사 내용 · 자재 · 규격을 자세히 적으라고 권해요.",
  "detail": "공정거래위원회 표준약관 제10079호 '실내건축 · 창호 공사 표준계약서'예요(2018. 3. 21. 제정). 업체는 원자재 가격이 올랐다는 이유로 총 공사금액을 올릴 수 없고, 대금을 낼 때 하자가 있으면 보수될 때까지 그만큼 지급을 거절할 수 있어요. 공사 범위 · 물량 · 자재 제품 · 규격을 적은 내역서를 따로 내게 하고, 계약할 때 업체 연락처가 적힌 계약서와 공사 면허 등을 소비자에게 주게 해요.",
  "use": "인테리어 공사 계약서를 쓸 때 양식으로 써요.",
  "images": [],
  "sources": [
   {
    "title": "실내건축·창호 공사 표준계약서 (표준약관 제10079호)",
    "publisher": "공정거래위원회",
    "url": "https://www.ftc.go.kr/www/selectBbsNttView.do?key=202&bordCd=201&nttSn=11181"
   },
   {
    "title": "실내건축·창호 공사 표준계약서 제정(보도자료)",
    "publisher": "공정거래위원회(약관심사과)",
    "url": "https://www.ftc.go.kr/www/selectBbsNttView.do?pageUnit=10&pageIndex=10&searchCnd=all&key=12&bordCd=3&searchViolt=100&nttSn=40720&rltnNttSn=36780"
   },
   {
    "title": "주택 리모델링 소비자피해, 부실시공과 계약불이행이 절반 이상",
    "publisher": "한국소비자원(경기지원 주택공산품팀)",
    "url": "https://www.kca.go.kr/home/sub.do?menukey=4002&mode=view&no=1002951945"
   }
  ]
 },
 {
  "id": "소비자분쟁해결기준",
  "term": "소비자분쟁해결기준",
  "aliases": [
   "분쟁해결기준"
  ],
  "trade": "common",
  "easy": "분쟁 때 쓰는 공정위 고시의 합의 · 권고 기준",
  "tip": "분쟁 때 쓰는 기준이에요. 업체와 따로 정한 해결 방법이 없을 때 기준이 돼요.",
  "detail": "소비자기본법에 따라 공정거래위원회가 고시로 정해요(지금은 고시 제2025-14호, 2025. 12. 18. 시행). 분쟁 당사자가 해결 방법을 따로 정하지 않았을 때 합의 또는 권고의 기준이 돼요. 실내건축공사업 기준은 2023년 12월에 새로 생겼고, 그전 기준은 창호공사만 다뤘어요. 계약서를 못 받았을 때, 공사가 늦어졌을 때, 시공 하자가 생겼을 때 등의 해결 기준이 있어요.",
  "use": "업체와 하자 · 지연 · 계약 해제로 다툴 때 해결 기준을 찾아봐요.",
  "images": [],
  "sources": [
   {
    "title": "소비자기본법 제16조(소비자분쟁의 해결)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/소비자기본법/제16조"
   },
   {
    "title": "소비자분쟁해결기준(공정거래위원회고시 제2025-14호)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/행정규칙/소비자분쟁해결기준"
   },
   {
    "title": "의류건조기·관리기 품질 보증기간 1년…독서실 이용료 반환기준 마련",
    "publisher": "대한민국 정책브리핑(공정거래위원회)",
    "url": "https://www.korea.kr/news/policyNewsView.do?newsId=148923999"
   },
   {
    "title": "이사 > 집 꾸미기 > 주택수리 하자에 관한 분쟁해결기준",
    "publisher": "법제처 찾기 쉬운 생활법령정보",
    "url": "https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=666&ccfNo=2&cciNo=3&cnpClsNo=2"
   }
  ]
 },
 {
  "id": "1372-소비자상담센터",
  "term": "1372 소비자상담센터",
  "aliases": [
   "1372"
  ],
  "trade": "common",
  "easy": "소비자 피해를 상담하는 공공 창구",
  "tip": "소비자 상담 창구예요. 업체와 해결이 안 되면 여기서 상담해요.",
  "detail": "업체가 하자를 부인하거나 연락이 끊기면 상담받고, 한국소비자원 피해구제와 분쟁조정으로 이어갈 수 있어요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "소비자기본법 제55·67조",
    "publisher": "법제처 국가법령정보센터",
    "url": "https://www.law.go.kr/법령/소비자기본법/제67조"
   }
  ]
 },
 {
  "id": "내용증명",
  "term": "내용증명",
  "aliases": [
   "내용증명 우편"
  ],
  "trade": "common",
  "easy": "보낸 내용과 날짜를 우체국이 증명해 주는 우편",
  "tip": "보낸 내용을 증명하는 우편이에요. 업체가 하자 보수를 거부할 때 보내요.",
  "detail": "업체가 하자 보수를 거부하면 하자 내용과 보수 기한을 적어 보내요. 제3자 하자 감정과 함께 손해배상의 근거가 돼요.",
  "use": "",
  "images": [],
  "sources": []
 },
 {
  "id": "잔금",
  "term": "잔금",
  "aliases": [
   "잔금 유보"
  ],
  "trade": "common",
  "easy": "공사가 끝난 뒤 마지막으로 내는 대금",
  "tip": "마지막 대금이에요. 하자 보수가 끝난 뒤 내도록 계약서에 적어요.",
  "detail": "잔금 기준일을 준공일이나 하자보수 완료일로 계약서에 적어요. 하자가 보수될 때까지 그만큼 지급을 미룰 수 있어요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   },
   {
    "title": "실내건축·창호 공사 표준계약서(표준약관 제10079호)",
    "publisher": "공정거래위원회",
    "url": "https://www.ftc.go.kr/www/selectBbsNttView.do?key=202&bordCd=201&nttSn=11181"
   }
  ]
 },
 {
  "id": "명의대여",
  "term": "명의대여",
  "aliases": [
   "면허 대여"
  ],
  "trade": "common",
  "easy": "건설업 등록증 · 상호를 빌려주고 빌리는 것",
  "tip": "남의 건설업 등록증 · 상호로 공사하는 거예요. 계약서의 상호 · 대표자가 등록 정보와 같은지 확인해요.",
  "detail": "건설산업기본법 제21조는 건설사업자가 자기 이름 · 상호나 등록증 · 등록수첩을 남에게 빌려주는 것, 빌리는 것, 이를 알선하는 것을 금지해요. 건축주가 이런 업체와 짜고 공사를 맡기는 것도 금지하고, 벌칙은 같은 법 제95조의2에 있어요. 등록 정보는 KISCON '건설업체정보조회'에서 찾아봐요.",
  "use": "계약할 업체의 등록 정보를 확인할 때 함께 봐요.",
  "images": [],
  "sources": [
   {
    "title": "건설산업기본법 제21조 · 제95조의2",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/건설산업기본법/제21조"
   },
   {
    "title": "건설업체정보조회",
    "publisher": "건설산업지식정보시스템(KISCON)",
    "url": "https://www.kiscon.net/"
   },
   {
    "title": "실내건축·창호 공사 표준계약서 제정(보도자료)",
    "publisher": "공정거래위원회(약관심사과)",
    "url": "https://www.ftc.go.kr/www/selectBbsNttView.do?pageUnit=10&pageIndex=10&searchCnd=all&key=12&bordCd=3&searchViolt=100&nttSn=40720&rltnNttSn=36780"
   }
  ]
 },
 {
  "id": "사용검사",
  "term": "사용검사",
  "aliases": [
   "사용검사 신청"
  ],
  "trade": "common",
  "easy": "허가 · 신고한 공사를 마친 뒤 구청에서 받는 검사",
  "tip": "구청에 허가 · 신고한 공사를 마쳤을 때 받는 검사예요. 구청 신고 없이 하는 도배 · 문틀 교체와는 상관없어요.",
  "detail": "공동주택관리법 제35조제5항은 허가를 받거나 신고한 공사를 마치면 시장 · 군수 · 구청장의 사용검사를 받게 해요. 신청서에 시공자의 공사확인서(감리 대상이면 감리자의 감리의견서도)를 붙이고, 구청은 허가 · 신고 내용과 맞는지 확인한 뒤 사용검사필증을 내줘요. 처리기간은 구청 민원 안내를 봐요(예: 서울 도봉구 안내는 15일).",
  "use": "허가 · 신고한 공사를 마친 뒤 구청에 신청해요.",
  "images": [],
  "sources": [
   {
    "title": "공동주택관리법 제35조(행위허가 기준 등)",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법/제35조"
   },
   {
    "title": "공동주택관리법 시행규칙 제15조",
    "publisher": "국가법령정보센터(법제처)",
    "url": "https://www.law.go.kr/법령/공동주택관리법시행규칙/제15조"
   },
   {
    "title": "공동주택관리 > 행위허가/신고",
    "publisher": "서울 도봉구청(주택과)",
    "url": "https://www.dobong.go.kr/Contents.asp?code=10009392"
   }
  ]
 },
 {
  "id": "전기-1차",
  "term": "전기 1차",
  "aliases": [
   "입선",
   "전기 배선 작업"
  ],
  "trade": "oos",
  "easy": "목공으로 벽 · 천장을 닫기 전에 하는 배선 작업",
  "tip": "벽 · 천장을 닫기 전 배선이에요. 천장을 덮기 전에 사진을 받아 둬요.",
  "detail": "LX 공정표에서 목공과 병행할 수 있는 단계예요. 천장을 덮기 전에 회로를 나누고 배선을 빼 두며, 사진을 받아 두라고 권해요.",
  "use": "",
  "oos": true,
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   },
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   }
  ]
 },
 {
  "id": "전기-2차",
  "term": "전기 2차",
  "aliases": [
   "조명·스위치 설치"
  ],
  "trade": "oos",
  "easy": "도배가 끝난 뒤 조명 · 스위치 · 콘센트를 다는 마무리 전기 작업",
  "tip": "마무리 전기 작업이에요. 보통 도배가 끝난 뒤에 해요.",
  "detail": "LX 공정표상 마지막 공정 쪽에 와요. 스위치 커버 · 조명기구는 도배 후 설치한다는 LH 시방서 기준과도 맞아요.",
  "use": "",
  "oos": true,
  "images": [],
  "sources": [
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   },
   {
    "title": "LHCS 41 51 05 도배공사",
    "publisher": "한국토지주택공사(LH)",
    "url": "https://enc.ksocket.com/lhcs/lhcs-lhcs-41-51-05-%EB%8F%84%EB%B0%B0%EA%B3%B5%EC%82%AC/"
   }
  ]
 },
 {
  "id": "마루",
  "term": "마루",
  "aliases": [
   "강마루",
   "원목마루"
  ],
  "trade": "oos",
  "easy": "나무 계열 바닥재",
  "tip": "나무 바닥재예요. 도배와 순서는 자료마다 달라 업체와 정해요.",
  "detail": "LX 공정표는 마루를 도배 전에 깔라고 하지만 도배를 먼저 한다는 자료도 있어 업체와 정해요. 시공 뒤 24시간 안정화가 필요하다는 자료가 있어요.",
  "use": "나무 느낌의 바닥을 원할 때 깔아요. 도배와 순서를 업체와 정해요.",
  "ask": "마루와 도배는 어느 쪽을 먼저 하나요?",
  "oos": true,
  "images": [
   {
    "src": "/guide-img/terms/wood_floor_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/wood_floor_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   },
   {
    "title": "내만집 가이드(공정 순서·작업일·신고·체크리스트 등)",
    "publisher": "내만집",
    "url": "https://nmjib.com/guide/"
   },
   {
    "title": "인테리어 공사 순서 이해하기",
    "publisher": "오늘의집",
    "url": "https://ohou.se/advices/8467"
   }
  ]
 },
 {
  "id": "장판",
  "term": "장판",
  "aliases": [
   "PVC 장판"
  ],
  "trade": "oos",
  "easy": "비닐(PVC) 계열 바닥재",
  "tip": "비닐 바닥재예요. 보통 도배 뒤에 깔아요.",
  "detail": "LX 공정표 기준 장판은 도배 뒤에 깔아요. 바닥재를 벽으로 꺾어 올려 걸레받이를 대신하기도 해요.",
  "use": "물에 강하고 저렴한 바닥을 원할 때 깔아요. 보통 도배 뒤에 깔아요.",
  "oos": true,
  "images": [
   {
    "src": "/guide-img/terms/vinyl_floor_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/vinyl_floor_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "인테리어-필름",
  "term": "인테리어 필름",
  "aliases": [
   "필름 시공",
   "필름 리폼"
  ],
  "trade": "oos",
  "easy": "문 · 몰딩 · 가구 표면에 접착 필름을 붙여 새것처럼 바꾸는 공정",
  "tip": "표면에 필름을 붙이는 공정이에요. 문 · 몰딩이 멀쩡하고 색만 바꿀 때 교체보다 싸게 골라요.",
  "detail": "도배 전에 하고 표면 청소 · 퍼티 · 프라이머 뒤에 붙여요. 시공 후 며칠 안에 기포가 생기는지 검수해요.",
  "use": "문 · 몰딩 · 가구를 바꾸지 않고 겉면만 새것처럼 바꿀 때 써요.",
  "oos": true,
  "images": [
   {
    "src": "/guide-img/terms/interior_film_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/interior_film_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "숨고 블로그 필름시공 비용",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/필름시공/"
   },
   {
    "title": "LX Z:IN 인테리어 공정별 체크리스트",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/7398?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "젯소",
  "term": "젯소",
  "aliases": [
   "젯소 칠"
  ],
  "trade": "oos",
  "easy": "페인트를 칠하기 전에 바르는 바탕 도료",
  "tip": "페인트 바탕 도료예요. 짙은 색을 밝게 칠할 때 2~3회 발라요.",
  "detail": "짙은 색 몰딩을 밝은 색으로 칠할 때 2~3회 발라 바탕색을 가려요. 그 뒤 붓으로 테두리, 롤러로 면을 칠해요.",
  "use": "짙은 색 몰딩 · 문을 밝은 색으로 칠하기 전에 바탕색을 가릴 때 발라요.",
  "oos": true,
  "images": [
   {
    "src": "/guide-img/terms/gesso_b.webp",
    "kind": "입체 그림"
   },
   {
    "src": "/guide-img/terms/gesso_c.webp",
    "kind": "단면 그림"
   }
  ],
  "sources": [
   {
    "title": "LX Z:IN 몰딩 선택·시공·교체 가이드",
    "publisher": "LX하우시스(LX Z:IN)",
    "url": "https://www.lxzin.com/styling/style-guide/detail/6979?guideTab=AZ01"
   }
  ]
 },
 {
  "id": "전용면적",
  "term": "전용면적",
  "aliases": [
   "전용㎡",
   "실평수"
  ],
  "trade": "common",
  "easy": "세대가 실제로 쓰는 면적",
  "tip": "실제로 쓰는 면적이에요. 견적 비교는 이 면적으로 맞추는 게 좋아요.",
  "detail": "관리비 고지서 · 등기부에 적힌 ㎡ 면적이에요. 도배 견적은 전용면적 기준으로 맞추라는 안내가 있고 1㎡는 0.3025평이에요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "goodservice '도배 장판 비용 25평·34평'",
    "publisher": "goodservice",
    "url": "https://goodservice.kr/659"
   },
   {
    "title": "숨고 블로그 '도배비용 기준표와 숨은 추가비 7가지'",
    "publisher": "숨고",
    "url": "https://soomgo.com/blog/interior/도배비용/"
   }
  ]
 },
 {
  "id": "공급면적",
  "term": "공급면적",
  "aliases": [
   "분양평",
   "분양면적"
  ],
  "trade": "common",
  "easy": "'34평'처럼 분양 평형으로 부르는 면적",
  "tip": "분양 평형 면적이에요. '평당' 견적이면 공급인지 전용인지 확인해요.",
  "detail": "시장에서는 34평을 전용 84㎡ 타입으로 부르는 식이에요. 공급과 전용이 섞이면 '평당' 견적 비교가 틀어져요.",
  "use": "",
  "images": [],
  "sources": [
   {
    "title": "얼마드나 블로그(목공 비용·공정·체크리스트 글 모음)",
    "publisher": "얼마드나",
    "url": "https://ulmadna.com/blog/"
   },
   {
    "title": "견적서 읽기 가이드 모음(interiorguide, demade51, goodservice/778, ganatoday)",
    "publisher": "interiorguide 외",
    "url": "https://interiorguide.co.kr/3079/"
   }
  ]
 }
];

"""평가 사례의 집 조건 값 (공정 의견 · 라우터 · 전문가 생성기가 같이 쓴다). 표준 라이브러리 + 계산 엔진 환산만 쓴다.

면적은 상담 코드(consult.service._area)와 같은 환산으로 ㎡ 소수 한 자리 문자열을 만든다.
면적 기준을 '모르겠어요'로 둔 집은 공급면적으로 계산하고, 생성기가 to_check에 남긴다.
"""

import random
from decimal import Decimal

from app.calc.common import m2, pyeong_to_m2
from evaluation.common.gen import Fragments, noisy

SIZES = ("S", "M", "L")  # 공급 평형 기준 대략 ~24평 · 25~35평 · 36평~
BASIS = ("supply", "exclusive", "unknown")
YEARS = ("none", "old", "mid", "new")  # 준공 연도 안 적음 · ~1999 · 2000~2012 · 2013~

_PY_COMMON = {"S": (18, 20, 24), "M": (25, 32, 33, 34), "L": (40, 43, 45, 49, 52)}
_PY_RANGE = {"S": (16, 24), "M": (25, 35), "L": (36, 60)}
_SU_M2 = {"S": (56.0, 82.0), "M": (83.0, 117.0), "L": (118.0, 198.0)}
_EX_COMMON = {"S": (39, 49, 51, 59), "M": (74, 76, 84), "L": (99, 101, 114, 125, 135)}
_EX_M2 = {"S": (39.0, 59.9), "M": (60.0, 85.0), "L": (85.1, 135.0)}
_EX_PY = {"S": (12, 18), "M": (19, 26), "L": (27, 40)}
_YEAR = {"old": (1985, 1999), "mid": (2000, 2012), "new": (2013, 2024)}


def _m2(v: float) -> str:
    return str(m2(Decimal(str(v))))


def _py(p: int) -> str:
    return str(pyeong_to_m2(Decimal(p)))


def area(r: random.Random, basis: str, size: str) -> dict:
    """{'area_m2': '112.4', 'area_basis': 'supply', 'area_said': '34평'} (area_said는 고객이 말한 꼴)"""
    if basis == "exclusive":
        if r.random() < 0.7:
            v = (
                r.choice(_EX_COMMON[size])
                if r.random() < 0.5
                else round(r.uniform(*_EX_M2[size]), 1)
            )
            return {"area_m2": _m2(v), "area_basis": "exclusive", "area_said": f"전용 {v}㎡"}
        p = r.randint(*_EX_PY[size])
        return {"area_m2": _py(p), "area_basis": "exclusive", "area_said": f"실평수 {p}평"}
    if basis == "supply" and r.random() < 0.2:
        v = round(r.uniform(*_SU_M2[size]), 1)
        return {"area_m2": _m2(v), "area_basis": "supply", "area_said": f"공급 {v}㎡"}
    p = r.choice(_PY_COMMON[size]) if r.random() < 0.5 else r.randint(*_PY_RANGE[size])
    said = f"{p}평" if basis == "supply" else f"{p}평 (공급 · 전용 모름)"
    return {"area_m2": _py(p), "area_basis": "supply", "area_said": said}


def built_year(r: random.Random, bucket: str) -> int | None:
    return None if bucket == "none" else r.randint(*_YEAR[bucket])


# 견적 받기에서 고객이 적은 공간 이름 (번호 % 3 == 2는 held-out 전용).
# 욕실 · 화장실은 범위 밖 공사 키워드와 겹쳐 넣지 않는다
SPACES = Fragments(
    {
        "space": [
            "거실", "안방", "작은방", "주방", "현관", "드레스룸", "아이방", "서재", "옷방",
            "큰방", "침실", "작은방1", "작은방2", "알파룸", "공부방", "부부 침실", "막내방", "손님방",
            "거실 겸 주방", "팬트리", "현관 복도", "아기방", "드레스 룸", "작업실", "게스트룸", "중간방",
            "끝방", "건넌방", "복도", "애기방",
        ]
    }
)  # fmt: skip
SPACE_PATTERNS = ("none", "one", "few", "all")


def space_names(r: random.Random, pattern: str, split: str, used: list[str]) -> list[str]:
    """공간 이름 0개 · 1개 · 2~3개 · 4~6개. 15%는 띄어쓰기 잡음을 넣는다 (고객이 적은 이름이라)"""
    if pattern == "none":
        return []
    k = {"one": 1, "few": r.choice((2, 3)), "all": r.randint(4, 6)}[pattern]
    names = SPACES.sample(r, "space", split, k, used)
    if r.random() < 0.15:
        i = r.randrange(len(names))
        names[i], _ = noisy(names[i], r, k=1, ops=("nospace", "add_space"))
    return names

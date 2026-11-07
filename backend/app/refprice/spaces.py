"""공간 종류별 몫 (2026 하반기 s1, 가정값). 고른 공간만큼 표준견적서 수량을 잡을 때 쓴다(calc/spaces.py).

흔한 평면(전용 59 · 84 · 114㎡형)의 방 치수로 계산했다. 천장고 2.3m, 창 · 문 · 주방 가구 · 신발장 ·
드레스룸 선반 자리는 뺐다. 몫은 모두 '그 종류 한 곳'이고, 표에 없는 종류(욕실 · 다용도실)는 0이다.
"""

from decimal import Decimal

from app.calc.spaces import SpaceShares

_D = Decimal


def _t(**kw: str) -> dict:
    return {k: _D(v) for k, v in kw.items()}


SPACES_2026H2 = SpaceShares(
    version="s1",
    # 도배 면적(벽 + 천장) 중 한 곳 몫
    paper={
        "10": _t(
            living="0.30",
            kitchen="0.09",
            master="0.27",
            room="0.21",
            dress="0.06",
            hall="0.06",
            entry="0.06",
        ),
        "20": _t(
            living="0.23",
            kitchen="0.12",
            master="0.21",
            room="0.155",
            dress="0.06",
            hall="0.08",
            entry="0.055",
        ),
        "30": _t(
            living="0.235",
            kitchen="0.11",
            master="0.18",
            room="0.135",
            dress="0.06",
            hall="0.095",
            entry="0.05",
        ),
        "40": _t(
            living="0.205",
            kitchen="0.11",
            master="0.15",
            room="0.105",
            dress="0.06",
            hall="0.105",
            entry="0.05",
        ),
        "50": _t(
            living="0.20",
            kitchen="0.10",
            master="0.14",
            room="0.095",
            dress="0.06",
            hall="0.10",
            entry="0.045",
        ),
    },
    # 몰딩 + 걸레받이 길이 중 한 곳 몫 (주방은 가구, 현관은 신발장 자리만큼 걸레받이가 적다)
    edge={
        "10": _t(
            living="0.235",
            kitchen="0.10",
            master="0.27",
            room="0.22",
            dress="0.08",
            hall="0.09",
            entry="0.08",
        ),
        "20": _t(
            living="0.18",
            kitchen="0.085",
            master="0.22",
            room="0.175",
            dress="0.085",
            hall="0.10",
            entry="0.07",
        ),
        "30": _t(
            living="0.18",
            kitchen="0.08",
            master="0.18",
            room="0.145",
            dress="0.085",
            hall="0.125",
            entry="0.06",
        ),
        "40": _t(
            living="0.15",
            kitchen="0.075",
            master="0.155",
            room="0.12",
            dress="0.075",
            hall="0.13",
            entry="0.06",
        ),
        "50": _t(
            living="0.15",
            kitchen="0.075",
            master="0.14",
            room="0.105",
            dress="0.075",
            hall="0.13",
            entry="0.06",
        ),
    },
    # 천장(바닥) 면적 ÷ 전용면적. 평탄화 면적에 쓴다(거실을 고르면 거실 천장)
    ceiling={
        "10": _t(
            living="0.35",
            kitchen="0.14",
            master="0.25",
            room="0.17",
            dress="0.05",
            hall="0.04",
            entry="0.04",
        ),
        "20": _t(
            living="0.27",
            kitchen="0.14",
            master="0.195",
            room="0.13",
            dress="0.05",
            hall="0.05",
            entry="0.04",
        ),
        "30": _t(
            living="0.285",
            kitchen="0.145",
            master="0.165",
            room="0.11",
            dress="0.06",
            hall="0.065",
            entry="0.035",
        ),
        "40": _t(
            living="0.265",
            kitchen="0.14",
            master="0.15",
            room="0.09",
            dress="0.06",
            hall="0.08",
            entry="0.045",
        ),
        "50": _t(
            living="0.26",
            kitchen="0.13",
            master="0.14",
            room="0.08",
            dress="0.06",
            hall="0.08",
            entry="0.04",
        ),
    },
    doors={"master": 1, "room": 1},
    doors_whole={"10": 2, "20": 3, "30": 3, "40": 4, "50": 4},
    whole_at=_D("0.85"),
    fallback="room",
    sources={
        "shares": "흔한 평면 방 치수로 계산(가정값): 84㎡형 거실 4.2×5.7 · 안방 3.6×3.9 · 작은방 3.0×3.3 · "
        "2.7×3.3m 등. 합계가 엔진 집 전체 수량(공급 × 2.3)과 1% 안에서 맞음. 작은방 33.5㎡ · "
        "몰딩 + 걸레받이 23.7m는 부분 시공 조사(T8)의 작은방 35.2㎡ · 24.3m와 맞음. AI Hub 평면도로 다시 맞춰야 함",
        "whole_at": "기본 공간 6곳(거실 · 주방 · 안방 · 작은방 2 · 복도, 30평대 몫 0.89)을 집 전체로 본다. "
        "현관 · 드레스룸은 집 전체 공사에 보통 같이 들어감. 40평대는 작은방이 3개라 6곳이면 약 0.78",
        "doors": "안방 · 작은방(침실)만 방문으로 센다. 욕실 · 드레스룸 문은 넣지 않음(가정)",
    },
)

# 지금 계산에 쓰는 공간 몫
SPACES = SPACES_2026H2

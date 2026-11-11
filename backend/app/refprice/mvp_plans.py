"""MVP 예시 평면도: 공개 평면도에서 읽은 공간 치수(mm)와 출처 (mvp_plans.json, 20곳).

치수는 벽 중심선이고, 공간마다 읽은 방법(how)과 확신(sure)을 남겼다. 평면도 그림은 화면 쪽에 둔다.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

from app.calc.plan_qty import Plan, PlanSpace, Window

VERSION = "plans-2026.11-v9"
_FILE = Path(__file__).with_name("mvp_plans.json")


@dataclass(frozen=True)
class PlanInfo:
    id: str
    name: str
    region: str
    type: str  # 분양 타입 (예: 84A)
    supply_m2: Decimal
    excl_m2: Decimal | None
    supply_py: int
    rooms: int
    baths: int
    layout: str
    year: int | None  # 입주 연도 (계획 도면이면 없음)
    stage: str | None  # 계획 도면 표시
    src: str
    src_url: str
    img: str  # 화면 쪽 그림 경로
    drawn: str  # 그린 평면: basic(확장 전) · expanded(확장)
    has_ext: bool  # 확장 여부로 수량이 달라지는 공간이 있음
    plan: Plan


def _plan(p: dict) -> Plan:
    spaces = tuple(
        PlanSpace(
            id=s["id"],
            ko=s["ko"],
            kind=s["kind"],
            w_mm=int(s["w"]),
            d_mm=int(s["d"]),
            paper=s["paper"],
            ext_mm=int(s.get("ext", 0)),
            ext_side=s.get("ext_side", "d"),
            open_mm=int(s.get("open", 0)),
            door_open=int(s.get("door_open", 0)),
            own_door=bool(s.get("own_door")),
            windows=tuple(Window(int(w["w"]), w["t"]) for w in s.get("win", [])),
            sure=s.get("sure", "mid"),
        )
        for s in p["spaces"]
    )
    wall = p.get("wall_mm") or {}
    return Plan(
        spaces=spaces, wall_int_mm=int(wall.get("int", 180)), wall_given=bool(wall.get("given"))
    )


@cache
def plans() -> dict[str, PlanInfo]:
    rows = json.loads(_FILE.read_text(encoding="utf-8"), parse_float=Decimal)
    out = {}
    for p in rows:
        plan = _plan(p)
        out[p["id"]] = PlanInfo(
            id=p["id"],
            name=p["name"],
            region=p["region"],
            type=p["type"],
            supply_m2=p["supply_m2"],
            excl_m2=p.get("excl_m2"),
            supply_py=p["supply_py"],
            rooms=p["rooms"],
            baths=p["baths"],
            layout=p["layout"],
            year=p.get("year"),
            stage=p.get("stage"),
            src=p["src"],
            src_url=p["src_url"],
            img=p["img"],
            drawn=p["drawn"],
            has_ext=any(s.ext_mm for s in plan.spaces),
            plan=plan,
        )
    return out

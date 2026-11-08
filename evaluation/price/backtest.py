"""실견적 ↔ 믿집 계산 엔진 비교(백테스트). 계산 엔진(backend/app/calc)만 쓰고 DB는 쓰지 않는다.

실견적 한 건마다 같은 조건(평형 · 공간 · 등급 · 천장 · 철거 포함 여부 · 부가세)으로 표준견적서(공공 기준 금액)와
예상 범위(10 · 50 · 90%)를 계산하고, 실견적이 범위 안인지 · 분포의 몇 % 지점(PIT)인지 본다.
가정값을 고칠 때는 dev로만 맞추고 heldout으로 확인한다(id 해시로 2:1, 늘 같은 나눔).

쓰는 법(backend 폴더에서):
  uv run python ../evaluation/price/backtest.py              # 요약
  uv run python ../evaluation/price/backtest.py --csv out.csv  # 건별 결과
  --ext: 확장 여부를 모르면 확장으로 본다 / --vat: 부가세 여부를 모르면 포함으로 본다
  --rules 2026H2-r2: 예전 범위 가정값으로 돌려 지금 값과 견준다 / --since 2025: 그해 이후 자료만
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app.calc import dobae, mokgong, spaces
from app.calc.common import COUNTED, PYEONG_M2, pyeong_to_m2
from app.calc.price_range import price_cdf, price_range
from app.quote import ranges
from app.refprice.book import DOBAE, MOKGONG
from app.refprice.market import RANGE, RANGE_2026H2, RANGE_2026H2_R3, RANGE_2026H2_R4
from app.refprice.spaces import SPACES

DATA = HERE / "real_quotes.jsonl"
RULES = {
    x.version: x for x in (RANGE_2026H2, RANGE_2026H2_R3, RANGE_2026H2_R4)
}  # 견줄 수 있는 범위 가정값
ALPHA = 0.2  # 80% 구간(10~90%)의 바깥 몫. 구간 점수에 쓴다
FIRST_BATCH = "2026-11-08"  # batch 칸이 없는 자료(첫 수집 585건)
ROLL_M2 = {"silk": Decimal("16.5"), "hapji": Decimal("16.5")}  # 실크 · 광폭 합지 1롤
SOPOK_M2 = Decimal("5.3")  # 소폭 합지 1롤
LOSS = Decimal("1.12")  # 롤 수에 든 로스(무늬 · 자투리 · 방마다 올림)
WHOLE = ["거실", "주방", "안방", "작은방 1", "작은방 2", "작은방 3", "복도", "드레스룸"]
# 방 하나를 다 하지 않는 공사(천장만 · 벽 한 면 · 부분)는 공간 몫 모델로 나타낼 수 없어 비교에서 뺀다
SUB_ROOM = ("천장", "부분", "일부", "1면", "한 면", "1폭", "한쪽")


class _Line:
    def __init__(self, ln) -> None:
        self.key, self.qty, self.amount, self.state = ln.key, ln.qty, ln.amount, ln.state


def split_of(rid: str) -> str:
    """id 해시로 dev : heldout = 2 : 1"""
    return "heldout" if int(hashlib.sha1(rid.encode()).hexdigest(), 16) % 3 == 0 else "dev"


def load(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"건너뜀 {path.name}:{i} ({e})", file=sys.stderr)
    return rows


def usable(r: dict) -> str:
    """비교에서 뺄 이유(빈 문자열이면 비교한다)"""
    if not r.get("price") or r.get("trade") not in ("dobae", "mokgong"):
        return "가격 · 공정 없음"
    notes = r.get("notes") or ""
    if "비교 제외" in notes or "비교 주의" in notes or "누수" in notes or r.get("price_includes"):
        return "다른 공정 · 누수 보수 포함"
    if r.get("scope") not in ("whole", "partial"):
        return "범위(집 전체 · 일부) 모름"
    door_only = set(r.get("items") or []) == {"door"} and r.get("doors")
    if r.get("scope") == "partial" and not r.get("spaces") and not door_only:
        return "일부 공간인데 공간 모름"  # 방문만 고친 목공은 짝 수로 계산해 공간이 없어도 된다
    if any(w in s for s in r.get("spaces") or [] for w in SUB_ROOM):
        return "방 안 일부(천장만 · 벽 한 면)"
    if r.get("price_parts") in ("material_only", "labour_only"):
        return "자재만 · 인건비만"
    if r.get("scope") == "whole" and not (r.get("pyeong") or r.get("exclusive_m2")):
        return "집 전체인데 평형 없음"
    if r.get("trade") == "mokgong":
        items = set(r.get("items") or [])
        if not items & set(mokgong.ITEMS):
            return "목공 항목 없음"
        if "other" in items or ("casing" in items and "door" not in items):
            return "표준 목공 밖 작업 포함(가벽 · 문선만 등)"
    return ""


def _size(r: dict) -> tuple[Decimal, str, str, bool]:
    """(면적, 기준, 평형대, 평형을 알았는지). 모르면 30평대 대표 평형"""
    if r.get("exclusive_m2"):
        area = Decimal(str(r["exclusive_m2"]))
        return area, "exclusive", spaces.band_of(area * Decimal("1.3") / PYEONG_M2), True
    if r.get("pyeong"):
        p = Decimal(str(r["pyeong"]))
        if r.get("area_basis") == "exclusive":
            return p * PYEONG_M2, "exclusive", spaces.band_of(p * Decimal("1.3")), True
        return pyeong_to_m2(p), "supply", spaces.band_of(p), True
    return pyeong_to_m2(Decimal(34)), "supply", "30", False


def _conds(r: dict, inp, trade: str):
    """실견적이 철거 · 폐기물을 포함했는지에 맞춰 '실측 후' 줄을 고친다(포함 → 늘 함, 별도 · 없음 → 뺌)"""
    conds = dict(inp.conds)
    removal = ["removal"] if trade == "dobae" else ["remove_trim", "remove_door", "remove_ceiling"]
    for key, state in [(k, r.get("removal")) for k in removal] + [("waste", r.get("waste"))]:
        if key not in conds:
            continue
        if state == "included":
            conds[key] = "yes"
        elif state in ("separate", "none"):
            del conds[key]
    return replace(inp, conds=conds)


def engine(r: dict, ext_default: bool, vat_default: bool, rules=RANGE) -> dict:
    trade = r["trade"]
    area, basis, band, known = _size(r)
    occupied = bool(r.get("occupied"))
    ext = ext_default if r.get("balcony_ext") is None else bool(r["balcony_ext"])
    names = r.get("spaces") or []
    pk = spaces.pick(names, band, SPACES) if r.get("scope") == "partial" and names else None
    if trade == "dobae":
        grade = "economy" if r.get("grade") == "hapji" else "basic"
        ceiling = True if r.get("ceiling") is None else bool(r["ceiling"])
        share = pk.paper if pk else Decimal(1)
        q = dobae.quote(
            dobae.DobaeInput(area, basis, grade, ceiling, occupied, ext, share=share), DOBAE
        )
        qty = {"paper_m2": q.paper_m2}
    else:
        grade = None
        items = tuple(i for i in r["items"] if i in mokgong.ITEMS)
        doors = int(r.get("doors") or 0) or (
            (max(pk.doors, 1) if pk else 3) if "door" in items else 0
        )
        flat = None
        if "flatten" in items and r.get("flatten_m2"):
            ex = area if basis == "exclusive" else area / Decimal("1.3")
            flat = min(Decimal(str(r["flatten_m2"])) / ex, Decimal(1))
        elif pk:
            flat = pk.flat_m2_share
        q = mokgong.quote(
            mokgong.MokgongInput(
                area,
                basis,
                items,
                occupied,
                doors=doors,
                door_frame=r.get("door_frame") is not False,
                share=pk.molding if pk else Decimal(1),
                base_share=pk.base if pk else None,
                flat_share=flat,
                flat_living=("living" in pk.kinds) if pk else True,
            ),
            MOKGONG,
        )
        qty = {"molding_m": q.molding_m, "doors_calc": q.doors}
    k = ranges.Known("area" if known else "band", pk or spaces.pick(WHOLE, band, SPACES))
    vat = r.get("vat") or "unknown"
    with_vat = vat == "included" or (vat == "unknown" and vat_default)
    lines = [_Line(x) for x in q.lines]
    inp = _conds(r, ranges.range_input(trade, grade, lines, k, exempt=not with_vat), trade)
    pr = price_range(inp, rules, explain=False)
    price = int(r["price"])
    supply = sum(ln.amount for ln in q.lines if ln.state in COUNTED and ln.amount is not None)
    std = q.total if with_vat else supply
    return {
        "std": std,
        "low": pr.low,
        "mid": pr.mid,
        "high": pr.high,
        "pit": float(price_cdf(inp, rules, price)),
        "sigma": float(pr.sigma),
        "inside": pr.low <= price <= pr.high,
        "ratio_mid": price / pr.mid,
        "ratio_std": price / std if std else None,
        "partial": pk is not None,
        "known_size": known,
        **qty,
    }


def quantity(r: dict, e: dict) -> float | None:
    """보고된 수량 ÷ 엔진 수량 (도배: 롤 · 시공평 → ㎡, 목공: 몰딩 m · 본)"""
    if r["trade"] == "dobae" and e.get("paper_m2"):
        rolls = r.get("rolls") or ((r.get("ceiling_rolls") or 0) + (r.get("wall_rolls") or 0))
        roll_type = (r.get("breakdown") or {}).get("roll_type")
        if rolls and roll_type == "mixed":
            return None  # 소폭 · 광폭이 섞이면 롤 수로 면적을 알 수 없다
        if rolls and r.get("grade") in ("silk", "hapji", "mixed"):
            roll_m2 = SOPOK_M2 if roll_type == "sopok" else ROLL_M2["silk"]
            m2 = Decimal(str(rolls)) * roll_m2 / LOSS
        elif r.get("area_pyeong"):
            m2 = Decimal(str(r["area_pyeong"])) * PYEONG_M2
        else:
            return None
        return float(m2 / e["paper_m2"])
    if r["trade"] == "mokgong" and e.get("molding_m"):
        m = r.get("molding_m") or (r.get("molding_pcs") or 0) * 2.4
        return float(Decimal(str(m)) / e["molding_m"]) if m else None
    return None


def summary(rows: list[dict], label: str) -> str:
    if not rows:
        return f"{label}: 0건"
    n = len(rows)
    inside = sum(x["inside"] for x in rows) / n
    below = sum(x["price"] < x["low"] for x in rows) / n
    above = sum(x["price"] > x["high"] for x in rows) / n
    rmid = statistics.median(x["ratio_mid"] for x in rows)
    rstd = statistics.median(x["ratio_std"] for x in rows if x["ratio_std"])
    err = statistics.median(abs(math.log(x["ratio_mid"])) for x in rows)
    pit = statistics.mean(x["pit"] for x in rows)
    return (
        f"{label}: {n}건 | 범위 안 {inside:.0%} (아래 {below:.0%} · 위 {above:.0%}) | "
        f"실견적 ÷ 범위 가운데 {rmid:.2f} | 실견적 ÷ 표준견적서 {rstd:.2f} | "
        f"|log 오차| 중앙값 {err:.2f} | PIT 평균 {pit:.2f} | 구간 점수 {interval_score(rows):.2f}"
    )


def interval_score(rows: list[dict]) -> float:
    """구간 점수(작을수록 좋음): 폭 + 범위 밖으로 벗어난 만큼 × 2/α, 실견적 대비 평균.
    좁기만 한 범위(자주 벗어남)와 넓기만 한 범위(늘 맞지만 쓸모없음)를 함께 벌한다."""
    k = 2 / ALPHA
    return statistics.mean(
        (
            (x["high"] - x["low"])
            + k * max(x["low"] - x["price"], 0)
            + k * max(x["price"] - x["high"], 0)
        )
        / x["price"]
        for x in rows
    )


def fit(rows: list[dict], label: str) -> str:
    """보정 힌트: log(실견적 ÷ 가운데)의 중앙값(중심 치우침)과 강건 흩어짐(1.4826 × MAD) vs 엔진 σ"""
    if len(rows) < 5:
        return f"{label}: {len(rows)}건(5건 미만이라 생략)"
    lr = [math.log(x["ratio_mid"]) for x in rows]
    bias = statistics.median(lr)
    spread = 1.4826 * statistics.median(abs(v - bias) for v in lr)
    model = statistics.median(x["sigma"] for x in rows)
    return (
        f"{label}: {len(rows)}건 | 중심 × {math.exp(bias):.2f} 이면 치우침 0 | "
        f"실제 흩어짐 σ {spread:.2f} vs 엔진 σ {model:.2f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--csv")
    ap.add_argument("--ext", action="store_true", help="확장 여부를 모르면 확장으로")
    ap.add_argument("--vat", action="store_true", help="부가세 여부를 모르면 포함으로")
    ap.add_argument("--split", choices=("all", "dev", "heldout"), default="all")
    ap.add_argument("--fit", action="store_true", help="구간별 중심 치우침 · 흩어짐 보정 힌트")
    ap.add_argument(
        "--rules",
        choices=tuple(RULES),
        default=RANGE.version,
        help="범위 가정값(기본: 지금 쓰는 값)",
    )
    ap.add_argument("--since", type=int, help="이 해 이후 자료만(날짜 없는 자료는 뺀다)")
    ap.add_argument("--batch", help=f"이 수집 묶음만(batch 칸, 없으면 첫 수집 {FIRST_BATCH})")
    a = ap.parse_args()
    rules = RULES[a.rules]
    rows = load(Path(a.data))
    out, skipped = [], {}
    for r in rows:
        why = usable(r)
        if not why and a.split != "all" and split_of(r["id"]) != a.split:
            why = "다른 나눔"
        year = str(r.get("date") or "")[:4]
        if not why and a.since and not (year.isdigit() and int(year) >= a.since):
            why = f"{a.since}년 전 · 날짜 없음"
        if not why and a.batch and (r.get("batch") or FIRST_BATCH) != a.batch:
            why = "다른 수집 묶음"
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        e = engine(r, a.ext, a.vat, rules)
        rec = {
            "id": r["id"],
            "split": split_of(r["id"]),
            "trade": r["trade"],
            "source": r.get("source"),
            "date": r.get("date"),
            "region": r.get("region"),
            "pyeong": r.get("pyeong"),
            "scope": r.get("scope"),
            "spaces": "·".join(r.get("spaces") or []),
            "grade": r.get("grade"),
            # 숨고 포트폴리오의 '예산'은 실제 공사 금액이다(게시 시작가가 아니다)
            "price_kind": "paid"
            if str(r.get("source", "")).startswith("soomgo") and r.get("price_kind") == "posted"
            else r.get("price_kind"),
            "vat": r.get("vat"),
            "removal": r.get("removal"),
            "price": int(r["price"]),
            **e,
            "qty_ratio": quantity(r, e),
        }
        out.append(rec)
    print(f"가정값 {rules.version} · 자료 {len(rows)}건 · 비교 {len(out)}건 · 제외 {skipped}")
    real = [x for x in out if x["price_kind"] != "posted"]
    print(summary(real, "실제 견적 · 낸 금액(게시가 제외)"))
    for trade, name in (("dobae", "도배"), ("mokgong", "목공")):
        t = [x for x in real if x["trade"] == trade]
        print(summary(t, f"  {name}"))
        print(summary([x for x in t if not x["partial"]], "    집 전체"))
        print(summary([x for x in t if x["partial"]], "    일부 공간"))
        if trade == "dobae":
            print(summary([x for x in t if x["grade"] == "silk"], "    실크"))
            print(summary([x for x in t if x["grade"] == "hapji"], "    합지"))
    print(summary([x for x in out if x["price_kind"] == "posted"], "게시가(시작가)"))
    if a.fit:
        print("보정 힌트(게시가 제외)")
        for trade, name in (("dobae", "도배"), ("mokgong", "목공")):
            t = [x for x in real if x["trade"] == trade]
            print(fit(t, f"  {name}"))
            print(fit([x for x in t if not x["partial"]], "    집 전체"))
            print(fit([x for x in t if x["partial"]], "    일부 공간"))
            if trade == "dobae":
                print(
                    fit(
                        [x for x in t if x["grade"] == "silk" and not x["partial"]],
                        "    실크 집 전체",
                    )
                )
                print(
                    fit(
                        [x for x in t if x["grade"] == "hapji" and not x["partial"]],
                        "    합지 집 전체",
                    )
                )
    q = [x["qty_ratio"] for x in out if x["qty_ratio"]]
    if q:
        print(f"수량: 보고 ÷ 엔진 중앙값 {statistics.median(q):.2f} ({len(q)}건)")
    if a.csv:
        # 도배(paper_m2)와 목공(molding_m · doors_calc) 칸이 달라 모든 행의 칸을 모은다
        fields = list(dict.fromkeys(k for x in out for k in x))
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(out)


if __name__ == "__main__":
    main()

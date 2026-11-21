"""가견적(업체 단가 × 믿집 수량) 근접도 · 원인 나누기 · 고치기안 비교 (ADR docs/v4/adr/0006). LLM · DB 없음, $0.

- 사례: price-sources `cases.csv` 본표(서울12호 밖 실크 · 합지). 원자료는 저장소 밖이고 여기엔 숫자만 나와요.
- 집: 평형(공급) · 빈 집 · 집 전체(벽 + 천장) · 방 개수 기본값. 둘 다 부가세 빼고 견줘요(ADR 0004 시장 줄과 같음).
- 가견적 단가: 업체 단가표 시장 기준값(refprice.vendor_baseline, 1201~1208 전부 '단가').
- 안은 모두 계산 엔진 판으로 셈해요(옛 판 2026.11-market에 규칙만 바꾼 판 · 새 판 2026.11b-market).
- 시장 품 계수는 dev(출처 · 벽지 · 평형대로 섞어 2:1, seed 20261121)에서 맞추고 held-out으로도 재요.

실행: cd backend && uv run python ../evaluation/v4/estimate_fit.py <cases.csv> [--s12 <posts_r.csv>] [--out <json>]
"""

import argparse
import csv
import itertools
import json
import random
import statistics as st
import sys
from dataclasses import replace
from decimal import Decimal
from math import factorial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.calc import dobae, estimate
from app.calc.common import COUNTED, pyeong_to_m2
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.refprice.book import (
    DOBAE_MARKET_2026_11,
    DOBAE_MARKET_2026_11B,
    DOBAE_REMODEL_2026_11,
    DOBAE_REMODEL_2026_11B,
)
from app.refprice.house import HOUSE_2026H2
from app.refprice.vendor_baseline import VENDOR_BASE_2026_11
from app.refprice.wallpaper_market import paper_market

D = Decimal
SEED = 20261121
HAPJI = D("0.55")
BANDS = ("~19", "20~29", "30~39", "40~")
BASE = {b.key: estimate.PriceV3("price", b.base) for b in VENDOR_BASE_2026_11.values()}
# 오늘 사용자 흐름의 시험 업체 단가
TRIAL = {
    k: estimate.PriceV3("price", v)
    for k, v in {
        "putty": 15_000,
        "paper_hapji": 4_600,
        "paper_silk": 10_500,
        "material": 6_900,
        "labor": 270_000,
        "meal": 10_000,
        "truck": 50_000,
    }.items()
}


def band(py: float) -> str:
    return "~19" if py < 20 else "20~29" if py < 30 else "30~39" if py < 40 else "40~"


def book(k: Decimal | None, hapji: bool, same: bool, base=DOBAE_MARKET_2026_11):
    """옛 판 + 규칙: k 시장 품 계수, hapji 합지 품 × 0.55, same 선택 줄도 맞춤"""
    m = {"basic": k or D(1), "economy": (k or D(1)) * (HAPJI if hapji else D(1))}
    return replace(base, md_mult=None if set(m.values()) == {D(1)} else m, same_rules=same)


_std: dict = {}


def std(p, py, g, occ=False, m2=None):
    states = p.profile and (p.profile.putty_state, p.profile.truck_state)
    mult = p.md_mult and tuple(sorted(p.md_mult.items()))
    key = (p.version, mult, p.same_rules, states, py, g, occ, m2)
    if key not in _std:
        area = m2 if m2 is not None else pyeong_to_m2(D(str(py)))
        h = dobae.HomeV3(area, "supply", g, occ)
        _std[key] = dobae.standard_v3(
            h, p, paper_market(g), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2
        )
    return _std[key]


def est(p, py, g, occ=False, prices=BASE, m2=None):
    v = std(p, py, g, occ, m2)
    keys = {ln.key for ln in v.quote.lines if ln.state in COUNTED}
    e = estimate.estimate_v3(
        prices,
        v.qty,
        grade=g,
        standard_total=v.quote.total,
        standard_keys=keys,
        optional_keys=v.optional_keys,
    )
    return v, e


def raw_md(v) -> float:
    q = v.quote
    p = DOBAE_MARKET_2026_11
    return float(q.wall_m2 * p.md_wall + q.ceiling_m2 * p.md_ceiling)


def summ(v: list[float]) -> dict | None:
    if not v:
        return None
    ape = [abs(x - 1) for x in v]
    med = st.median(v)
    return {
        "n": len(v),
        "med": round(med, 3),
        "mdape": round(100 * st.median(ape), 1),
        "hit10": round(100 * sum(a <= 0.1 + 1e-9 for a in ape) / len(v), 1),
        "hit20": round(100 * sum(a <= 0.2 + 1e-9 for a in ape) / len(v), 1),
        "cod": round(100 * (sum(abs(x - med) for x in v) / len(v)) / med, 1),
    }


def boot(v: list[float], n: int = 2000) -> dict:
    """중앙 비율 · MdAPE 부트스트랩 95% 구간"""
    rng = random.Random(SEED)
    meds, mdapes = [], []
    for _ in range(n):
        s = [rng.choice(v) for _ in v]
        meds.append(st.median(s))
        mdapes.append(100 * st.median(abs(x - 1) for x in s))
    meds.sort()
    mdapes.sort()
    lo, hi = int(0.025 * n), int(0.975 * n) - 1
    return {
        "med": (round(meds[lo], 3), round(meds[hi], 3)),
        "mdape": (round(mdapes[lo], 1), round(mdapes[hi], 1)),
    }


def read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load(path: str) -> list[dict]:
    rows = [
        r for r in read_csv(path) if r["본표에_씀"] == "예" and r["벽지종류"] in ("실크", "합지")
    ]
    out = []
    for r in rows:
        py = round(float(r["평형"]), 1)
        md = float(r["인건비_품수"]) if r["인건비_품수"].strip() else None
        g = "basic" if r["벽지종류"] == "실크" else "economy"
        out.append(
            {
                "id": r["case_id"],
                "src": r["출처묶음"],
                "py": py,
                "g": g,
                "act": float(r["합계"]),
                "md": md,
            }
        )
        out[-1]["b"] = band(py)
    rng = random.Random(SEED)
    groups: dict = {}
    for c in out:
        groups.setdefault((c["src"], c["g"], c["b"]), []).append(c)
    for key in sorted(groups):
        xs = sorted(groups[key], key=lambda c: c["id"])
        rng.shuffle(xs)
        for i, c in enumerate(xs):
            c["split"] = "held" if i % 3 == 2 else "dev"
    return out


def kfit(cases, g, split=None) -> tuple[float, int]:
    xs = [c for c in cases if c["g"] == g and c["md"] and (split is None or c["split"] == split)]
    v0 = DOBAE_MARKET_2026_11
    return round(st.median(c["md"] / raw_md(std(v0, c["py"], g)) for c in xs), 3), len(xs)


def variants(k: Decimal) -> dict:
    both_in = replace(
        DOBAE_MARKET_2026_11B,
        profile=replace(
            DOBAE_MARKET_2026_11B.profile, putty_state="included", truck_state="included"
        ),
    )
    return {
        "기준선(2026.11-market)": DOBAE_MARKET_2026_11,
        "안1 선택 줄 맞춤": book(None, False, True),
        "안2 안1 + 합지 품 0.55": book(None, True, True),
        "안3 안2 + 시장 품 계수(= 2026.11b-market)": DOBAE_MARKET_2026_11B,
        "참고 둘 다 합계 안(퍼티 · 경비 포함)": both_in,
    }


def evaluate(cases, books) -> dict:
    out = {}
    for name, p in books.items():
        res = {}
        for g in ("basic", "economy"):
            rows = []
            for c in (x for x in cases if x["g"] == g):
                v, e = est(p, c["py"], g)
                rows.append(
                    dict(
                        c,
                        r=e.supply / c["act"],
                        s=v.quote.subtotal / c["act"],
                        es=e.supply / v.quote.subtotal,
                        mdr=c["md"] / float(v.qty.man_day) if c["md"] else None,
                    )
                )
            held = [x for x in rows if x["split"] == "held"]
            res[g] = {
                "est": summ([x["r"] for x in rows]),
                "est_held": summ([x["r"] for x in held]),
                "est_ci": boot([x["r"] for x in rows]),
                "std": summ([x["s"] for x in rows]),
                "est_over_std": round(st.median(x["es"] for x in rows), 3),
                "md": summ([x["mdr"] for x in rows if x["mdr"]]),
                "band": {
                    b: {
                        "est": summ([x["r"] for x in rows if x["b"] == b]),
                        "std": summ([x["s"] for x in rows if x["b"] == b]),
                        "es": round(st.median([x["es"] for x in rows if x["b"] == b]), 3),
                    }
                    for b in BANDS
                    if any(x["b"] == b for x in rows)
                },
            }
        out[name] = res
    return out


CAUSES = ("합지 품", "선택 줄", "품 계수")  # 원인 1 · 2 · 3


def shapley(cases, k: Decimal) -> dict:
    """원인별 몫(평균 %p, Shapley): 가견적 ÷ 표준 − 1 · 가견적 ÷ 시장 − 1. 남은 것은 세 원인을 다 고친 뒤 차이"""

    def val(c, left: set, denom: float) -> float:
        p = book(k if "품 계수" not in left else None, "합지 품" not in left, "선택 줄" not in left)
        return 100 * (est(p, c["py"], c["g"])[1].supply / denom - 1)

    out = {}
    n_c = len(CAUSES)
    for g in ("basic", "economy"):
        xs = [c for c in cases if c["g"] == g]
        for tag in ("표준", "시장"):
            acc = dict.fromkeys(CAUSES, 0.0)
            gap = rest = 0.0
            for c in xs:
                d0 = (
                    std(DOBAE_MARKET_2026_11, c["py"], g).quote.subtotal
                    if tag == "표준"
                    else c["act"]
                )
                for i in CAUSES:
                    others = [x for x in CAUSES if x != i]
                    for r in range(n_c):
                        for sub in itertools.combinations(others, r):
                            w = factorial(r) * factorial(n_c - r - 1) / factorial(n_c)
                            acc[i] += w * (val(c, set(sub) | {i}, d0) - val(c, set(sub), d0))
                gap += val(c, set(CAUSES), d0)
                rest += val(c, set(), d0)
            n = len(xs)
            out[f"{g}|vs {tag}"] = dict(
                gap=round(gap / n, 1),
                **{x: round(acc[x] / n, 1) for x in CAUSES},
                남음=round(rest / n, 1),
            )
        # 남은 것(표준 대비)을 줄 묶음으로
        parts = dict.fromkeys(
            ("시공(품 × 일당 · 0.5 올림)", "식대 줄", "부자재 단가", "벽지 단가"), 0.0
        )
        p3 = book(k, True, True)
        for c in xs:
            v = std(DOBAE_MARKET_2026_11, c["py"], g)
            s0 = v.quote.subtotal
            L = {ln.key: ln.amount or 0 for ln in v.quote.lines if ln.state in COUNTED}
            a = {x.row.key: x.amount for x in est(p3, c["py"], g)[1].lines}
            pk = "paper_silk" if g == "basic" else "paper_hapji"
            parts["시공(품 × 일당 · 0.5 올림)"] += (
                100 * (a["labor"] - L["wall"] - L["ceiling"]) / s0
            )
            parts["식대 줄"] += 100 * a["meal"] / s0
            parts["부자재 단가"] += 100 * (a["material"] - L["material"]) / s0
            parts["벽지 단가"] += 100 * (a[pk] - L["paper"]) / s0
        out[f"{g}|남음(표준 대비) 줄 묶음"] = {x: round(y / len(xs), 1) for x, y in parts.items()}
    return out


def grid(books) -> dict:
    """같은 집 가견적 ÷ 표준 · 품 · 기간 (시장 기준값 단가)"""
    out = {}
    for g in ("basic", "economy"):
        for occ in (False, True):
            for py in (16, 24, 32, 34, 45):
                row = {}
                for name, p in books.items():
                    v, e = est(p, py, g, occ)
                    row[name] = {
                        "es": round(e.supply / v.quote.subtotal, 3),
                        "md": str(v.quote.man_days),
                        "days": str(v.quote.days),
                    }
                out[f"{g}|{'살면서' if occ else '빈 집'}|{py}평"] = row
    return out


def flows(books) -> dict:
    """오늘 사용자 흐름: F1 실크 · 공급 105.8㎡ · 살면서, F3 합지 · 공급 79.3㎡ · 빈 집 (시험 업체 단가)"""
    out = {}
    for f, m2, g, occ in (("F1", "105.8", "basic", True), ("F3", "79.3", "economy", False)):
        for name in ("기준선(2026.11-market)", "안3 안2 + 시장 품 계수(= 2026.11b-market)"):
            v, e = est(books[name], None, g, occ, TRIAL, D(m2))
            out[f"{f}|{name}"] = {
                "std_total": v.quote.total,
                "days": str(v.quote.days),
                "man_day": str(v.quote.man_days),
                "est_total": e.total,
                "est_over_std": round(e.total / v.quote.total, 3),
                "optional": {x.row.key: x.amount for x in e.lines if x.optional},
            }
    return out


def s12(path: str) -> dict:
    """서울12호(리모델링 기준): 표준 앞 판 vs 새 판, 그 업체 단가 × 믿집 수량(가견적 꼴) vs 실견적"""
    rows = read_csv(path)
    out = {}
    for name, p in (
        ("2026.11-remodel", DOBAE_REMODEL_2026_11),
        ("2026.11b-remodel", DOBAE_REMODEL_2026_11B),
    ):
        rs, re_ = [], []
        for r in rows:
            g = "economy" if r["벽지_종류"] == "합지" else "basic"
            py = round(float(r["평형"]), 1)
            v = std(p, py, g)
            act = float(r["실제_도배소계"])
            rs.append(v.quote.subtotal / act)
            md = float(r["실제_품"] or 0)
            unit = {
                "paper": float(r["실제_벽지평당단가"] or 0),
                "labor": float(r["실제_일당"] or 0),
                "material": float(r["실제_부자재"] or 0) / py,
                "putty": float(r["실제_퍼티"] or 0) / py,
                "meal": float(r["실제_식대"] or 0) / md if md else 0.0,
                "truck": float(r["실제_운송비"] or 0),
            }
            q = v.qty
            e = (
                unit["paper"] * float(q.paper_py)
                + (unit["labor"] + unit["meal"]) * float(q.man_day)
                + (unit["material"] + unit["putty"]) * float(q.floor_py)
                + unit["truck"]
            )
            if md:
                re_.append(e / act)
        out[name] = {"std": summ(rs), "est_own_prices": summ(re_)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--s12")
    ap.add_argument("--out")
    a = ap.parse_args()
    cases = load(a.cases)
    fit = {
        g: {s or "all": kfit(cases, g, s) for s in ("dev", "held", None)}
        for g in ("basic", "economy")
    }
    k = D(str(round(fit["basic"]["dev"][0], 2)))
    assert DOBAE_MARKET_2026_11B.md_mult == {"basic": k, "economy": k * HAPJI}, (
        "새 판 품 배수 = dev 계수"
    )
    books = variants(k)
    res = {
        "k_fit": fit,
        "k": str(k),
        "split": {s: sum(1 for c in cases if c["split"] == s) for s in ("dev", "held")},
        "metrics": evaluate(cases, books),
        "decomp": shapley(cases, k),
        "grid": grid(books),
        "flows": flows(books),
    }
    if a.s12:
        res["s12"] = s12(a.s12)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    for name, m in res["metrics"].items():
        for g in ("basic", "economy"):
            print(
                name, g, m[g]["est"], "held", m[g]["est_held"]["med"], "÷표준", m[g]["est_over_std"]
            )
    print(
        json.dumps(
            {"k_fit": fit, "decomp": res["decomp"], "flows": res["flows"]}, ensure_ascii=False
        )
    )
    if a.s12:
        print(json.dumps(res["s12"], ensure_ascii=False))


if __name__ == "__main__":
    main()

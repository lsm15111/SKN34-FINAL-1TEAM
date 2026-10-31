"""공정 의견 평가 사례를 공정 스펙으로 만든다 (공정 하나에 약 5,000개). 시드를 고정한다.

- 범주 = 조건 없는 칸(when 없음)의 값 조합. choice는 값마다, multi는 고를 수 있는 조합마다, count는 구간마다,
  '모르겠어요'(unknown)가 있는 칸은 unknown도 값 하나로 친다. 조합이 60개를 넘으면 첫 칸만 범주로 쓴다
- 범주 안 격자 (조합마다 고르게): 거주 × 같이 하는 공정(없음 · 하나 · 여럿) × 면적 기준(공급 · 전용 · 모름)
  × 조건 있는 칸(when이 켜질 때만 묻는 칸)과 범주에 못 넣은 칸. 면적 크기 · 발코니 · 준공 연도 · 공간 이름 수 ·
  같이 할 공정은 값마다 고르게 채운다
- 같이 하는 공정 칸은 무작위로 채우고, 같이 쓰는 칸(share)은 비워 둬 상담 normalize가 같은 값을 넣게 한다
- '모르겠어요'는 스펙의 unknown 값을 넣고 to_check에 남긴다 (상담과 같게)
- 나눔은 격자 조합마다 dev, dev, held-out (2:1). 공간 이름은 조각 3개 중 1개를 held-out 전용으로 둔다
- 같은 입력은 넣지 않는다. 입력 글 꼴(수를 뺀 plan_text)이 같고 면적 차이가 1평 안이면 근사 중복으로 거른다
- 기대(단계 키 · 실측 후 줄 · 꼭 언급 · 언급하면 안 됨)는 계산 엔진 + 스펙 + 공정 설정(config.py)으로 붙인다

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/plan/make_cases.py --trade dobae
→ evaluation/plan/<공정>/cases_5k.jsonl (커밋 안 함) · sample_100.jsonl (커밋)
"""

import argparse
import itertools
import json
import math
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.consult.trades.base import FieldSpec, TradeSpec
from evaluation.common import gen, house, trades
from evaluation.plan import config
from evaluation.scorers.expect import expect

TOTAL = 5000
MAX_CATEGORIES = 60
NEAR_M2 = Decimal("3.3")  # 입력 글 꼴이 같을 때 이보다 면적 차이가 작으면 근사 중복 (1평)


def out_dir(trade: str) -> Path:
    return HERE / trade


def buckets(f: FieldSpec, cfg: config.PlanConfig) -> dict[str, tuple[int, int]]:
    """숫자 칸 구간: 설정이 없으면 범위를 셋으로 나눈다"""
    if f.key in cfg.count_buckets:
        return cfg.count_buckets[f.key]
    lo, hi = f.min, f.max
    if hi - lo < 3:
        return {str(v): (v, v) for v in range(lo, hi + 1)}
    a, b = lo + (hi - lo + 1) // 3, lo + 2 * (hi - lo + 1) // 3
    return {"low": (lo, a - 1), "mid": (a, b - 1), "high": (b, hi)}


def field_opts(f: FieldSpec, cfg: config.PlanConfig) -> list[str]:
    """범주 · 격자에 쓰는 칸 값 이름 (multi는 '+'로 잇고, 숫자 칸은 구간 이름)"""
    if f.kind == "choice":
        opts = list(f.values)
    elif f.kind == "multi":
        opts = ["+".join(s) for s in trades.subsets(f)]
    else:
        opts = list(buckets(f, cfg))
    return opts + (["unknown"] if f.unknown is not None else [])


def value_of(r, f: FieldSpec, opt: str, cfg: config.PlanConfig):
    """칸 값 이름 → (카드 값, 모르겠어요였는지)"""
    if opt == "unknown":
        return f.unknown, True
    if f.kind == "choice":
        return opt, False
    if f.kind == "multi":
        return opt.split("+"), False
    lo, hi = buckets(f, cfg)[opt]
    return r.randint(lo, hi), False


def layout(sp: TradeSpec, cfg: config.PlanConfig) -> tuple[list[FieldSpec], list[FieldSpec]]:
    """(범주 칸, 격자 칸)"""
    uncond = [f for f in sp.fields if f.when is None]
    cat = uncond
    if math.prod(len(field_opts(f, cfg)) for f in uncond) > MAX_CATEGORIES:
        cat = uncond[:1]
    return cat, [f for f in sp.fields if f not in cat]


def other_opts(trade: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(같이 하는 공정 격자 값, 같이 할 공정 후보)"""
    others = tuple(k for k in trades.registered() if k != trade)
    opts = ("none",) + (("one",) if others else ()) + (("many",) if len(others) > 1 else ())
    return opts, others or ("-",)


def strata_key(f: FieldSpec) -> str:
    fixed = {"occupied", "other", "with", "basis", "size", "balcony", "year", "spaces", "unknown"}
    return f.key if f.key not in fixed else f"f_{f.key}"


def make_card(r, sp: TradeSpec, cfg, cat: dict[str, str], row: dict, used: list[str]) -> dict:
    """한 줄 설계 → 상담 카드 JSON + 고객이 말한 면적"""
    a = house.area(r, row["basis"], row["size"])
    vals: dict = {}
    to_check = ["area_basis"] if row["basis"] == "unknown" else []
    for f in sp.fields:
        if not f.asks(vals):
            continue
        opt = cat.get(f.key) or row.get(strata_key(f))
        if opt in (None, "-"):  # 조건이 다른 칸에 기대어 격자에 없던 칸
            opt = r.choice(field_opts(f, cfg))
        v, unknown = value_of(r, f, opt, cfg)
        vals[f.key] = f.norm(v)
        if unknown:
            to_check.append(f"{sp.key}.{f.key}")
    others = []
    if row["other"] == "one":
        others = [row["with"]]
    elif row["other"] == "many":
        pool = [k for k in trades.registered() if k not in (sp.key, row["with"])]
        others = [row["with"]] + r.sample(pool, min(len(pool), r.choice((1, 2))))
    shares = {f.share for f in sp.asked(vals) if f.share}
    values = {sp.key: vals} | {
        k: trades.random_values(r, trades.spec(k), skip_shares=shares) for k in others
    }
    names = house.space_names(r, row["spaces"], row["split"], used)
    card = {
        "trades": [k for k in trades.registered() if k == sp.key or k in others],
        "area_m2": a["area_m2"],
        "area_basis": a["area_basis"],
        "occupied": row["occupied"] == "yes",
        "balcony_ext": row["balcony"] == "yes",
        "built_year": house.built_year(r, row["year"]),
        "values": values,
        "spaces": {sp.key: names} if names else {},
        "to_check": to_check,
    }
    c = trades.card({"card": card})  # 스펙 검사 + 상담과 같게 맞춤 (같이 쓰는 칸 채우기)
    return {"card": c.model_dump(mode="json"), "area_said": a["area_said"]}


class Near:
    """같은 입력 · 근사 중복(입력 글 꼴이 같고 면적 차이 1평 안) 거르기"""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.areas: dict[str, list[Decimal]] = {}
        self.exact = self.near = 0

    def add(self, trade: str, inp: dict) -> bool:
        key = json.dumps(inp["card"], sort_keys=True, ensure_ascii=False)
        if key in self.seen:
            self.exact += 1
            return False
        shape = gen.norm(trades.plan_text(trade, inp))
        area = Decimal(inp["card"]["area_m2"])
        got = self.areas.setdefault(shape, [])
        if any(abs(area - x) < NEAR_M2 for x in got):
            self.near += 1
            return False
        self.seen.add(key)
        got.append(area)
        return True


def build(trade: str, total: int = TOTAL) -> tuple[list[dict], dict]:
    """(사례, 생성 통계)"""
    sp, cfg = trades.spec(trade), config.get(trade)
    r = gen.rng(cfg.salt or trade)
    cat_fields, grid_fields = layout(sp, cfg)
    cats = list(itertools.product(*(field_opts(f, cfg) for f in cat_fields)))
    per = max(3, total // len(cats) // 3 * 3)
    opts, others = other_opts(trade)
    near = Near()
    cases: list[dict] = []
    for combo in cats:
        cat = dict(zip([f.key for f in cat_fields], combo, strict=True))
        probe = {}
        for f in cat_fields:
            probe[f.key] = f.norm(value_of(r, f, cat[f.key], cfg)[0])
        asked = [f for f in grid_fields if f.when is None or f.asks(probe)]
        core = {"occupied": ("yes", "no"), "other": opts, "basis": house.BASIS}
        core |= {strata_key(f): tuple(field_opts(f, cfg)) for f in asked}
        extra = {
            "size": house.SIZES,
            "balcony": ("yes", "no"),
            "year": house.YEARS,
            "spaces": house.SPACE_PATTERNS,
            "with": others,
        }
        rows = gen.balanced_rows(r, per, core, extra)
        gen.assign_splits(rows, group=lambda x, core=core: tuple(x[k] for k in core))
        for row in rows:
            for _ in range(100):
                used: list[str] = []
                inp = make_card(r, sp, cfg, cat, row, used)
                if near.add(trade, inp):
                    break
            else:
                raise SystemExit("같은 입력만 나와요. 면적 · 준공 연도 범위를 넓혀 주세요.")
            c = trades.card(inp)
            facts = trades.facts(sp.build(trades.common(c), c.values[trade]))
            unknown = [x.split(".")[-1] for x in inp["card"]["to_check"]]
            strata = {strata_key(f): "-" for f in grid_fields} | {
                k: v for k, v in row.items() if k != "split"
            }
            if row["other"] == "none":
                strata["with"] = "-"
            cases.append(
                {
                    "split": row["split"],
                    "category": "-".join(combo),
                    "strata": strata | {"unknown": "+".join(unknown) or "none"},
                    "input": inp,
                    "expect": expect(trade, c, facts),
                    "tpl": used,
                }
            )
    stats = {"exact": near.exact, "near": near.near, "shapes": len(near.areas)}
    return gen.number_cases(cases, cfg.prefix or trade, trade=trade), stats


def sample(cases: list[dict], n: int = 100) -> list[dict]:
    return gen.sample_2to1(cases, n, key=lambda c: c["category"])


def report(trade: str, cases: list[dict], smp: list[dict], stats: dict) -> str:
    sp, cfg = trades.spec(trade), config.get(trade)
    cat_fields, _ = layout(sp, cfg)
    keys = [f"strata.{k}" for k in cases[0]["strata"]]
    seen, total = gen.pair_coverage(cases, ["category", *keys])
    tpl = {s: {x for c in cases if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS}
    steps = Counter(" ".join(c["expect"]["step_keys"]) for c in cases)
    rules = Counter(x for c in cases for x in c["expect"]["must"] + c["expect"]["must_not"])
    title = "범주 (" + "-".join(f.label for f in cat_fields) + ")"
    frags = (
        f"공간 이름 조각: dev {len(tpl['dev'])}개 · held-out {len(tpl['heldout'])}개, "
        f"두 나눔이 같이 쓴 조각 {len(tpl['dev'] & tpl['heldout'])}개"
    )
    dups = (
        f"거른 입력: 같은 입력 {stats['exact']}번 · 근사 중복 {stats['near']}번 "
        f"(입력 글 꼴 {stats['shapes']}가지)"
    )
    parts = [
        gen.count_table(cases, "category", title),
        *(gen.count_table(cases, k) for k in keys),
        f"두 칸씩 짝지은 값 조합: {seen}/{total}개 나옴 (조건이 꺼져 '-'인 칸과의 짝은 나올 수 없다)",
        frags,
        dups,
        "단계 키: " + ", ".join(f"{k} {v}" for k, v in sorted(steps.items())),
        "기대 규칙: " + ", ".join(f"{k} {v}" for k, v in sorted(rules.items())),
        "표본 100: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(c["split"] for c in smp).items())),
    ]
    return "\n\n".join(parts)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="공정 스펙으로 공정 의견 평가 사례를 만든다")
    ap.add_argument(
        "--trade", action="append", help="공정 키 (여러 번 줄 수 있음, 없으면 등록된 공정 전부)"
    )
    ap.add_argument(
        "--n", type=int, default=TOTAL, help="공정 하나의 사례 수 (범주마다 3의 배수로 맞춘다)"
    )
    args = ap.parse_args()
    for trade in args.trade or trades.registered():
        cases, stats = build(trade, args.n)
        smp = sample(cases)
        d = out_dir(trade)
        d.mkdir(parents=True, exist_ok=True)
        gen.write_jsonl(d / "cases_5k.jsonl", cases)
        gen.write_jsonl(d / "sample_100.jsonl", smp)
        assert gen.read_jsonl(d / "cases_5k.jsonl") == cases, "다시 읽은 사례가 달라요"
        print(f"## {trades.label(trade)} ({trade}): {len(cases)}개 → {d.relative_to(ROOT)}\n")
        print(report(trade, cases, smp, stats))
        print()


if __name__ == "__main__":
    main()

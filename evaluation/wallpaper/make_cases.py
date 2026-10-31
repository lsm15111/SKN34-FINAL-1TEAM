"""도배 공정 의견 평가 사례 4,995개를 만든다. 표준 라이브러리 + 계산 엔진(순수 함수)만 쓰고 시드를 고정한다.

- 범주 = 등급(저가형 · 기본형 · 모름) × 천장(포함 · 안 함 · 모름) 9개, 범주마다 555개 (dev 370 · held-out 185)
- 범주 안에서 거주 × 같이 하는 공정(목공) × 면적 기준(공급 · 전용 · 모름)은 모든 조합을 고르게 돌려 쓰고,
  면적 크기 · 발코니 확장 · 준공 연도는 값마다 고르게 채운다. '모름'은 상담 기본값으로 계산하고 to_check에 남긴다
- 나눔은 칸 조합마다 dev, dev, held-out 차례로 붙인다
- 사례마다 계산 엔진으로 단계 키 · '실측 후' 줄을 뽑아 기대 검사(꼭 언급 · 언급하면 안 됨)를 붙인다
- 같은 입력은 두 번 넣지 않는다. 입력이 칸 값의 조합이라 글자 3-gram 거르기는 쓰지 않는다 (README)

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/wallpaper/make_cases.py
→ evaluation/wallpaper/cases_5k.jsonl (커밋 안 함) · sample_100.jsonl (커밋)
"""

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, house, trades
from evaluation.scorers.expect import expect

AGENT = "wallpaper"
PER_CATEGORY = 555  # 3의 배수라 범주마다 dev:held-out이 정확히 2:1
GRADES = ("economy", "basic", "unknown")
CEILINGS = ("yes", "no", "unknown")
CORE = {"occupied": ("yes", "no"), "other": ("none", "mokgong"), "basis": house.BASIS}
EXTRA = {"size": house.SIZES, "balcony": ("yes", "no"), "year": house.YEARS}
FULL = HERE / "cases_5k.jsonl"
SAMPLE = HERE / "sample_100.jsonl"


def category(grade: str, ceiling: str) -> str:
    g = {"economy": "economy", "basic": "basic", "unknown": "gradeunk"}[grade]
    c = {"yes": "ceil", "no": "wall", "unknown": "ceilunk"}[ceiling]
    return f"{g}-{c}"


def make_input(r, row: dict) -> dict:
    a = house.area(r, row["basis"], row["size"])
    to_check = [
        f
        for f, unknown in (
            ("area_basis", row["basis"] == "unknown"),
            ("grade", row["grade"] == "unknown"),
            ("include_ceiling", row["ceiling"] == "unknown"),
        )
        if unknown
    ]
    return {
        "common": {
            "area_m2": a["area_m2"],
            "area_basis": a["area_basis"],
            "area_said": a["area_said"],
            "occupied": row["occupied"] == "yes",
            "balcony_ext": row["balcony"] == "yes",
            "built_year": house.built_year(r, row["year"]),
        },
        "trades": {
            "dobae": {
                "grade": trades.DEFAULTS["grade"] if row["grade"] == "unknown" else row["grade"],
                "include_ceiling": row["ceiling"] != "no",  # 모름이면 기본값(포함)
            }
        },
        "other_trades": ["mokgong"] if row["other"] == "mokgong" else [],
        "to_check": to_check,
    }


def build() -> list[dict]:
    r = gen.rng(AGENT)
    cases: list[dict] = []
    seen: set[str] = set()
    for grade in GRADES:
        for ceiling in CEILINGS:
            rows = gen.balanced_rows(r, PER_CATEGORY, CORE, EXTRA)
            gen.assign_splits(rows, group=lambda x: (x["occupied"], x["other"], x["basis"]))
            for row in rows:
                row |= {"grade": grade, "ceiling": ceiling}
                for _ in range(100):
                    inp = make_input(r, row)
                    key = json.dumps(inp, sort_keys=True, ensure_ascii=False)
                    if key not in seen:
                        break
                else:
                    raise SystemExit("같은 입력만 나와요. 면적 값 범위를 넓혀 주세요.")
                seen.add(key)
                split = row.pop("split")
                facts = trades.facts(trades.quote(AGENT, inp))
                unknown = "+".join(inp["to_check"]) or "none"
                cases.append(
                    {
                        "split": split,
                        "category": category(grade, ceiling),
                        "strata": row | {"unknown": unknown},
                        "input": inp,
                        "expect": expect(AGENT, inp, facts),
                    }
                )
    return gen.number_cases(cases, "wp", AGENT)


def sample(cases: list[dict], n: int = 100) -> list[dict]:
    return gen.sample_2to1(cases, n, key=lambda c: c["category"])


def report(cases: list[dict], smp: list[dict]) -> str:
    keys = ("strata.occupied", "strata.other", "strata.basis", "strata.unknown", "strata.size")
    keys += ("strata.balcony", "strata.year")
    dims = ("category",) + keys[:3] + keys[4:]
    seen, total = gen.pair_coverage(cases, dims)
    steps = Counter(" ".join(c["expect"]["step_keys"]) for c in cases)
    rules = Counter(r for c in cases for r in c["expect"]["must"] + c["expect"]["must_not"])
    shapes = {gen.norm(trades.card_text(AGENT, c["input"])) for c in cases}
    keys_in = {json.dumps(c["input"], sort_keys=True) for c in cases}
    parts = [
        gen.count_table(cases, "category", "범주 (등급-천장)"),
        *(gen.count_table(cases, k) for k in keys),
        f"두 칸씩 짝지은 값 조합: {seen}/{total}개 나옴",
        f"같은 입력: {len(cases) - len(keys_in)}개 · 숫자를 뺀 입력 글 가짓수: {len(shapes)}개",
        "단계 키: " + ", ".join(f"{k} {v}" for k, v in sorted(steps.items())),
        "기대 규칙: " + ", ".join(f"{k} {v}" for k, v in sorted(rules.items())),
        "표본 100: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(c["split"] for c in smp).items())),
    ]
    return "\n\n".join(parts)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서도 한글이 깨지지 않게
    cases = build()
    smp = sample(cases)
    gen.write_jsonl(FULL, cases)
    gen.write_jsonl(SAMPLE, smp)
    back = gen.read_jsonl(FULL)
    assert back == cases, "다시 읽은 사례가 달라요"
    print(
        f"저장: {FULL.relative_to(ROOT)} ({len(back)}개) · {SAMPLE.relative_to(ROOT)} ({len(smp)}개)"
    )
    print()
    print(report(cases, smp))


if __name__ == "__main__":
    main()

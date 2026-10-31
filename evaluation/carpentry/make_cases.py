"""목공 공정 의견 평가 사례 4,995개를 만든다. 표준 라이브러리 + 계산 엔진(순수 함수)만 쓰고 시드를 고정한다.

- 범주 = 목공 항목 조합(천장 몰딩 · 걸레받이 · 방문 · 천장 평탄화 중 하나 이상) 15개, 범주마다 333개
  (dev 222 · held-out 111)
- 범주 안에서 거주 × 같이 하는 공정(도배) × 면적 기준(공급 · 전용 · 모름)은 모든 조합을 고르게 돌려 쓰고,
  방문이 있는 범주는 문틀 교체(예 · 아니요 · 모름) × 방문 개수(1~2 · 3~4 · 5~6 · 모름)까지 조합에 넣는다.
  면적 크기 · 발코니 확장 · 준공 연도 · 공간 이름 수(없음 · 1 · 2~3 · 4~6)는 값마다 고르게 채운다
- 공간 이름은 문장 조각처럼 3개 중 1개를 held-out 전용으로 두어 두 나눔이 같은 이름을 쓰지 않는다.
  15%는 띄어쓰기 잡음을 넣는다 (프로젝트에 고객이 적은 이름이라)
- 나눔은 칸 조합마다 dev, dev, held-out 차례로 붙인다
- 사례마다 계산 엔진으로 단계 키 · '실측 후' 줄을 뽑아 기대 검사(꼭 언급 · 언급하면 안 됨)를 붙인다
- 같은 입력은 두 번 넣지 않는다

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/carpentry/make_cases.py
→ evaluation/carpentry/cases_5k.jsonl (커밋 안 함) · sample_100.jsonl (커밋)
"""

import itertools
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, house, trades
from evaluation.scorers.expect import expect

AGENT = "carpentry"
PER_CATEGORY = 333  # 3의 배수라 범주마다 dev:held-out이 정확히 2:1
ITEM_SETS = [c for k in range(1, 5) for c in itertools.combinations(trades.ITEMS, k)]
CORE = {"occupied": ("yes", "no"), "other": ("none", "dobae"), "basis": house.BASIS}
DOOR_CORE = {"door_frame": ("yes", "no", "unknown"), "doors": ("few", "mid", "many", "unknown")}
EXTRA = {
    "size": house.SIZES,
    "balcony": ("yes", "no"),
    "year": house.YEARS,
    "spaces": ("none", "one", "few", "all"),
}
# 공간 이름 (번호 % 3 == 2는 held-out 전용). 욕실 · 화장실은 범위 밖 공사 키워드와 겹쳐 넣지 않는다
SPACES = gen.Fragments(
    {
        "space": [
            "거실", "안방", "작은방", "주방", "현관", "드레스룸", "아이방", "서재", "옷방",
            "큰방", "침실", "작은방1", "작은방2", "알파룸", "공부방", "부부 침실", "막내방", "손님방",
            "거실 겸 주방", "팬트리", "현관 복도", "아기방", "드레스 룸", "작업실", "게스트룸", "중간방",
            "끝방", "건넌방", "복도", "애기방",
        ]
    }
)  # fmt: skip
FULL = HERE / "cases_5k.jsonl"
SAMPLE = HERE / "sample_100.jsonl"


def space_names(r, pattern: str, split: str, used: list[str]) -> list[str]:
    if pattern == "none":
        return []
    k = {"one": 1, "few": r.choice((2, 3)), "all": r.randint(4, 6)}[pattern]
    names = SPACES.sample(r, "space", split, k, used)
    if r.random() < 0.15:
        i = r.randrange(len(names))
        names[i], _ = gen.noisy(names[i], r, k=1, ops=("nospace", "add_space"))
    return names


def door_count(r, bucket: str) -> int:
    if bucket == "unknown":
        return trades.DEFAULTS["doors"]
    lo = {"few": 1, "mid": 3, "many": 5}[bucket]
    return r.choice((lo, lo + 1))


def make_input(r, row: dict, items: tuple[str, ...], used: list[str]) -> dict:
    a = house.area(r, row["basis"], row["size"])
    door = "door" in items
    to_check = [
        f
        for f, unknown in (
            ("area_basis", row["basis"] == "unknown"),
            ("doors", door and row["doors"] == "unknown"),
            ("door_frame", door and row["door_frame"] == "unknown"),
        )
        if unknown
    ]
    t = {
        "items": list(items),
        "spaces": space_names(r, row["spaces"], row["split"], used),
        "doors": door_count(r, row["doors"]) if door else None,
        "door_frame": row["door_frame"] != "no" if door else None,  # 모름이면 기본값(문틀까지)
    }
    return {
        "common": {
            "area_m2": a["area_m2"],
            "area_basis": a["area_basis"],
            "area_said": a["area_said"],
            "occupied": row["occupied"] == "yes",
            "balcony_ext": row["balcony"] == "yes",
            "built_year": house.built_year(r, row["year"]),
        },
        "trades": {"mokgong": t},
        "other_trades": ["dobae"] if row["other"] == "dobae" else [],
        "to_check": to_check,
    }


def build() -> list[dict]:
    r = gen.rng(AGENT)
    cases: list[dict] = []
    seen: set[str] = set()
    for items in ITEM_SETS:
        core = CORE | (DOOR_CORE if "door" in items else {})
        rows = gen.balanced_rows(r, PER_CATEGORY, core, EXTRA)
        gen.assign_splits(rows, group=lambda x, core=core: tuple(x[k] for k in core))
        for row in rows:
            for _ in range(100):
                used: list[str] = []
                inp = make_input(r, row, items, used)
                key = json.dumps(inp, sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    break
            else:
                raise SystemExit("같은 입력만 나와요. 면적 값 범위를 넓혀 주세요.")
            seen.add(key)
            split = row.pop("split")
            facts = trades.facts(trades.quote(AGENT, inp))
            strata = {"door_frame": "-", "doors": "-"} | row
            cases.append(
                {
                    "split": split,
                    "category": "+".join(items),
                    "strata": strata | {"unknown": "+".join(inp["to_check"]) or "none"},
                    "input": inp,
                    "expect": expect(AGENT, inp, facts),
                    "tpl": used,
                }
            )
    return gen.number_cases(cases, "cp", AGENT)


def sample(cases: list[dict], n: int = 100) -> list[dict]:
    return gen.sample_2to1(cases, n, key=lambda c: c["category"])


def report(cases: list[dict], smp: list[dict]) -> str:
    keys = ("strata.occupied", "strata.other", "strata.basis", "strata.unknown")
    keys += ("strata.door_frame", "strata.doors", "strata.spaces", "strata.size")
    keys += ("strata.balcony", "strata.year")
    always = ("category", "strata.occupied", "strata.other", "strata.basis", "strata.size")
    always += ("strata.balcony", "strata.year", "strata.spaces")
    seen, total = gen.pair_coverage(cases, always)
    doors = [c for c in cases if c["strata"]["doors"] != "-"]
    dseen, dtotal = gen.pair_coverage(doors, ("category", "strata.door_frame", "strata.doors"))
    tpl = {s: {x for c in cases if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS}
    steps = Counter(" ".join(c["expect"]["step_keys"]) for c in cases)
    rules = Counter(r for c in cases for r in c["expect"]["must"] + c["expect"]["must_not"])
    shapes = {gen.norm(trades.card_text(AGENT, c["input"])) for c in cases}
    keys_in = {json.dumps(c["input"], sort_keys=True) for c in cases}
    frags = (
        f"공간 이름 조각: dev {len(tpl['dev'])}개 · held-out {len(tpl['heldout'])}개 사용, "
        f"두 나눔이 같이 쓴 조각 {len(tpl['dev'] & tpl['heldout'])}개"
    )
    parts = [
        gen.count_table(cases, "category", "범주 (목공 항목)"),
        *(gen.count_table(cases, k) for k in keys),
        f"두 칸씩 짝지은 값 조합: {seen}/{total}개 나옴 · 방문 범주의 문틀 × 개수 짝: {dseen}/{dtotal}개",
        frags,
        f"같은 입력: {len(cases) - len(keys_in)}개 · 숫자를 뺀 입력 글 가짓수: {len(shapes)}개",
        "단계 키: " + ", ".join(f"{k} {v}" for k, v in sorted(steps.items())),
        "기대 규칙: " + ", ".join(f"{k} {v}" for k, v in sorted(rules.items())),
        "표본 100: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(c["split"] for c in smp).items())),
    ]
    return "\n\n".join(parts)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
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

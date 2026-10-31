"""평가 사례 생성기가 같이 쓰는 도구. 표준 라이브러리만 쓰고, 같은 시드면 늘 같은 결과를 낸다.

- rng: 시드 + 이름으로 따로 쓰는 난수
- product · balanced_rows: 조합 격자와 고른 배치
- assign_splits: dev:held-out 2:1 나누기 (묶음 안에서도 2:1)
- allocate · stratified_sample: 층마다 고르게 뽑기
- Fragments: 문장 조각 dev/held-out 분리 (묶음마다 번호 % 3 == 2인 조각은 held-out 전용)
- grams · jaccard · NearDup: 글자 3-gram 근사 중복 거르기
- noisy: 오타 · 띄어쓰기 · 구어체 잡음
- read_jsonl · write_jsonl · get · count_table · pair_coverage
"""

import itertools
import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from pathlib import Path

SEED = 20261031
SPLITS = ("dev", "heldout")


def rng(*salt: object, seed: int = SEED) -> random.Random:
    """시드와 이름(에이전트 · 단계)으로 만든 난수. 문자열 시드라 실행마다 같다."""
    return random.Random(":".join(map(str, (seed, *salt))))


# ---------------------------------------------------------------- 조합 · 배치
def product(dims: dict[str, Sequence]) -> list[dict]:
    """칸 이름 → 값 목록에서 모든 조합을 만든다."""
    keys = list(dims)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*dims.values())]


def balanced_rows(
    r: random.Random,
    n: int,
    core: dict[str, Sequence],
    extra: dict[str, Sequence] | None = None,
) -> list[dict]:
    """n줄을 만든다.

    core 칸은 모든 조합을 섞어 차례로 돌려 쓴다 (조합마다 개수 차이가 1 이하).
    extra 칸은 칸마다 값을 고르게 채운 뒤 따로 섞는다 (값마다 개수 차이가 1 이하).
    """
    grid = product(core) if core else [{}]
    r.shuffle(grid)
    rows = [dict(grid[i % len(grid)]) for i in range(n)]
    for key, vals in (extra or {}).items():
        col = [vals[i % len(vals)] for i in range(n)]
        r.shuffle(col)
        for row, v in zip(rows, col, strict=True):
            row[key] = v
    return rows


def assign_splits(
    items: list[dict],
    group: Callable[[dict], Hashable] | None = None,
    key: str = "split",
) -> None:
    """dev, dev, held-out 순서로 나눔을 붙인다 (2:1).

    group을 주면 같은 묶음끼리 모아 차례로 센다. 셈을 묶음 사이에 이어 가므로 전체도 2:1이고,
    묶음 안도 2:1에 가깝다 (차이 1 이하). 묶음 순서는 이름 순이라 늘 같다.
    """
    groups: dict[Hashable, list[dict]] = defaultdict(list)
    for it in items:
        groups[group(it) if group else 0].append(it)
    i = 0
    for g in sorted(groups, key=repr):
        for it in groups[g]:
            it[key] = "heldout" if i % 3 == 2 else "dev"
            i += 1


# ---------------------------------------------------------------- 층화 표본
def allocate(
    n: int, sizes: dict[Hashable, int], order: Sequence[Hashable] | None = None
) -> dict[Hashable, int]:
    """n자리를 층마다 고르게 나눈다.

    층이 작으면 있는 만큼만 주고 남는 자리는 다른 층에 돌린다. 나머지는 order 순(없으면 이름 순)으로 준다.
    """
    quota = {k: 0 for k in sizes}
    left = min(n, sum(sizes.values()))
    keys = list(order) if order is not None else sorted(sizes, key=repr)
    open_ = [k for k in keys if sizes[k] > 0]
    while left > 0 and open_:
        share = max(left // len(open_), 1)
        for k in list(open_):
            if left == 0:
                break
            add = min(share, sizes[k] - quota[k], left)
            quota[k] += add
            left -= add
            if quota[k] >= sizes[k]:
                open_.remove(k)
    return quota


def stratified_sample(
    items: list[dict],
    n: int,
    key: Callable[[dict], Hashable],
    r: random.Random | None = None,
) -> list[dict]:
    """key 값(층)마다 고르게 n개를 뽑는다.

    r이 없으면 층마다 앞에서부터, 있으면 무작위로 고른다. 돌려줄 때는 원래 순서를 지킨다.
    """
    if n <= 0 or n >= len(items):
        return list(items)
    groups: dict[Hashable, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        groups[key(it)].append(i)
    order = sorted(groups, key=repr)
    if r is not None:
        r.shuffle(order)
    quota = allocate(n, {k: len(groups[k]) for k in order}, order)
    pick: list[int] = []
    for k in order:
        idx = groups[k]
        pick += r.sample(idx, quota[k]) if r is not None else idx[: quota[k]]
    return [items[i] for i in sorted(pick)]


def sample_2to1(
    items: list[dict], n: int, key: Callable[[dict], Hashable], r: random.Random | None = None
) -> list[dict]:
    """나눔마다 dev:held-out 2:1 자리를 나누고, 그 안에서 층마다 고르게 뽑는다.

    r이 없으면 앞에서부터 골라 늘 같다 (표본 파일용).
    """
    if n <= 0 or n >= len(items):
        return list(items)
    nd = round(n * 2 / 3)
    out: list[dict] = []
    for split, k in (("dev", nd), ("heldout", n - nd)):
        out += stratified_sample([x for x in items if x["split"] == split], k, key, r)
    return out


CASE_KEYS = ("split", "category", "strata", "input", "expect")


def number_cases(cases: list[dict], prefix: str, **head: object) -> list[dict]:
    """나눔마다 차례 번호(prefix-d0001 · prefix-h0001)를 붙이고 사례 키 순서를 맞춘다.

    head는 id 다음에 둘 키 (예: trade="dobae")."""
    n: Counter[str] = Counter()
    out = []
    for c in cases:
        n[c["split"]] += 1
        first = {"id": f"{prefix}-{c['split'][0]}{n[c['split']]:04d}"} | head
        rest = {k: v for k, v in c.items() if k not in CASE_KEYS and k not in first}
        out.append(first | {k: c[k] for k in CASE_KEYS if k in c} | rest)
    return out


# ---------------------------------------------------------------- 문장 조각
class Fragments:
    """문장 조각 묶음 이름 → 조각 목록.

    묶음마다 번호 % 3 == 2인 조각은 held-out 전용, 나머지는 dev 전용이라 같은 조각이 두 나눔에 같이
    나오지 않는다. 고른 조각은 used에 '묶음:번호'로 남겨 나중에 겹침을 점검한다.
    """

    def __init__(self, table: dict[str, Sequence]) -> None:
        self.table = table

    def part(self, name: str, split: str) -> list[tuple[int, object]]:
        held = split == "heldout"
        return [(i, x) for i, x in enumerate(self.table[name]) if (i % 3 == 2) == held]

    def pick(self, r: random.Random, name: str, split: str, used: list[str] | None = None):
        return self.sample(r, name, split, 1, used)[0]

    def sample(
        self, r: random.Random, name: str, split: str, k: int, used: list[str] | None = None
    ) -> list:
        """서로 다른 조각 k개"""
        got = r.sample(self.part(name, split), k)
        if used is not None:
            used += [f"{name}:{i}" for i, _ in got]
        return [x for _, x in got]


# ---------------------------------------------------------------- 근사 중복
def norm(text: str) -> str:
    """수(112.4 · 1,262,725 등)는 #로 바꾸고 공백은 지운다 (숫자만 다른 글을 같은 글로 본다)."""
    return re.sub(r"\d+(?:[.,]\d+)*", "#", re.sub(r"\s", "", text))


def grams(text: str, n: int = 3, keep_numbers: bool = False) -> frozenset[str]:
    """글자 n-gram. keep_numbers면 수를 #로 바꾸지 않는다 (수가 답인 고객 말: '34평' · '25평'은 다른 사례)"""
    t = re.sub(r"\s", "", text) if keep_numbers else norm(text)
    return frozenset(t[i : i + n] for i in range(max(1, len(t) - n + 1)))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


class NearDup:
    """묶음(예: 나눔)마다 지금까지 받은 글과 글자 3-gram Jaccard가 threshold 이상이면 거른다.

    gram 역색인으로 겹치는 글만 견주어 수천 개도 빠르게 돈다.
    """

    def __init__(self, threshold: float = 0.8, keep_numbers: bool = False) -> None:
        self.threshold = threshold
        self.keep_numbers = keep_numbers
        self._sets: dict[Hashable, list[frozenset[str]]] = defaultdict(list)
        self._index: dict[Hashable, dict[str, list[int]]] = defaultdict(dict)

    def _nearest(self, g: frozenset[str], group: Hashable) -> float:
        hits: Counter[int] = Counter()
        index = self._index[group]
        for x in g:
            for j in index.get(x, ()):
                hits[j] += 1
        sets = self._sets[group]
        return max((c / (len(g) + len(sets[j]) - c) for j, c in hits.items()), default=0.0)

    def nearest(self, text: str, group: Hashable = None) -> float:
        """이 묶음에서 가장 비슷한 글과의 Jaccard"""
        return self._nearest(grams(text, keep_numbers=self.keep_numbers), group)

    def add(self, text: str, group: Hashable = None) -> bool:
        """비슷한 글이 없으면 넣고 True, 있으면 넣지 않고 False"""
        g = grams(text, keep_numbers=self.keep_numbers)
        if self._nearest(g, group) >= self.threshold:
            return False
        sets, index = self._sets[group], self._index[group]
        for x in g:
            index.setdefault(x, []).append(len(sets))
        sets.append(g)
        return True


# ---------------------------------------------------------------- 잡음 (규칙이라 두 나눔이 같이 쓴다)
def _partial_space(t: str, r: random.Random) -> str:
    return "".join(ch for ch in t if ch != " " or r.random() < 0.5)


def _add_space(t: str, r: random.Random) -> str:
    spots = [i for i in range(1, len(t)) if "가" <= t[i - 1] <= "힣" and "가" <= t[i] <= "힣"]
    if len(t) < 3 or not spots:
        return t
    i = r.choice(spots)
    return t[:i] + " " + t[i:]


def _spelling(t: str, r: random.Random) -> str:
    for a, b in (
        ("돼요", "되요"),
        ("할게요", "할께요"),
        ("하려고요", "할려구요"),
        ("얼마예요", "얼마에요"),
    ):
        t = t.replace(a, b)
    return t


_NOISE: dict[str, Callable[[str, random.Random], str]] = {
    "nospace": lambda t, r: t.replace(" ", ""),
    "partial_space": _partial_space,
    "add_space": _add_space,
    "ceiling_typo": lambda t, r: t.replace("천장", "천정"),
    "pyeong_typo": lambda t, r: re.sub(r"(\d)평(?![형수당])", r"\1펑", t, count=1),
    "spelling": _spelling,
    "yeo": lambda t, r: re.sub(r"요([.!?]|$)", r"여\1", t),
    "informal": lambda t, r: re.sub(r"(이에요|예요)\.", "임.", t),
    "tail": lambda t, r: t + r.choice([" ㅠㅠ", " ㅎㅎ", "!!", "~~"]),
    "drop_punct": lambda t, r: re.sub(r"(?<!\d)[.,]|[.,](?!\d)", "", t),  # 84.9 같은 소수점은 둔다
}
NOISE_OPS = tuple(_NOISE)


def noisy(
    text: str, r: random.Random, k: int = 2, ops: Sequence[str] = NOISE_OPS
) -> tuple[str, list[str]]:
    """잡음 규칙 k개를 골라 차례로 적용한다. 실제로 글이 바뀐 규칙 이름만 돌려준다."""
    done: list[str] = []
    for op in r.sample(list(ops), min(k, len(ops))):
        s = _NOISE[op](text, r)
        if s != text:
            text = s
            done.append(op)
    return text, done


# ---------------------------------------------------------------- 파일 · 표
def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def read_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def get(row: dict, dotted: str) -> object:
    """'strata.occupied'처럼 점으로 이은 키로 값을 꺼낸다 (없으면 None)."""
    cur: object = row
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def count_table(rows: list[dict], key: str, title: str | None = None) -> str:
    """key 값 × 나눔 개수 표 (마크다운)"""
    cnt = Counter((str(get(row, key)), row["split"]) for row in rows)
    vals = sorted({v for v, _ in cnt})
    out = [
        f"| {title or key} | dev | held-out | 합계 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for v in vals:
        d, h = cnt[v, "dev"], cnt[v, "heldout"]
        out.append(f"| {v} | {d} | {h} | {d + h} |")
    d = sum(row["split"] == "dev" for row in rows)
    out.append(f"| 합계 | {d} | {len(rows) - d} | {len(rows)} |")
    return "\n".join(out)


def split_report(cases: list[dict]) -> dict:
    """무료 점검 공통: id 중복 · 같은 입력 · 범주마다 dev:held-out 2:1 · 두 나눔의 조각 겹침"""
    ids = [c.get("id") for c in cases]
    inputs = [json.dumps(c.get("input"), sort_keys=True, ensure_ascii=False) for c in cases]
    cnt = Counter((c.get("category"), c.get("split")) for c in cases)
    uneven = sorted(
        cat for cat in {k for k, _ in cnt} if abs(cnt[cat, "dev"] - 2 * cnt[cat, "heldout"]) > 2
    )
    tpl = {s: {x for c in cases if c.get("split") == s for x in c.get("tpl", [])} for s in SPLITS}
    return {
        "n": len(cases),
        "dup_ids": len(ids) - len(set(ids)),
        "dup_inputs": len(inputs) - len(set(inputs)),
        "uneven": uneven,
        "shared_fragments": sorted(tpl["dev"] & tpl["heldout"]),
    }


def pair_coverage(rows: list[dict], keys: Sequence[str]) -> tuple[int, int]:
    """두 칸씩 짝지은 값 조합 중 사례에 나온 것 / 나올 수 있는 것"""
    seen = total = 0
    for a, b in itertools.combinations(keys, 2):
        va = {get(row, a) for row in rows}
        vb = {get(row, b) for row in rows}
        pairs = {(get(row, a), get(row, b)) for row in rows}
        seen += len(pairs)
        total += len(va) * len(vb)
    return seen, total

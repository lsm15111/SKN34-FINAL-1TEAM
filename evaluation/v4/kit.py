"""v4 평가 공용: 경로 · JSONL · 구간 · 토큰 어림 · 비용 기록. 표준 라이브러리만 써요(LLM · DB 없음)."""

import csv
import hashlib
import json
import math
import random
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

import prices

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SETS = HERE / "sets"
SCENARIOS = SETS / "scenarios"
RUNS = HERE / "runs"


def utf8_stdout() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8", newline="\n")  # 저장소 줄 끝(LF)과 같게


_LOCK = threading.Lock()


def append_jsonl(path: Path, row: dict) -> None:
    """한 줄씩 바로 써요(중간에 멈춰도 끝난 것은 남아요). 여러 일꾼이 같이 써도 줄이 섞이지 않게 잠가요."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    with _LOCK, path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)


def stable_int(*parts) -> int:
    """씨앗 고정 난수용 정수(파이썬 hash와 달리 실행마다 같아요)."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """이항 비율 k/n의 95% Wilson 구간."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def bootstrap_ci(
    values: Sequence[float], *, n_boot: int = 2000, seed: int = 20261121, alpha: float = 0.05
) -> tuple[float, float] | None:
    """평균의 부트스트랩 구간(항목을 다시 뽑아요). 값이 없으면 None."""
    if not values:
        return None
    rnd = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rnd.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(n_boot * alpha / 2)]
    hi = means[min(n_boot - 1, int(n_boot * (1 - alpha / 2)))]
    return (round(lo, 3), round(hi, 3))


def est_tokens(text: str) -> int:
    """토큰 어림(글자 수 기준). 한글 한 글자 ≈ 1토큰, 그 밖은 3.2글자 ≈ 1토큰으로 크게 잡아요.
    실제 값은 시범 실행의 usage로 바꿔요(count_tokens API는 키가 있어야 해서 쓰지 않아요)."""
    if not text:
        return 0
    ko = sum(1 for ch in text if "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ")
    return math.ceil(ko + (len(text) - ko) / 3.2)


class CostLog:
    """runs/<tag>/cost.csv에 호출마다 한 줄. 이미 있으면 이어 쓰고 누적을 다시 읽어요(이어 하기).

    estimated=1은 스텁 · 어림 값이에요(실제로 낸 돈이 아님). 상한 확인은 두 값을 합쳐서 해요."""

    FIELDS = (
        "ts", "kind", "item", "step", "model", "input_tokens", "cache_write_tokens",
        "cache_read_tokens", "output_tokens", "cost_usd", "estimated", "cum_usd",
    )  # fmt: skip

    def __init__(self, path: Path, kind: str):
        self.path, self.kind = path, kind
        self.lock = threading.Lock()
        self.spent = 0.0
        self.real = 0.0
        self.unknown = 0
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    c = float(r["cost_usd"]) if r["cost_usd"] else 0.0
                    self.spent += c
                    if r["estimated"] == "0":
                        self.real += c
                    if not r["cost_usd"]:
                        self.unknown += 1

    def add(
        self, item: str, step: str, model: str | None, usage, *, estimated: bool
    ) -> float | None:
        u = prices.usage_of(usage)
        cost = prices.cost_usd(model, u)
        with self.lock:
            self.spent += cost or 0.0
            if not estimated:
                self.real += cost or 0.0
            if cost is None:
                self.unknown += 1
            new = not self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(self.FIELDS)
                w.writerow([
                    time.strftime("%Y-%m-%dT%H:%M:%S"), self.kind, item, step, model or "",
                    u["input"], u["cache_write"], u["cache_read"], u["output"],
                    "" if cost is None else f"{cost:.6f}", 1 if estimated else 0, f"{self.spent:.6f}",
                ])  # fmt: skip
        return cost


class Budget:
    """상한(--max-usd) 지키기: 일을 시작하기 전에 어림을 잡아 두고(reserve), 끝나면 실제로 바꿔요(settle).
    여러 일꾼이 같이 돌아도 잡아 둔 몫까지 합쳐 상한을 넘지 않게 해요."""

    def __init__(self, max_usd: float | None, spent: float = 0.0):
        self.max_usd = max_usd
        self.spent = spent
        self.held = 0.0
        self.lock = threading.Lock()

    def reserve(self, usd: float) -> bool:
        with self.lock:
            if self.max_usd is not None and self.spent + self.held + usd > self.max_usd:
                return False
            self.held += usd
            return True

    def settle(self, held: float, actual: float) -> None:
        with self.lock:
            self.held -= held
            self.spent += actual

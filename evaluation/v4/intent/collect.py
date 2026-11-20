"""v4 비서 의도 held-out 후보 모으기 · 세트 점검(LLM 0회).

    cd backend && uv run python ../evaluation/v4/intent/collect.py            # 후보(pool) 다시 만들기
    cd backend && uv run python ../evaluation/v4/intent/collect.py --check    # dev · held-out 점검

held-out은 이번에 새로 쓰지 않은 글만 모아요(출처 칸을 남겨요). 우선순위가 높은 출처부터 같은 글은 하나만 둬요.
- scenario: v4 시나리오 대본의 고객 · 업체 말(evaluation/v4/sets/scenarios)
- redteam: 레드팀 중 공격 글을 입력 칸(견적서 메모 · 업체 글 · 웹 · 요청 메모)에 심은 문항의 사용자 말(말 자체는 정상)
- compare: v4 비교 세트(core32 · set30 · multi45)
- intent_v1: v1 의도 held-out(evaluation/intent/heldout.jsonl)
- coverage: v3 범위 질문(빈 글 · 이모지만 · 주입 시도는 뺌)
- ask_back: 되묻기 세트(evaluation/ask_back)

글은 intent.clean(전화 · 동호수 가림)을 지난 꼴로 둬요. 학습 · 평가 글에 개인정보를 넣지 않아요.
"""

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parent
sys.path.insert(0, str(V4))
sys.path.insert(0, str(V4.parents[1] / "backend"))

from kit import RUNS, ROOT, SCENARIOS, SETS, jsonl, utf8_stdout, write_jsonl

from app.agent.intent import DONGHO, PHONE, clean

POOL = RUNS / "intent" / "pool.jsonl"  # 라벨 붙이기 전 후보(git 밖)
DEV = HERE / "dev.jsonl"
HELDOUT = HERE / "heldout.jsonl"
LABELS = (
    "home_info", "standard_quote", "vendor_pick", "visit", "quote_compare", "schedule",
    "knowledge", "guide", "out_of_scope",
)  # fmt: skip
SOURCES = ("scenario", "redteam", "compare", "intent_v1", "coverage", "ask_back")
# 레드팀: 공격 글을 입력 칸에 심은 문항만(사용자 말은 정상)
RT_NORMAL = ("inject_quote_memo", "inject_vendor_text", "inject_web", "inject_request_note")
SKIP_COVERAGE = ("empty", "inject")
# dev 글이 held-out 글과 이 값 이상 비슷하면 거의 같은 글로 봐요(dev에서 뺌).
# 0.30~0.45 쌍은 눈으로 보고 held-out 문장과 같은 내용을 다시 말한 dev 줄을 더 뺐어요(docs/v4/eval/intent.md)
NEAR = 0.45
LETTER = re.compile(r"[가-힣A-Za-z]")


def norm(text: str) -> str:
    """같은 글 찾기용: 띄어쓰기 · 문장부호를 뺀 소문자."""
    t = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[\s\W_]+", "", t)


def _grams(text: str) -> Counter[str]:
    """낱말 안 글자 2~4개 묶음(낱말 앞뒤에 빈칸). 문장부호는 빼고 소문자."""
    t = re.sub(r"[^\w\s]+|_", " ", unicodedata.normalize("NFC", text).lower())
    out: Counter[str] = Counter()
    for word in t.split():
        w = f" {word} "
        out.update(w[i : i + n] for n in (2, 3, 4) for i in range(max(1, len(w) - n + 1)))
    return out


class NearIndex:
    """거의 같은 글 찾기: 낱말 안 글자 2~4개 묶음 TF-IDF 코사인(색인 글로 IDF)."""

    def __init__(self, texts: list[str]) -> None:
        grams = [_grams(t) for t in texts]
        df: Counter[str] = Counter(g for gs in grams for g in gs)
        n = len(texts)
        self.idf = {g: math.log((1 + n) / (1 + c)) + 1 for g, c in df.items()}
        self.default = math.log(1 + n) + 1  # 색인에 없는 묶음
        self.vecs = [self._vec(g) for g in grams]
        self.post: dict[str, list[int]] = {}
        for i, v in enumerate(self.vecs):
            for g in v:
                self.post.setdefault(g, []).append(i)

    def _vec(self, grams: Counter[str]) -> dict[str, float]:
        v = {g: (1 + math.log(c)) * self.idf.get(g, self.default) for g, c in grams.items()}
        s = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / s for g, x in v.items()}

    def best(self, text: str) -> tuple[float, int]:
        """가장 비슷한 색인 글의 (코사인, 번호). 겹치는 묶음이 없으면 (0, -1)."""
        q = self._vec(_grams(text))
        dots: Counter[int] = Counter()
        for g, x in q.items():
            for i in self.post.get(g, ()):
                dots[i] += x * self.vecs[i][g]
        if not dots:
            return 0.0, -1
        i, s = dots.most_common(1)[0]
        return s, i


def _scenarios() -> list[dict]:
    out = []
    for f in sorted(SCENARIOS.glob("*.json")):
        if f.name.startswith("scenario."):
            continue
        sc = json.loads(f.read_text(encoding="utf-8"))
        for k, t in enumerate(sc.get("script", {}).get("turns", []), start=1):
            if "say" in t:
                out.append(
                    {"id": f"sc:{sc['id']}:{k}", "src": "scenario", "src_id": f"{sc['id']}#{k}",
                     "surface": sc["surface"], "raw": t["say"]}
                )  # fmt: skip
    return out


def _redteam() -> list[dict]:
    out = []
    for r in jsonl(SETS / "redteam.jsonl"):
        if r["category"] not in RT_NORMAL:
            continue
        for k, t in enumerate(r["turns"], start=1):
            text = t if isinstance(t, str) else t.get("say", "")
            out.append(
                {"id": f"rt:{r['id']}:{k}", "src": "redteam", "src_id": f"{r['id']}#{k}",
                 "surface": r["surface"], "raw": text}
            )  # fmt: skip
    return out


def _compare() -> list[dict]:
    return [
        {"id": f"cmp:{r['id']}", "src": "compare", "src_id": r["id"], "surface": "customer",
         "raw": r["turns"][-1]}
        for r in jsonl(SETS / "compare.jsonl")
    ]  # fmt: skip


def _intent_v1() -> list[dict]:
    rows = jsonl(ROOT / "evaluation" / "intent" / "heldout.jsonl")
    return [
        {"id": f"iv1h:{k}", "src": "intent_v1", "src_id": f"heldout.jsonl#{k}",
         "surface": "customer", "raw": r["text"]}
        for k, r in enumerate(rows, start=1)
    ]  # fmt: skip


def _coverage() -> list[dict]:
    rows = jsonl(ROOT / "evaluation" / "v3" / "coverage_questions.jsonl")
    return [
        {"id": f"cov:{r['id']}", "src": "coverage", "src_id": r["id"], "surface": "customer",
         "raw": r["text"]}
        for r in rows
        if r["cat"] not in SKIP_COVERAGE and LETTER.search(r["text"] or "")
    ]  # fmt: skip


def _ask_back() -> list[dict]:
    out = []
    for split in ("dev", "heldout"):
        for k, r in enumerate(jsonl(ROOT / "evaluation" / "ask_back" / f"{split}.jsonl"), 1):
            out.append(
                {"id": f"ab:{split}:{k}", "src": "ask_back", "src_id": f"{split}.jsonl#{k}",
                 "surface": "customer", "raw": r["text"]}
            )  # fmt: skip
    return out


def gather() -> list[dict]:
    """출처 우선순위대로 모으고 같은 글(norm)은 처음 것만 둬요."""
    seen: dict[str, str] = {}
    out = []
    for rows in (_scenarios(), _redteam(), _compare(), _intent_v1(), _coverage(), _ask_back()):
        for r in rows:
            text = clean(r.pop("raw"))
            key = norm(text)
            if not key:
                continue
            if key in seen:
                continue
            seen[key] = r["id"]
            out.append({**r, "text": text})
    return out


def pii(text: str) -> bool:
    """가리지 않은 전화 · 동호수가 남았는지."""
    return bool(PHONE.search(text) or DONGHO.search(text))


def check() -> int:
    """dev · held-out 점검: 라벨 · 출처 글과 같은지 · 개인정보 · 겹침 · 2:1."""
    errors: list[str] = []
    pool = {r["id"]: r for r in gather()}
    dev, held = jsonl(DEV), jsonl(HELDOUT)
    for name, rows in (("dev", dev), ("heldout", held)):
        ids = Counter(r["id"] for r in rows)
        errors += [f"{name}: id 겹침 {i}" for i, n in ids.items() if n > 1]
        for r in rows:
            if r["label"] not in LABELS:
                errors.append(f"{name} {r['id']}: 모르는 라벨 {r['label']}")
            if any(a not in LABELS or a == r["label"] for a in r.get("alt", [])):
                errors.append(f"{name} {r['id']}: alt가 틀림")
            if pii(r["text"]):
                errors.append(f"{name} {r['id']}: 전화 · 동호수가 남음")
            if r["text"] != clean(r["text"]):
                errors.append(f"{name} {r['id']}: clean을 지나지 않은 글")
    for r in held:
        if r.get("synthetic"):
            errors.append(f"heldout {r['id']}: 새로 쓴 글은 held-out에 두지 않아요")
        src = pool.get(r["id"])
        if src is None or src["text"] != r["text"]:
            errors.append(f"heldout {r['id']}: 출처 글과 다름")
    idx = NearIndex([r["text"] for r in held])
    for r in dev:
        sim, j = idx.best(r["text"])
        if sim >= NEAR:
            errors.append(f"dev {r['id']}: held-out {held[j]['id']}과 거의 같은 글({sim:.2f})")
    keys = Counter(norm(r["text"]) for r in dev)
    errors += [f"dev 안에 같은 글이 {n}번" for k, n in keys.items() if n > 1]
    ratio = len(dev) / max(1, len(held))
    if not 1.9 <= ratio <= 2.1:
        errors.append(f"dev : held-out = {ratio:.2f} : 1 (2:1이어야 해요)")
    for e in errors:
        print("틀림:", e)
    syn = sum(1 for r in dev if r.get("synthetic"))
    print(
        f"dev {len(dev)}(합성 {syn}, {syn / max(1, len(dev)):.1%}) · held-out {len(held)} · "
        f"비 {ratio:.2f}:1 · 틀림 {len(errors)}"
    )
    return 1 if errors else 0


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        return check()
    rows = gather()
    write_jsonl(POOL, rows)
    print(f"후보 {len(rows)}줄 → {POOL.relative_to(ROOT)}")
    print(Counter(r["src"] for r in rows), Counter(r["surface"] for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

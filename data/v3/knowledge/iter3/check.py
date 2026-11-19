"""지식 보강 3회차 조각 검사. 묶은 파일(chunks.jsonl)이나 나눠 쓴 파일(parts/*.jsonl)을 봐요.

세는 것: 2회차 검사(iter2/check.py)와 같은 것 + 3회차에 더한 것
- 2회차와 같음: 개수 · 빈 칸 · id 중복(1 · 2회차 포함) · 출처 없는 행 · 값 밖(공종 · 주제 · 라이선스 · 빈 주제) ·
  요지 문장 수(3~6) · 해요체 요지 문장 수(2~4) · 해요체 요지의 숫자가 요지에 있는지 · 해요체로 끝나는지 ·
  고객 질문(answers) 3~5개 · dev 질문을 그대로 옮긴 것 · 빈 주제마다 2개 이상
- 더한 것: 금액 숫자(원) · 기간 숫자(일 · 주 · 개월 · 년) · 출처 종류(kind) 값 · 블로그 · 커뮤니티 출처 ·
  같은 doc_key인데 출처 이름 · 주소가 다름 · held-out 질문과 같은 고객 질문(글은 보이지 않고 수만 세요)
- 화면 출처 종류: v3_csv.kind_of가 정하는 종류와 조각에 적은 종류(kind)가 다르면 수만 세요(제조사 → 'guide' 등).
실행: python -X utf8 data/v3/knowledge/iter3/check.py [파일 ...] [--gaps=H01,H02]   (파일을 안 주면 chunks.jsonl)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

from gaps import dev_rows

from app.knowledge.v3_csv import kind_of

TRADES = {"dobae", "mokgong", "floor", "tile", "bath", "kitchen", "paint", "film", "electric", "window",
          "demolition", "plumbing", "common"}  # fmt: skip
TOPICS = {"spec", "defect", "contract", "dispute", "permit", "noise", "waste", "asbestos", "air",
          "productivity", "safety", "license_biz", "guide"}  # fmt: skip
LICENSES = {"공공저작물(저작권법 제7조, 법령 · 고시)", "공공누리 제1유형", "공공누리 제4유형(요지만)",
            "확인 못 함(요지만)"}  # fmt: skip
# 출처 종류(bm25.TIER 이름). 블로그 · 커뮤니티 · 후기는 3회차에서 쓰지 않아요(kind_of가 'guide'로 올려 버려요)
KINDS = {"law", "gov_notice", "gov_guide", "gov_qa", "kcs", "standard_contract", "consumer_agency",
         "official", "public_data", "gov", "maker", "maker_guide", "industry"}  # fmt: skip
CASUAL = {"blog", "community", "platform", "experience", "news"}
REQUIRED = ["id", "gap", "trade", "topic", "title", "summary", "summary_haeyo", "source_url",
            "source_name", "clause", "checked_at", "license", "answers", "kind", "publisher", "doc_key",
            "verify"]  # fmt: skip
NUM = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s?(?:만|억|천)?\s?"
    r"(?:원|㎡|m²|mm|cm|km|m|년|개월|달|주|일|시간|분|초|%|℃|°C|품|평|배|회|층|세대|dB|kg|g|L|ℓ|cm²|개|장|롤)?"
)
MONEY = re.compile(
    r"\d[\d,.]*\s*(?:만\s*원|천\s*원|억\s*원|억|원)|[일이삼사오육칠팔구십백천만]+\s*원"
)
PERIOD = re.compile(
    r"\d[\d,.~]*\s*(?:일|주일|주|개월|달|년)(?![가-힣])|\d[\d,.~]*\s*(?:일|주|개월|년)\s*(?:이상|이내|안|정도|쯤|뒤|후|만에|동안|가량)"
)
ENDS = ("요", "죠")


def sentences(s: str) -> list[str]:
    # 문장 끝 = 한글 · 닫는 괄호 뒤 마침표 · 물음표. '1999. 9. 1.' 같은 날짜는 끝으로 안 세요
    return [x.strip() for x in re.split(r"(?<=[가-힣)])[.!?](?:\s+|$)", s.strip()) if x.strip()]


def haeyo_ok(sent: str) -> bool:
    s = re.sub(r"(\s*\([^()]*\))+\s*$", "", sent.strip()).rstrip(" .!?~\"'”’")
    return s.endswith(ENDS)


def flat(s: str) -> str:
    return re.sub(r"\s+", "", s).replace(",", "")


def numbers_missing(haeyo: str, summary: str) -> list[str]:
    base = flat(summary)
    out = []
    for m in NUM.finditer(haeyo):
        tok = m.group(0).strip()
        if tok and flat(tok) not in base:
            out.append(tok)
    return out


def norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s)


def dev_texts() -> set[str]:
    """dev 질문 글(새는지 보려고). gaps.dev_rows와 같은 줄(3회차 전 점검의 dev 질문)."""
    return {norm(r["text"]) for r in dev_rows()}


def heldout_texts() -> set[str]:
    """held-out 질문 글(같은 글을 고객 질문 · 열쇠로 쓰지 않았는지 세기만 해요. 글은 보이지 않아요)."""
    out: set[str] = set()
    rows = ROOT / "evaluation" / "v3" / ".cache" / "kb" / "coverage_rows.jsonl"
    dev = dev_texts()
    for line in rows.read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = norm(json.loads(line)["text"])
            if t not in dev:
                out.add(t)  # dev가 아닌 줄(held-out · 라벨 없음) 전부. 넓게 잡아요
    return out


def old_ids() -> set[str]:
    out = set()
    for p in (HERE.parent / "chunks.jsonl", HERE.parent / "iter2" / "chunks.jsonl"):
        out |= {
            json.loads(x)["id"] for x in p.read_text(encoding="utf-8").splitlines() if x.strip()
        }
    return out


def old_docs() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in (HERE.parent / "chunks.jsonl", HERE.parent / "iter2" / "chunks.jsonl"):
        for x in p.read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                out.setdefault(r.get("doc_key") or r["id"], r["source_name"])
    return out


def load(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        for i, line in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                r = json.loads(line)
                r["_where"] = f"{p.name}:{i}"
                rows.append(r)
    return rows


def check(
    rows: list[dict], only: set[str] | None = None
) -> tuple[list[tuple[str, str]], list[str]]:
    table: list[tuple[str, str]] = []
    problems: list[str] = []
    gaps = json.loads((HERE / "gaps.json").read_text(encoding="utf-8"))["topics"]
    gap_ids = {g["id"] for g in gaps}
    want = only or {
        g["id"] for g in gaps if g.get("need") == "chunks"
    }  # 2개 이상인지 볼 빈 주제(새 조각 주제)
    old = old_ids()
    olddoc = old_docs()
    dev = dev_texts()
    held = heldout_texts()

    def bad(kind: str, r: dict, why: str = "") -> None:
        problems.append(f"{kind}: {r.get('id') or r['_where']} {why}".rstrip())

    ids = Counter(r.get("id") for r in rows)
    docs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    shown = Counter()
    held_hits = 0
    for r in rows:
        for k in REQUIRED:
            v = r.get(k)
            if v in (None, "", []) or (isinstance(v, str) and not v.strip()):
                bad("빈 칸", r, k)
        if ids[r.get("id")] > 1:
            bad("id 중복", r)
        if r.get("id") in old:
            bad("1 · 2회차 id와 겹침", r)
        if not str(r.get("id", "")).startswith(f"kv3i3-{r.get('gap')}-"):
            bad("id 모양", r, "kv3i3-<빈 주제>-<번호>")
        if not str(r.get("source_url", "")).startswith(("http://", "https://")):
            bad("출처 주소 없음", r)
        for k, allowed in (
            ("trade", TRADES),
            ("topic", TOPICS),
            ("license", LICENSES),
            ("gap", gap_ids),
            ("kind", KINDS),
        ):
            if r.get(k) not in allowed:
                bad("값 밖", r, f"{k}={r.get(k)}")
        if r.get("kind") in CASUAL:
            bad("블로그 · 커뮤니티 출처", r, r.get("kind"))
        for t in r.get("also", []) or []:
            if t not in TRADES:
                bad("값 밖", r, f"also={t}")
        dk = r.get("doc_key") or r.get("id")
        docs[dk].add((r.get("source_name", ""), r.get("source_url", "")))
        if dk in olddoc and olddoc[dk] != r.get("source_name"):
            bad("doc_key가 1 · 2회차 다른 문서와 겹침", r, dk)
        shown[(r.get("kind"), kind_of(r.get("source_name", ""), r.get("license", "")))] += 1
        s, h = r.get("summary", ""), r.get("summary_haeyo", "")
        if not 3 <= len(sentences(s)) <= 6:
            bad("요지 문장 수", r, str(len(sentences(s))))
        hs = sentences(h)
        if not 2 <= len(hs) <= 4:
            bad("해요체 문장 수", r, str(len(hs)))
        if not all(haeyo_ok(x) for x in hs):
            bad("해요체 아님", r, next(x for x in hs if not haeyo_ok(x))[-25:])
        miss = numbers_missing(h, s)
        if miss:
            bad("해요체 숫자가 요지에 없음", r, ", ".join(miss))
        ans = r.get("answers") or []
        for field, text in (
            ("요지", s),
            ("해요체", h),
            ("질문", " ".join(ans)),
            ("제목", r.get("title", "")),
        ):
            m = MONEY.search(text)
            if m:
                bad("금액 숫자", r, f"{field}: {m.group(0)}")
            m = PERIOD.search(text)
            if m:
                bad("기간 숫자", r, f"{field}: {m.group(0)}")
        if not 3 <= len(ans) <= 5 or not all(isinstance(a, str) and a.strip() for a in ans):
            bad("질문 수", r, str(len(ans)))
        for a in ans:
            if norm(a) in dev:
                bad("dev 질문을 그대로 옮김", r, a)
            if norm(a) in held:
                held_hits += 1
                bad("held-out 질문과 같은 글", r, "(글은 안 보여요)")
            if len(a) > 80:
                bad("질문 80자 넘음", r, a[:20])
    for dk, v in docs.items():
        if len(v) > 1:
            problems.append(f"같은 doc_key인데 출처 이름 · 주소가 다름: {dk} {len(v)}가지")
    per_gap = Counter(r.get("gap") for r in rows)
    short = sorted(g for g in want if per_gap.get(g, 0) < 2)
    sums = Counter(norm(r.get("summary", "")) for r in rows)
    answers = Counter(norm(a) for r in rows for a in r.get("answers") or [])
    cnt = lambda k: sum(1 for p in problems if p.startswith(k))
    table += [
        ("조각 수", str(len(rows))),
        ("필수 칸 빈 칸 · id 중복 · 1 · 2회차와 겹침 · id 모양", f"{cnt('빈 칸')} · {cnt('id 중복')} · {cnt('1 · 2회차')} · {cnt('id 모양')}"),
        ("출처 주소 없는 행", str(cnt("출처 주소"))),
        ("값 밖(공종 · 주제 · 라이선스 · 빈 주제 · 출처 종류)", str(cnt("값 밖"))),
        ("블로그 · 커뮤니티 출처", str(cnt("블로그"))),
        ("요지 3~6문장 벗어남 · 해요체 2~4문장 벗어남", f"{cnt('요지 문장')} · {cnt('해요체 문장')}"),
        ("해요체로 안 끝나는 조각", str(cnt("해요체 아님"))),
        ("해요체 숫자가 요지에 없는 조각", str(cnt("해요체 숫자"))),
        ("금액 숫자 · 기간 숫자", f"{cnt('금액 숫자')} · {cnt('기간 숫자')}"),
        ("질문 3~5개 벗어남 · 80자 넘음 · dev 질문 그대로 · held-out 질문 그대로", f"{cnt('질문 수')} · {cnt('질문 80')} · {cnt('dev 질문')} · {held_hits}"),
        ("요지 같은 글자 중복 · 질문 같은 글자 중복", f"{sum(v - 1 for v in sums.values() if v > 1)} · {sum(v - 1 for v in answers.values() if v > 1)}"),
        ("같은 doc_key 다른 출처 · 1 · 2회차 문서와 겹침", f"{cnt('같은 doc_key')} · {cnt('doc_key가')}"),
        ("빈 주제별 조각 수", ", ".join(f"{g} {per_gap.get(g, 0)}" for g in sorted(want))),
        ("2개 못 채운 빈 주제", " · ".join(short) or "없음"),
        ("출처 종류별(kind)", ", ".join(f"{k} {v}" for k, v in Counter(r.get("kind") for r in rows).most_common())),
        ("화면 출처 종류(kind_of)가 다른 조각", ", ".join(f"{a}→{b} {v}" for (a, b), v in shown.most_common() if a != b) or "없음"),
        ("라이선스별", ", ".join(f"{k} {v}" for k, v in Counter(r.get("license") for r in rows).most_common())),
        ("확인 방법별(verify)", ", ".join(f"{k} {v}" for k, v in Counter(r.get("verify", "") for r in rows).most_common())),
    ]  # fmt: skip
    if sums and max(sums.values()) > 1:
        problems.append("요지 같은 글자 중복")
    if short:
        problems.append(f"2개 못 채운 빈 주제: {short}")
    return table, problems


def main() -> None:
    args = sys.argv[1:]
    only = {g for a in args if a.startswith("--gaps=") for g in a[7:].split(",") if g}
    paths = [Path(a) for a in args if not a.startswith("--")] or [HERE / "chunks.jsonl"]
    table, problems = check(load(paths), only or None)
    for k, v in table:
        print(f"| iter3 | {k} | {v} |")
    if problems:
        print("\n문제:")
        for p in problems[:80]:
            print("-", p)
        sys.exit(1)
    print("\n문제 없음")


if __name__ == "__main__":
    main()

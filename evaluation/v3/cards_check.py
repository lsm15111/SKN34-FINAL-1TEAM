"""답 카드 코드 검사 (카드 쓴 사람 · 검증 하위 에이전트 · CI가 같이 쓴다). LLM · DB 없음.

    backend/.venv/Scripts/python.exe evaluation/v3/cards_check.py                # 모든 카드
    backend/.venv/Scripts/python.exe evaluation/v3/cards_check.py --fix-sources  # sources 칸을 말뭉치로 채움
    backend/.venv/Scripts/python.exe evaluation/v3/cards_check.py backend/app/agent/cards/dobae.jsonl

오류(카드를 쓰면 안 됨)
- 모양(Pydantic AnswerCard) · id 겹침 · 파일 이름과 공종이 다름
- 인용 조각이 말뭉치에 없음
- 문장과 인용 조각의 글자 두 개 묶음 겹침 < 0.18 (bm25.verify_cites 기준)
- 금액(원) · 기간(일 · 주 · 개월) 숫자, 인용 조각에 없는 숫자, 한글 금액, 쓰면 안 되는 표현(guard · AI 행동)
- 같은 열쇠 질문이 두 카드에 있음
경고
- 열쇠가 다른 카드 열쇠와 자카드 ≥ 0.6 · 해요체로 안 끝남 · 원문과 40자 넘게 같음 · 책 조각만 인용
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common import ROOT, corpus_path, utf8_stdout
from pydantic import ValidationError
from rank_server import load_index

from app.agent.v3.check import AI_ACTS
from app.knowledge import bm25
from app.knowledge.cards import CARD_DIR, DOC_REFS, AnswerCard
from app.v2 import guard

# 카드 글에 쓰면 안 되는 숫자: 금액 · 공사 기간(계산 엔진 몫). 년(하자 기간 같은 법 조항)은 인용 조각에 있으면 둔다
MONEY_OR_PERIOD = re.compile(r"\d[\d,.]*\s*(?:만\s*원|천\s*원|억\s*원|억|원|일|주일|주|개월)")
HAEYO = re.compile(r"(?:요|요\.|요\)|요\?|까요\?)$")


def lcs_len(a: str, b: str) -> int:
    """가장 긴 같은 글자 이음 길이(짧은 문장용 단순 계산)."""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def overlap(sentence: str, items: list[bm25.Item]) -> float:
    sg = set(bm25.grams(sentence))
    if not sg:
        return 0.0
    tf: set[str] = set()
    for x in items:
        tf |= set(x.tf)
    return sum(1 for t in sg if t in tf) / len(sg)


def check_file(path: Path, ix: bm25.Index, fix: bool, all_keys: Counter) -> tuple[int, int, int]:
    errors = warns = 0
    rows = [x for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    out_rows = []
    seen_ids: set[str] = set()
    for n, line in enumerate(rows, 1):
        where = f"{path.name}:{n}"
        try:
            raw = json.loads(line)
            card = AnswerCard.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as e:  # 모양 오류는 첫 줄만
            print(f"[오류] {where} 모양: {str(e).splitlines()[0][:160]}")
            errors += 1
            out_rows.append(line)
            continue
        cid = card.id
        if cid in seen_ids:
            print(f"[오류] {where} id 겹침 {cid}")
            errors += 1
        seen_ids.add(cid)
        if path.stem != card.trade and not (path.stem == "service" and card.trade == "common"):
            print(f"[오류] {where} {cid}: 파일 {path.stem} ≠ 공종 {card.trade}")
            errors += 1
        missing = [r for r in card.cites() if r not in ix.by_ref and r not in DOC_REFS]
        if missing:
            print(f"[오류] {where} {cid}: 없는 조각 {missing}")
            errors += 1
        sents = list(card.answer) + [x for x in (card.caution, card.tip) if x]
        for s in sents:
            items = [ix.by_ref[r] for r in s.cites if r in ix.by_ref]
            src_text = " ".join(x.chunk.text for x in items)
            ov = overlap(s.text, items)
            doc_only = all(
                r in DOC_REFS for r in s.cites
            )  # 서비스 규칙 문장: 사람이 화면 글과 대 봐요
            if doc_only:
                src_text = s.text
            elif ov < bm25.CONF["cite_min"]:
                print(f"[오류] {where} {cid}: 근거 겹침 {ov:.2f} < 0.18 · {s.text[:40]}")
                errors += 1
            if MONEY_OR_PERIOD.search(s.text):
                print(f"[오류] {where} {cid}: 금액 · 기간 숫자 · {s.text[:50]}")
                errors += 1
            why = guard._why(s.text, guard.numbers(src_text), None)
            if why:
                print(f"[오류] {where} {cid}: {why} · {s.text[:50]}")
                errors += 1
            if AI_ACTS.search(s.text):
                print(f"[오류] {where} {cid}: AI 행동 표현 · {s.text[:50]}")
                errors += 1
            if not HAEYO.search(s.text.strip()):
                print(f"[경고] {where} {cid}: 해요체 끝이 아님 · {s.text[-20:]}")
                warns += 1
            if src_text and not doc_only and lcs_len(s.text, src_text) > 40:
                print(f"[경고] {where} {cid}: 원문과 40자 넘게 같음 · {s.text[:40]}")
                warns += 1
        kinds = {ix.by_ref[r].doc.kind for r in card.cites() if r in ix.by_ref}
        if kinds == {"book"}:
            print(f"[경고] {where} {cid}: 책 조각만 인용(화면에 출처 이름만)")
            warns += 1
        for k in card.keys:
            all_keys[k.strip()] += 1
        if fix:
            raw["sources"] = [
                {
                    "ref": r,
                    "title": ix.by_ref[r].doc.title,
                    "kind": ix.by_ref[r].doc.kind,
                    "publisher": ix.by_ref[r].doc.pub,
                }
                if r in ix.by_ref
                else {"ref": r, "title": DOC_REFS[r], "kind": "service", "publisher": "믿집"}
                for r in card.cites()
                if r in ix.by_ref or r in DOC_REFS
            ]
            out_rows.append(json.dumps(raw, ensure_ascii=False))
        else:
            out_rows.append(line)
    if fix:
        path.write_text("\n".join(out_rows) + "\n", encoding="utf-8")
    return errors, warns, len(rows)


def key_overlaps(paths: list[Path]) -> int:
    """다른 카드 열쇠끼리 자카드 ≥ 0.6이면 경고(같은 질문을 두 카드가 받음)."""
    keys: list[tuple[str, str]] = []
    for p in paths:
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                try:
                    c = json.loads(line)
                    keys.extend((c["id"], k) for k in c.get("keys", []))
                except (json.JSONDecodeError, KeyError):
                    continue
    grams = [(cid, k, set(bm25.grams(k))) for cid, k in keys]
    warns = 0
    for i in range(len(grams)):
        for j in range(i + 1, len(grams)):
            a, b = grams[i], grams[j]
            if a[0] == b[0] or not a[2] or not b[2]:
                continue
            jac = len(a[2] & b[2]) / len(a[2] | b[2])
            if jac >= 0.6:
                print(f"[경고] 열쇠 겹침 {jac:.2f}: {a[0]} '{a[1]}' ↔ {b[0]} '{b[1]}'")
                warns += 1
    return warns


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--fix-sources", action="store_true")
    ap.add_argument("--no-overlap", action="store_true", help="열쇠 겹침 검사를 건너뜀(빠르게)")
    a = ap.parse_args()
    ix = load_index(corpus_path())
    paths = a.files or sorted(CARD_DIR.glob("*.jsonl"))
    total = Counter()
    keys: Counter = Counter()
    per: dict[str, int] = {}
    for p in paths:
        e, w, n = check_file(p, ix, a.fix_sources, keys)
        total["errors"] += e
        total["warns"] += w
        total["cards"] += n
        per[p.stem] = n
    dup = [k for k, c in keys.items() if c > 1]
    for k in dup:
        print(f"[오류] 같은 열쇠가 여러 카드에: {k}")
    total["errors"] += len(dup)
    if not a.no_overlap:
        total["warns"] += key_overlaps(paths)
    print(
        f"\n카드 {total['cards']}장 · 오류 {total['errors']} · 경고 {total['warns']} · 공종별 {per}"
    )
    print(f"말뭉치 {ix.version} ({ix.n}조각) · 기준 {ROOT.name}")
    sys.exit(1 if total["errors"] else 0)


if __name__ == "__main__":
    main()

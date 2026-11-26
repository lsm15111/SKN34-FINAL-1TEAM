"""바닥 질문 세트(questions.jsonl)로 지식 자료가 바닥 질문을 얼마나 덮는지 잰다. LLM · 임베딩 호출 · DB 없음.

    cd backend
    .venv/Scripts/python.exe -I -X utf8 ../evaluation/floor/coverage.py --new <바닥 원문 CSV 폴더> [--synonyms <묶기 CSV>]

- 말뭉치
  - dev: data/processed · data/consult · data/v3/knowledge(요지 + iter2)를 sources.assemble로 읽은 것(data/local은 넣지 않음)
  - new: --new 폴더의 *_rag.csv(바닥 원문 조각, 저장소 밖 자료)
  - dev+new: 둘을 함께 assemble한 것(새 CSV를 data/processed에 넣었을 때 흉내)
  - 카드: app/agent/cards 그대로
- 근거 낱말 규칙(문항의 evidence): 조각 목록이고, 조각마다 낱말 묶음이 모두 든 글이 하나라도 있으면 그 조각을 찾은 것.
  띄어쓰기는 무시하고, 영문 낱말은 앞뒤가 영문이 아닐 때만 센다
- 잰 값
  - 자료 있음: 모든 조각을 말뭉치 어딘가에서 찾음(부분: 일부 조각만)
  - 위 5개: 지금 검색(search3.search, 공종 floor, BM25만)의 위 5개 글 안에서 모든 조각을 찾음.
    --synonyms를 주면 새 원문에서 bm25.search 위 5개를 묶기 표 없이 · 있이(고객 말 → 문서 말 검색어 하나 더) 견준다
  - v3 한 턴: turn.run_turn(LLM 끔, 관문 포함)이 카드 · 조각 문장 · 모름 중 무엇으로 답했는지,
    보여 준 글이 규칙에 맞는지, 금액 · 기간 정해 둔 글('업체 견적서에서 확인' 등)이 붙었는지
- 결과: --out(저장소 밖 JSON), 표는 표준 출력(마크다운)
"""

import argparse
import asyncio
import csv
import hashlib
import io
import json
import re
import sys
import uuid
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.v3.answer import KB
from app.agent.v3.schemas import TurnContext
from app.agent.v3.trades import TAG_TO_CODE
from app.agent.v3.turn import run_turn
from app.knowledge import bm25, cards, search3
from app.knowledge.json_csv import EXTRA, REQUIRED
from app.knowledge.sources import assemble
from app.knowledge.v3_csv import START, START2
from app.knowledge.v3_csv import rows as v3_rows

DIRS = [ROOT / "data/processed", ROOT / "data/consult"]
V3 = [
    (ROOT / "data/v3/knowledge/chunks.jsonl", START, "v3_knowledge_rag"),
    (ROOT / "data/v3/knowledge/iter2/chunks.jsonl", START2, "v3_knowledge_iter2_rag"),
]
CATS = ["자재", "시공", "순서", "기간", "비용", "하자", "AS", "규정", "계약", "관리", "셀프"]
MAKER = frozenset({"maker", "maker_guide"})  # 제조사 글(라이선스 결정 대기)
# 10공종 금액 · 기간 정해 둔 글(templates.PRICE_KNOWLEDGE · PERIOD_KNOWLEDGE)의 고정 부분
QUOTE_TEXT = ("금액은 실측 뒤 업체 견적서에서 확인해요", "기간은 집을 본 뒤 업체가 정해요")
TODAY = date(2026, 11, 25)
K = 5


def nz(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def term(t: str):
    k = nz(t)
    if re.fullmatch(r"[0-9a-z/.\-]+", k):
        pat = re.compile(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])")
        return lambda s: bool(pat.search(s))
    return lambda s: k in s


def compile_rule(evidence: list) -> list:
    return [[[term(t) for t in grp] for grp in piece] for piece in evidence]


def piece_ok(piece, s: str) -> bool:
    return all(any(f(s) for f in grp) for grp in piece)


def all_ok(rule, texts: list[str]) -> bool:
    return bool(texts) and all(any(piece_ok(p, s) for s in texts) for p in rule)


def read_csv(path: Path) -> tuple[str, list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return path.stem, list(csv.DictReader(f))


def v3_dataset(path: Path, start: int, key: str) -> tuple[str, list[dict[str, str]]]:
    """corpus3.py처럼 v3 요지 JSONL → CSV 행(같은 열 · 같은 번호)으로 바꾼다."""
    raw = path.read_bytes()
    lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
    w.writeheader()
    w.writerows(v3_rows(lines, hashlib.sha256(raw).hexdigest(), start))
    buf.seek(0)
    return key, list(csv.DictReader(buf))


def index(datasets: list) -> bm25.Index:
    chunks, docs = assemble(datasets)
    return bm25.build(chunks, docs, f"floor-eval:{len(chunks)}")


def new_flags(r: dict[str, str]) -> set[str]:
    """새 원문 줄 표시. 2026-11-25 사용자 결정: LH 시방서(lhcs)와 신축 기준(newbuild)은 참고로 쓰고,
    요지만(summary_only, 기관 협의 · 통지 확인 못 함) 줄은 원문으로 인용하지 않고 요지를 쓴 뒤에만 쓴다."""
    out = set()
    if (r.get("source") or "").startswith("LHCS"):
        out.add("lhcs")
    if r.get("rag_reference_usable") == "false":
        out.add("summary_only")
    if (
        r["id"].startswith("FLOOR-HAJA")
        or r.get("review_reason") == "new_build_standard_not_renovation"
    ):
        out.add("newbuild")
    return out


def find(rule, items, allow=None) -> list[list[str]]:
    """조각마다 규칙에 맞는 글 번호(allow가 있으면 그 안에서만)."""
    return [
        [ref for ref, s in items if (allow is None or allow(ref)) and piece_ok(p, s)] for p in rule
    ]


def state(found: list[list[str]]) -> str:
    n = sum(1 for x in found if x)
    return "all" if n == len(found) else ("part" if n else "none")


def one_or_part(one: list[str], found: list[list[str]]) -> str:
    """카드는 한 장이 모든 조각을 덮을 때만 '있음', 여러 장에 흩어져 있으면 '부분'."""
    return "all" if one else ("part" if any(found) else "none")


def card_text(c: cards.AnswerCard) -> str:
    xs = [s.text for s in c.answer] + [s.text for s in (c.caution, c.tip) if s]
    if c.compare:
        xs += [" ".join(r.cells) for r in c.compare.rows]
    return " ".join(xs)


def load_synonyms(path: Path | None) -> list[tuple[list[str], list[str]]]:
    """묶기 표(synonyms.csv)의 (고객 말들, 시방서 · 법령 말들). 문서 말이 없거나 묶지 않는 줄은 뺀다."""
    if not path:
        return []
    _, rows = read_csv(path)
    out = []
    for r in rows:
        cust = [x.strip() for x in (r.get("고객 말") or "").split("·") if x.strip()]
        docs = r.get("시방서 · 법령 말") or r.get("문서 말") or ""
        doc = [x.strip() for x in docs.split("·") if x.strip()]
        if cust and doc and r.get("관계", "").startswith(("같", "넓", "비슷")):
            out.append((cust, doc))
    return out


def expand(q: str, syn: list[tuple[list[str], list[str]]]) -> str:
    """질문에 든 고객 말의 문서 말을 이어 붙인 검색어 하나(없으면 빈 글)."""
    s = nz(q)
    add: list[str] = []
    for cust, doc in syn:
        if any(nz(c) in s for c in cust):
            add += [d for d in doc if d not in add]
    return " ".join(add)[:80]


def top(ix: bm25.Index, rule, q: str, label) -> tuple[bool, list[str]]:
    hits = search3.search(ix, q, trades=["floor"], tags=TAG_TO_CODE, k=K).hits
    return all_ok(rule, [nz(h.text) for h in hits]), [label(h.ref) for h in hits]


def top_bm25(ix: bm25.Index, rule, q: str, extra: str = "") -> bool:
    hits = bm25.search(ix, q, queries=[extra] if extra else (), k=K).hits
    return all_ok(rule, [nz(h.text) for h in hits])


def turn(kb: KB, rule, q: str) -> dict:
    """run_turn 한 번(LLM 끔). 근거 검사 = 보여 준 글(answer.plain) + 답이 인용한 조각 원문.
    조각 문장 답은 원문을 해요체로 풀어 써서 원문 낱말 규칙에 안 걸릴 수 있어 인용 조각도 같이 본다."""
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=TODAY)
    a = asyncio.run(run_turn(q, ctx, kb=kb)).answer
    t = a.trace
    if t.route in ("out_of_scope", "ask_back"):
        how = t.route
    elif t.cards:
        how = "card"
    elif t.chunks:
        how = "extract"
    else:
        how = "unknown" if a.unknown else "template"
    plain = a.plain()
    cited = [nz(kb.ix.by_ref[r].chunk.text) for r in t.chunks if r in kb.ix.by_ref]
    shown = [nz(plain)] + cited if how in ("card", "extract") else []
    return {
        "route": t.route, "trades": t.trades, "policy": t.policy, "how": how,
        "cards": [c.split(":", 1)[-1] for c in t.cards], "chunks": t.chunks[:6],
        "shown_ok": all_ok(rule, shown), "quote_text": any(x in plain for x in QUOTE_TEXT),
        "plain": plain[:600],
    }  # fmt: skip


def pct(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "-"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    ap.add_argument("--new", type=Path, required=True, help="바닥 원문 *_rag.csv 폴더")
    ap.add_argument("--synonyms", type=Path, help="묶기 CSV(고객 말 · 시방서 · 법령 말 · 관계 칸)")
    ap.add_argument("--out", type=Path, required=True, help="문항별 결과 JSON(저장소 밖)")
    a = ap.parse_args()

    qs = [json.loads(x) for x in a.questions.read_text(encoding="utf-8").splitlines() if x.strip()]
    dev_sets = [read_csv(p) for d in DIRS for p in sorted(d.glob("*_rag.csv"))]
    dev_sets += [v3_dataset(p, s, k) for p, s, k in V3 if p.exists()]
    new_sets = [read_csv(p) for p in sorted(a.new.glob("*_rag.csv"))]
    new_rows = {f"{key}/{r['id']}": r for key, rs in new_sets for r in rs}
    syn = load_synonyms(a.synonyms)

    ix_dev, ix_new, ix_comb = index(dev_sets), index(new_sets), index(dev_sets + new_sets)
    cs = cards.default()
    kb_dev, kb_comb = KB(ix=ix_dev, cards=cs), KB(ix=ix_comb, cards=cs)

    def items(ix: bm25.Index) -> list[tuple[str, str]]:
        return [(x.chunk.ref, nz(x.chunk.text)) for x in ix.items]

    it_dev, it_new = items(ix_dev), items(ix_new)
    rid_new = {x.chunk.ref: x.chunk.rid for x in ix_new.items}
    rid_comb = {x.chunk.ref: x.chunk.rid for x in ix_comb.items}
    kind_dev = {x.chunk.ref: x.doc.kind for x in ix_dev.items}
    card_items = [(c.id, nz(card_text(c))) for c in cs.cards]
    maker_only = set()
    for c in cs.cards:
        ks = [r for r in c.cites() if r.startswith("K")]
        if ks and all(kind_dev.get(r) in MAKER for r in ks):
            maker_only.add(c.id)

    def new_id(ref: str) -> str:
        return rid_new[ref].split("/", 1)[1]

    def comb_id(ref: str) -> str:
        rid = rid_comb.get(ref, ref)
        return new_rows[rid]["id"] if rid in new_rows else ref

    def flags_of(ref: str) -> set[str]:
        return new_flags(new_rows[rid_new[ref]])

    def quotable(ref: str) -> bool:
        return "summary_only" not in flags_of(ref)

    out = []
    for q in qs:
        rule, text = compile_rule(q["evidence"]), q["text"]
        dev_f = find(rule, it_dev)
        card_f = find(rule, card_items)
        card_one = [c for c, s in card_items if all(piece_ok(p, s) for p in rule)]
        new_f = find(rule, it_new)
        d_ok, d_top = top(ix_dev, rule, text, lambda r: r)
        n_ok, n_top = top(ix_new, rule, text, new_id)
        c_ok, c_top = top(ix_comb, rule, text, comb_id)
        extra = expand(text, syn)
        row = {
            "id": q["id"], "split": q["split"], "category": q["category"], "expect": q["expect"], "text": text,
            "needs_calc": bool(q.get("needs_calc")),
            "dev": {"has": state(dev_f), "has_no_maker": state(find(rule, it_dev, lambda r: kind_dev.get(r) not in MAKER)),
                    "refs": [x[:5] for x in dev_f], "top5": d_ok, "top5_refs": d_top},
            "card": {"has": one_or_part(card_one, card_f), "one_card": card_one[:5],
                     "has_no_maker_only": one_or_part([c for c in card_one if c not in maker_only],
                                                      find(rule, card_items, lambda r: r not in maker_only))},
            "new": {"has": state(new_f), "has_quotable": state(find(rule, it_new, quotable)),
                    "has_non_reference": state(find(rule, it_new, lambda r: not flags_of(r))),
                    "refs": [[new_id(r) for r in x[:5]] for x in new_f], "top5": n_ok, "top5_refs": n_top,
                    "bm25_top5": top_bm25(ix_new, rule, text), "syn_query": extra,
                    "bm25_top5_syn": top_bm25(ix_new, rule, text, extra) if syn else None},
            "comb": {"top5": c_ok, "top5_refs": c_top},
            "turn_dev": turn(kb_dev, rule, text),
            "turn_comb": turn(kb_comb, rule, text),
        }  # fmt: skip
        out.append(row)

    meta = {
        "questions": a.questions.resolve().relative_to(ROOT).as_posix()
        if a.questions.resolve().is_relative_to(ROOT) else a.questions.name,
        "corpus": {"dev": ix_dev.n, "new": ix_new.n, "dev+new": ix_comb.n, "cards": cs.n,
                   "cards_maker_only": len(maker_only), "synonym_rows": len(syn)},
        "search": f"search3.search(trades=['floor'], k={K}) · bm25.search(k={K}), BM25만(의미 검색 없음)",
        "turn": "turn.run_turn(mode=free), 프로젝트 · 대화 맥락 없음", "today": TODAY.isoformat(),
    }  # fmt: skip
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"meta": meta, "rows": out}, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")  # fmt: skip
    report(out, meta)


def table(rows: list[dict], head: list[str], cols: list) -> None:
    print("| 분류 | 문항 | " + " | ".join(head) + " |")
    print("|" + " --- |" * (len(head) + 2))
    groups = [(c, [r for r in rows if r["category"] == c]) for c in CATS]
    groups += [("**dev 나눔**", [r for r in rows if r["split"] == "dev"]),
               ("**따로 둔 나눔**", [r for r in rows if r["split"] == "heldout"]), ("**전체**", rows)]  # fmt: skip
    for name, rs in groups:
        vals = [pct(sum(1 for r in rs if f(r)), len(rs)) for f in cols]
        print("| " + " | ".join([name, str(len(rs)), *vals]) + " |")
    print()


def report(rows: list[dict], meta: dict) -> None:
    c = meta["corpus"]
    print(f"말뭉치: dev {c['dev']}조각 · 새 원문 {c['new']}조각 · dev+새 원문 {c['dev+new']}조각 · "
          f"카드 {c['cards']}장(제조사 글만 근거 {c['cards_maker_only']}장) · 묶기 표 {c['synonym_rows']}줄\n")  # fmt: skip

    print("### 자료 있음(근거 낱말 규칙의 모든 조각을 찾음)\n")
    table(rows, ["dev 조각", "카드 한 장", "새 원문", "새 원문(요지만 줄 빼고)", "dev 또는 새 원문"], [
        lambda r: r["dev"]["has"] == "all", lambda r: r["card"]["has"] == "all",
        lambda r: r["new"]["has"] == "all", lambda r: r["new"]["has_quotable"] == "all",
        lambda r: r["dev"]["has"] == "all" or r["new"]["has"] == "all"])  # fmt: skip

    print("### 검색 위 5개에 근거가 다 들어옴\n")
    head = ["dev", "새 원문", "dev+새 원문"]
    cols = [lambda r: r["dev"]["top5"], lambda r: r["new"]["top5"], lambda r: r["comb"]["top5"]]
    if c["synonym_rows"]:
        head += ["새 원문(bm25)", "새 원문(bm25 + 묶기 표)"]
        cols += [lambda r: r["new"]["bm25_top5"], lambda r: r["new"]["bm25_top5_syn"]]
    table(rows, head, cols)

    print("### v3 한 턴(LLM 끔, 관문 포함)\n")
    table(rows, ["카드", "조각 문장", "모름", "범위 밖 · 되묻기", "보여 준 글에 근거(dev)", "보여 준 글에 근거(dev+새 원문)",
                 "'업체 견적서에서 확인' 정해 둔 글"], [
        lambda r: r["turn_dev"]["how"] == "card", lambda r: r["turn_dev"]["how"] == "extract",
        lambda r: r["turn_dev"]["how"] in ("unknown", "template"),
        lambda r: r["turn_dev"]["how"] in ("out_of_scope", "ask_back"),
        lambda r: r["turn_dev"]["shown_ok"], lambda r: r["turn_comb"]["shown_ok"],
        lambda r: r["turn_dev"]["quote_text"]])  # fmt: skip

    mark = {"all": "있음", "part": "부분", "none": "없음"}
    ko = {"card": "카드", "extract": "조각", "unknown": "모름", "template": "정해 둔 글만", "out_of_scope": "범위 밖",
          "ask_back": "되묻기"}  # fmt: skip
    calc = [r for r in rows if r["needs_calc"]]
    print(f"### 계산이 필요한 문항(needs_calc {len(calc)}개, 바닥 계산은 아직 없음)\n")
    print("| id | 나눔 | 질문 | 기대 | 설명 몫 근거(dev · 새 원문) | v3 지금 답 |")
    print("|" + " --- |" * 6)
    for r in calc:
        v = r["turn_dev"]
        now = ko[v["how"]] + (" · '업체 견적서에서 확인' 글" if v["quote_text"] else "")
        exp = "계산 값(engine)" if r["expect"] == "engine" else "설명 + 계산 값"
        print(f"| {r['id']} | {r['split']} | {r['text']} | {exp} | "
              f"{mark[r['dev']['has']]} · {mark[r['new']['has']]} | {now} |")  # fmt: skip
    print()

    print("### 문항별\n")
    print(
        "| id | 나눔 | 분류 | 질문 | 기대 | dev | 카드 | 새 원문 | 위 5개(dev · 새 · 합침) | v3 한 턴(dev) |"
    )
    print("|" + " --- |" * 10)
    for r in rows:
        v = r["turn_dev"]
        how = f"{ko[v['how']]}({v['route']}{'/' + ','.join(v['trades']) if v['trades'] else ''})"
        how += (" " + v["cards"][0]) if v["cards"] else ""
        how += " · 근거 맞음" if v["shown_ok"] else ""
        how += " · '업체 견적서에서 확인' 글" if v["quote_text"] else ""
        tops = " · ".join("O" if r[x]["top5"] else "X" for x in ("dev", "new", "comb"))
        nw = mark[r["new"]["has"]]
        if r["new"]["has"] == "all" and r["new"]["has_quotable"] != "all":
            nw += "(요지만 줄 필요)"
        elif r["new"]["has"] == "all" and r["new"]["has_non_reference"] != "all":
            nw += "(참고 자료)"
        exp = {"engine": "계산"}.get(r["expect"], "답") + (
            " · 계산 필요" if r["needs_calc"] and r["expect"] != "engine" else ""
        )
        print(f"| {r['id']} | {r['split']} | {r['category']} | {r['text']} | {exp} | {mark[r['dev']['has']]} | "
              f"{mark[r['card']['has']]} | {nw} | {tops} | {how} |")  # fmt: skip


if __name__ == "__main__":
    main()

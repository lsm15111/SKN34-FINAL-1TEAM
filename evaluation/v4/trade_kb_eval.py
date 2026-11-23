"""공정 지식 검색 기준선(LLM · 임베딩 없음): 전문가 문항마다 지금 검색(공정 범위)의 위 5조각에 정답 사실 낱말(gold)이
드는지 세요.

    cd backend
    uv run python ../evaluation/v4/trade_kb_eval.py check                               # 문항 파일 검사
    uv run python ../evaluation/v4/trade_kb_eval.py prepare --db-name mitjip_test_b1b   # 시험 DB에 지금 자료 넣기
    uv run python ../evaluation/v4/trade_kb_eval.py run --db-name mitjip_test_b1b --out ../evaluation/v4/trade_kb/before.json
    uv run python ../evaluation/v4/trade_kb_eval.py run --source files [--with-expert]   # DB 없이 저장소 파일로

- 문항: sets/trade_dobae.jsonl · trade_mokgong.jsonl(공정마다 60, dev 40 · heldout 20). gold 한 칸은 `|`로 다른 표기를 이어요.
- 검색: 비서 도구(search_knowledge)와 같은 bm25.search(공정 = 도배 · 목공, 임베딩 없음 = 키워드만).
  - top5: k=5 위 다섯 조각(제목 · 절 · 본문)에 gold가 다 드는지(all) · 몇 몫 드는지(recall).
  - tool4: k=8 → on_topic(그 공정 · 공통) → 앞 4개. 비서 모델이 실제로 받는 조각이에요.
- 비교 글: 소문자 · 공백 없앰 · 숫자 쉼표 없앰 · ㎡→m2 · °C→℃ · ㎜/㎝→mm/cm · ×→x · ∼→~ · 따옴표 없앰.
- held-out은 집계만 찍고, 문항별 결과는 --final일 때만 남겨요(조각을 고칠 때 보지 않게).
- DB 이름은 mitjip_test · mitjip_eval로 시작해야 해요(보기용 · 개발 DB에 쓰지 않게). 접속값은 찍지 않아요.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "backend"
SETS = HERE / "sets"
SET_FILES = {"dobae": SETS / "trade_dobae.jsonl", "mokgong": SETS / "trade_mokgong.jsonl"}
OLD_SETS = [
    ROOT / "evaluation/trade/dobae.jsonl",
    ROOT / "evaluation/trade/mokgong.jsonl",
    ROOT / "evaluation/rag/questions.jsonl",
    ROOT / "evaluation/rag/questions_300.jsonl",
    ROOT / "evaluation/rag/questions_sigong.jsonl",
    SETS / "compare.jsonl",
]
TOPICS = (
    "자재", "바탕", "공정 순서", "도구", "품질 기준", "하자 원인", "책임", "검수", "건조", "온습도", "계절",
    "살면서 공사", "안전", "친환경", "견적서 읽기", "계약", "하자보증", "분쟁", "다른 공정과 순서", "뒤 관리",
)  # fmt: skip
KO = {"dobae": "도배", "mokgong": "목공"}
DB_PREFIX = ("mitjip_test", "mitjip_eval")
EXPERT_MIN = 23001  # 공정 지식 묶음 번호(app.knowledge.expert_pack.START)
OVERLAP = 0.5  # 이미 있는 세트 질문과 글자 두 개 묶음 자카드가 이 값 이상이면 겹침


def utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


# ---- 비교 ----
_SUBS = [
    ("㎡", "m2"),
    ("m²", "m2"),
    ("°c", "℃"),
    ("º c", "℃"),
    ("㎜", "mm"),
    ("㎝", "cm"),
    ("㎏", "kg"),
    ("×", "x"),
]


def norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in _SUBS:
        t = t.replace(a, b)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"[∼～〜]", "~", t)
    t = re.sub(r"['\"‘’“”`]", "", t)
    return re.sub(r"\s+", "", t)


def found(gold: list[str], text: str) -> list[bool]:
    t = norm(text)
    return [any(norm(alt) in t for alt in g.split("|") if alt.strip()) for g in gold]


def hit_text(h) -> str:
    return f"{h.title} {h.section} {h.text}"


# ---- 문항 검사 ----
def _grams(t: str) -> set[str]:
    t = re.sub(r"[^0-9a-z가-힣]", "", (t or "").lower())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _jac(a: str, b: str) -> float:
    x, y = _grams(a), _grams(b)
    return len(x & y) / max(1, len(x | y))


def old_questions() -> list[tuple[str, str]]:
    out = []
    for p in OLD_SETS:
        for r in jsonl(p):
            texts = r.get("turns") or [r.get("text", "")]
            out += [(f"{p.name}:{r.get('id')}", t) for t in texts if t]
    return out


def check_sets() -> list[str]:
    problems: list[str] = []
    old = old_questions()
    every: list[dict] = []
    for trade, path in SET_FILES.items():
        rows = jsonl(path)
        every += rows
        prefix = {"dobae": "kbd", "mokgong": "kbm"}[trade]
        ids = [r.get("id") for r in rows]
        if len(set(ids)) != len(ids):
            problems.append(f"{path.name}: id가 겹쳐요")
        per: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            where = f"{path.name} {r.get('id')}"
            if not re.fullmatch(rf"{prefix}-\d{{3}}", str(r.get("id"))):
                problems.append(f"{where}: id 꼴")
            if r.get("trade") != trade:
                problems.append(f"{where}: trade")
            if r.get("split") not in ("dev", "heldout"):
                problems.append(f"{where}: split")
            if r.get("topic") not in TOPICS:
                problems.append(f"{where}: topic")
            gold = r.get("gold") or []
            if not 2 <= len(gold) <= 4 or any(
                not g or any(not 1 <= len(a.strip()) <= 20 for a in g.split("|")) for g in gold
            ):
                problems.append(f"{where}: gold는 2~4개, 표기 하나는 1~20자")
            srcs = r.get("source")
            srcs = srcs if isinstance(srcs, list) else [srcs]
            for s in srcs:
                if not s or not str(s.get("url", "")).startswith(("http://", "https://")):
                    problems.append(f"{where}: source url")
                if not s or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("checked", ""))):
                    problems.append(f"{where}: source checked")
            per[r.get("topic")].append(r.get("split"))
            best = max(((_jac(r.get("text", ""), t), k) for k, t in old), default=(0.0, ""))
            if best[0] >= OVERLAP:
                shown = r["text"] if r.get("split") == "dev" else "(heldout)"
                problems.append(f"{where}: 이미 있는 문항과 겹쳐요 {best[0]:.2f} {best[1]} {shown}")
        if len(rows) != 60 or sum(r.get("split") == "dev" for r in rows) != 40:
            problems.append(f"{path.name}: 60문항 · dev 40 · heldout 20이어야 해요")
        for topic in TOPICS:
            if sorted(per.get(topic, [])) != ["dev", "dev", "heldout"]:
                problems.append(f"{path.name} {topic}: 주제마다 dev 2 · heldout 1")
    for i, a in enumerate(every):
        for b in every[i + 1 :]:
            if _jac(a.get("text", ""), b.get("text", "")) >= OVERLAP:
                problems.append(f"세트 안에서 겹쳐요: {a.get('id')} · {b.get('id')}")
    return problems


# ---- 자료 ----
def repo_datasets(with_expert: bool) -> list[tuple[str, list[dict[str, str]]]]:
    """저장소의 지금 지식 자료(data/processed · data/consult의 *_rag.csv + v3 요지 3묶음) [+ 공정 지식 묶음]."""
    from app.knowledge import expert_pack, v3_csv

    out = []
    for d in (ROOT / "data/processed", ROOT / "data/consult"):
        for p in sorted(d.glob("*_rag.csv")):
            with p.open(encoding="utf-8-sig", newline="") as f:
                out.append((p.stem, list(csv.DictReader(f))))
    for key, path, start in v3_files():
        raw = path.read_bytes()
        lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
        out.append((key, v3_csv.rows(lines, hashlib.sha256(raw).hexdigest(), start)))
    if with_expert:
        data, problems = expert_pack.check()
        if problems:
            raise SystemExit(f"공정 지식 묶음 검사 실패: {problems[0]}")
        out.append((expert_pack.KEY, expert_pack.rows(data)))
    return out


def v3_files():
    from app.knowledge import v3_csv

    base = ROOT / "data/v3/knowledge"
    return [
        ("v3_knowledge_rag", base / "chunks.jsonl", v3_csv.START),
        ("v3_knowledge_iter2_rag", base / "iter2/chunks.jsonl", v3_csv.START2),
        ("v3_knowledge_iter3_rag", base / "iter3/chunks.jsonl", v3_csv.START3),
    ]


def files_index(with_expert: bool):
    from app.knowledge import bm25
    from app.knowledge.sources import assemble

    chunks, docs = assemble(repo_datasets(with_expert))
    return bm25.build(chunks, docs, "files+expert" if with_expert else "files")


# ---- DB ----
def use_db(name: str) -> None:
    """DB 이름 확인 뒤 접속값(.env의 POSTGRES_* · DB_HOST_PORT)으로 DATABASE_URL을 둬요. 값은 찍지 않아요."""
    if not name.startswith(DB_PREFIX):
        raise SystemExit(
            f"DB 이름은 {' · '.join(DB_PREFIX)}로 시작해야 해요(보기용 · 개발 DB 금지)"
        )
    sys.path.insert(0, str(HERE))
    import apienv

    apienv.load_db_env()
    apienv.free_mode()
    user = os.environ.get("POSTGRES_USER") or "mitjip"
    pw = os.environ.get("POSTGRES_PASSWORD") or ""
    port = os.environ.get("DB_HOST_PORT") or "5433"
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{user}:{pw}@127.0.0.1:{port}/{name}"
    os.environ["_KB_ADMIN_DSN"] = f"postgresql://{user}:{pw}@127.0.0.1:{port}/postgres"


async def _recreate(name: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(os.environ["_KB_ADMIN_DSN"])
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def prepare(name: str) -> None:
    """시험 DB를 새로 만들고 지금 지식 자료(공정 지식 묶음 빼고)를 키워드 검색용으로 넣어 켜요."""
    use_db(name)
    asyncio.run(_recreate(name))
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")

    from app import data_ingest as di
    from app.config import settings
    from app.db import SessionLocal, engine
    from app.knowledge import v3_csv
    from app.knowledge.json_csv import EXTRA, REQUIRED

    with tempfile.TemporaryDirectory(prefix="kb-eval-") as tmp:
        paths = [
            p
            for d in ("data/processed", "data/consult")
            for p in sorted((ROOT / d).glob("*_rag.csv"))
        ]
        for key, path, start in v3_files():
            raw = path.read_bytes()
            lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
            out = Path(tmp) / f"{key}.csv"
            with out.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
                w.writeheader()
                w.writerows(v3_csv.rows(lines, hashlib.sha256(raw).hexdigest(), start))
            paths.append(out)
        model, dims = settings.openai_embedding_model, 1536  # data_ingest CLI 기본값과 같게

        async def load():
            datasets = [di.inspect_csv(p) for p in paths]
            for d in datasets:
                await di.load_dataset(SessionLocal, d, model, dims, di.BUILD_PROFILE)
            async with di.execution_lock(engine):
                got = await di.activate_versions(
                    SessionLocal, datasets, model, dims, di.BUILD_PROFILE, require_embeddings=False
                )
            await engine.dispose()
            return got

        for r in asyncio.run(load()):
            print(f"  {r['file']}: {r['rows']}행 · {'활성' if r['status'] else '비활성'}")


async def db_index():
    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from app.knowledge import service

    async with SessionLocal() as s:
        ix = await service.index(s)
        rows = await s.execute(
            text(
                "select dataset_key, version from ref_dataset_versions"
                " where kind = 'knowledge' and status order by dataset_key"
            )
        )
        active = [f"{k}@{v}" for k, v in rows]
    await engine.dispose()
    return ix, active


# ---- 재기 ----
def score(ix, rows: list[dict]) -> list[dict]:
    from app.knowledge import bm25

    out = []
    for r in rows:
        ko = KO[r["trade"]]
        top = bm25.search(ix, r["text"], trade=ko, k=5).hits
        tool = bm25.on_topic(bm25.search(ix, r["text"], trade=ko, k=8).hits, (ko, bm25.COMMON))[:4]
        f5 = found(r["gold"], " ".join(hit_text(h) for h in top))
        f4 = found(r["gold"], " ".join(hit_text(h) for h in tool))
        out.append(
            {
                "id": r["id"],
                "trade": r["trade"],
                "split": r["split"],
                "topic": r["topic"],
                "top5_all": all(f5),
                "top5_recall": round(sum(f5) / len(f5), 3),
                "tool4_all": bool(tool) and all(f4),
                "tool4_recall": round(sum(f4) / len(f4), 3),
                "missing": [g for g, ok in zip(r["gold"], f5, strict=True) if not ok],
                "top5": [h.ref for h in top],
                "tool4": [h.ref for h in tool],
                "expert_in_top5": sum(int(h.ref[1:]) >= EXPERT_MIN for h in top),
            }
        )
    return out


def aggregate(res: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in res:
        for key in (
            f"{r['trade']}/{r['split']}",
            f"{r['trade']}/all",
            f"all/{r['split']}",
            "all/all",
        ):
            groups[key].append(r)

    def agg(rs: list[dict]) -> dict:
        n = len(rs)
        return {
            "n": n,
            "top5_all": round(sum(r["top5_all"] for r in rs) / n, 3),
            "top5_recall": round(sum(r["top5_recall"] for r in rs) / n, 3),
            "tool4_all": round(sum(r["tool4_all"] for r in rs) / n, 3),
            "tool4_recall": round(sum(r["tool4_recall"] for r in rs) / n, 3),
            "expert_share_top5": round(sum(r["expert_in_top5"] for r in rs) / (5 * n), 3),
        }

    return {k: agg(v) for k, v in sorted(groups.items())}


def topic_table(res: list[dict]) -> dict:
    t: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in res:
        if r["split"] == "dev":
            t[f"{r['trade']}/{r['topic']}"][0] += r["top5_all"]
            t[f"{r['trade']}/{r['topic']}"][1] += 1
    return {k: f"{a}/{n}" for k, (a, n) in sorted(t.items())}


def run(args) -> None:
    rows = [r for p in SET_FILES.values() for r in jsonl(p)]
    if not rows:
        raise SystemExit("문항 파일이 없어요")
    if args.source == "db":
        use_db(args.db_name)
        sys.path.insert(0, str(BACKEND))
        ix, active = asyncio.run(db_index())
    else:
        sys.path.insert(0, str(BACKEND))
        ix, active = (
            files_index(args.with_expert),
            ["files" + ("+expert" if args.with_expert else "")],
        )
    res = score(ix, rows)
    agg = aggregate(res)
    shown = res if args.final else [r for r in res if r["split"] == "dev"]
    report = {
        "label": args.label,
        "source": args.source,
        "index_items": ix.n,
        "active": active,
        "final": bool(args.final),
        "aggregate": agg,
        "dev_topics": topic_table(res),
        "questions": shown,
    }
    print(f"색인 {ix.n}조각 · {', '.join(active)}")
    print("갈래 | n | top5 all | top5 recall | tool4 all | tool4 recall | 묶음 몫")
    for k, v in agg.items():
        print(
            f"{k} | {v['n']} | {v['top5_all']:.3f} | {v['top5_recall']:.3f} | {v['tool4_all']:.3f}"
            f" | {v['tool4_recall']:.3f} | {v['expert_share_top5']:.3f}"
        )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
        out.write_text(text, encoding="utf-8", newline="\n")  # 저장소 줄 끝(LF)과 같게
        print(f"저장: {out}")


def main() -> int:
    utf8()
    ap = argparse.ArgumentParser(description="공정 지식 검색 기준선(LLM · 임베딩 없음)")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="문항 파일 검사(꼴 · 나눔 · 겹침)")
    p = sub.add_parser("prepare", help="시험 DB를 새로 만들고 지금 지식 자료를 넣어 켜요")
    p.add_argument("--db-name", required=True)
    r = sub.add_parser("run", help="문항마다 위 5조각에 gold가 드는지 세요")
    r.add_argument("--source", choices=("db", "files"), default="db")
    r.add_argument("--db-name", default="mitjip_test_b1b")
    r.add_argument("--with-expert", action="store_true", help="files일 때 공정 지식 묶음도 넣어요")
    r.add_argument("--final", action="store_true", help="held-out 문항별 결과도 남겨요")
    r.add_argument("--label", default="")
    r.add_argument("--out")
    a = ap.parse_args()
    if a.command == "check":
        problems = check_sets()
        for x in problems:
            print(x)
        print(f"문제 {len(problems)}건")
        return 1 if problems else 0
    sys.path.insert(0, str(BACKEND))
    if a.command == "prepare":
        prepare(a.db_name)
        return 0
    run(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

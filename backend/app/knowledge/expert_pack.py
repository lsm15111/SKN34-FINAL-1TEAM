"""공정 지식 묶음(expert pack): 도배 · 목공 · 공통 전문가 조각(JSONL) → 공통 RAG CSV → 지식 검색 적재.

    cd backend
    uv run python -m app.knowledge.expert_pack check                 # 파일 꼴 검사(DB 없음)
    uv run python -m app.knowledge.expert_pack csv --out DIR         # CSV만 만들기(DB 없음)
    uv run python -m app.knowledge.expert_pack ingest                # 계획만 보기(읽기 전용)
    uv run python -m app.knowledge.expert_pack ingest --execute      # 적재 + 키워드 검색 켜기

- 조각: `app/knowledge/expert/{dobae,mokgong,common}.jsonl`. 한 줄 = id · trade · also · tags · title · body · hints ·
  sources(org · doc · url · section · checked · kind). 입문서(`*_primer.md`)는 공정 에이전트 지시문에 넣는 글이에요.
- 번호(ref): 공정마다 자리를 따로 둬요(도배 K23001~ · 목공 K23401~ · 공통 K23801~). id 끝 번호로 정해져서
  조각을 더하거나 지워도 다른 조각 번호는 그대로예요. 상담 K1~ · 팀 K2001~ · 책 K5001~ · 시공일지 ~K16949 ·
  v3 요지 K20001~K22040과 겹치지 않아요.
- 공정 표시(trades): dobae → 도배, mokgong → 목공, common → 공통. bm25.scope_of가 그대로 읽어요(검색은 바꾸지 않음).
- 적재는 app.data_ingest의 load → verify --keyword-only --activate를 그대로 불러요. 같은 내용이면 같은 CSV가 나와
  있던 버전을 다시 써요(멱등). 내용이 바뀌면 새 버전을 만들어 켜고 옛 버전은 꺼요. 임베딩은 만들지 않아요(유료).
"""

import argparse
import asyncio
import csv
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.knowledge.bm25 import TIER
from app.knowledge.json_csv import EXTRA, REQUIRED

DIR = Path(__file__).resolve().parent / "expert"
KEY = "expert_pack_rag"  # data_ingest의 dataset_key(CSV 파일 이름)
PACK_VERSION = "expert-2026.11.24"
TRADES = ("dobae", "mokgong", "common")
START = {"dobae": 23001, "mokgong": 23401, "common": 23801}
SLOT = 399  # 공정마다 조각 자리 수(id 001~399)
TAG = {"dobae": "도배", "mokgong": "목공", "common": "공통"}
TAGS = (
    "자재", "바탕", "공정 순서", "도구", "품질 기준", "하자 원인", "책임", "검수", "건조", "온습도", "계절",
    "살면서 공사", "안전", "친환경", "견적서 읽기", "계약", "하자보증", "분쟁", "다른 공정과 순서", "뒤 관리", "용어",
)  # fmt: skip
TITLE_MAX, BODY_MAX, HINT_MAX = 40, 500, 80
COLUMNS = REQUIRED + EXTRA + ["tags", "pack", "cites"]
ID = re.compile(r"(dobae|mokgong|common)-(\d{3})")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# 금액: 숫자 뒤 원 · 만 원 · 천 원 · 억 원('3만 원이에요'도), '₩', 한글 금액(삼십만 원 등). '원인 · 원칙 · 원목'처럼
# 원으로 시작하는 낱말은 빼요. 돈은 계산 엔진만 말해요
MONEY = re.compile(
    r"\d[\d,.]*\s*(?:만|천|백|억)?\s*원(?!인|칙|목|형|래|지|료|리|본|활|격|단|칼|색|두)"
    r"|₩|[일이삼사오육칠팔구십백천]+\s*만\s*원"
)


@dataclass(frozen=True)
class Problem:
    where: str
    what: str

    def __str__(self) -> str:
        return f"{self.where}: {self.what}"


def path_of(trade: str, root: Path | None = None) -> Path:
    return (root or DIR) / f"{trade}.jsonl"


def read(trade: str, root: Path | None = None) -> list[dict]:
    p = path_of(trade, root)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def ref_of(chunk_id: str) -> str:
    m = ID.fullmatch(chunk_id)
    if not m:
        raise ValueError(f"조각 id 꼴이 아니에요: {chunk_id}")
    return f"K{START[m.group(1)] + int(m.group(2)) - 1}"


def trades_of(c: dict) -> list[str]:
    """조각의 공정 낱말(검색 색인의 trades). 첫 낱말이 대표 공정이에요."""
    return [TAG[c["trade"]], *(TAG[t] for t in c.get("also") or [] if t != c["trade"])]


def check_chunk(c: dict, trade: str, where: str) -> list[Problem]:
    out: list[Problem] = []

    def bad(what: str) -> None:
        out.append(Problem(where, what))

    m = ID.fullmatch(str(c.get("id", "")))
    if not m or m.group(1) != trade:
        bad(f"id는 {trade}-NNN 꼴이어야 해요")
    elif not 1 <= int(m.group(2)) <= SLOT:
        bad(f"id 번호는 001~{SLOT:03d}이에요")
    if c.get("trade") != trade:
        bad(f"trade는 {trade}이어야 해요(파일과 같게)")
    also = c.get("also") or []
    if not isinstance(also, list) or any(t not in ("dobae", "mokgong") or t == trade for t in also):
        bad("also는 dobae · mokgong 중 자기 공정 말고만 써요")
    if trade == "common" and also:
        bad("공통 조각은 also를 비워요")
    tags = c.get("tags") or []
    if not isinstance(tags, list) or not 1 <= len(tags) <= 3 or any(t not in TAGS for t in tags):
        bad("tags는 정한 주제 낱말 1~3개예요")
    title, body = str(c.get("title") or ""), str(c.get("body") or "")
    if not 0 < len(title) <= TITLE_MAX:
        bad(f"title은 1~{TITLE_MAX}자예요")
    if not 0 < len(body) <= BODY_MAX:
        bad(f"body는 1~{BODY_MAX}자예요")
    for text in (title, body, *map(str, c.get("hints") or [])):
        if MONEY.search(text):
            bad("금액 숫자를 넣지 않아요")
            break
    hints = c.get("hints") or []
    if (
        not isinstance(hints, list)
        or len(hints) > 3
        or any(not 0 < len(str(h)) <= HINT_MAX for h in hints)
    ):
        bad(f"hints는 {HINT_MAX}자 안쪽 0~3개예요")
    sources = c.get("sources") or []
    if not isinstance(sources, list) or not 1 <= len(sources) <= 4:
        bad("sources는 1~4개예요")
        sources = []
    for i, s in enumerate(sources, 1):
        if not all(str(s.get(k) or "").strip() for k in ("org", "doc", "section")):
            bad(f"출처 {i}: org · doc · section이 비었어요")
        if not str(s.get("url") or "").startswith(("http://", "https://")):
            bad(f"출처 {i}: url은 http(s) 주소예요")
        if not DAY.fullmatch(str(s.get("checked") or "")):
            bad(f"출처 {i}: checked는 YYYY-MM-DD예요")
        if s.get("kind") not in TIER:
            bad(f"출처 {i}: kind는 {', '.join(TIER)} 중 하나예요")
    return out


def check(root: Path | None = None) -> tuple[dict[str, list[dict]], list[Problem]]:
    """세 파일을 읽고 꼴을 검사해요. (공정별 조각, 문제 목록)"""
    data: dict[str, list[dict]] = {}
    problems: list[Problem] = []
    seen: set[str] = set()
    for trade in TRADES:
        try:
            rows = read(trade, root)
        except json.JSONDecodeError as e:
            problems.append(Problem(f"{trade}.jsonl", f"JSON이 아니에요({e.lineno}번째 줄)"))
            rows = []
        data[trade] = rows
        for n, c in enumerate(rows, 1):
            where = f"{trade}.jsonl:{n} {c.get('id', '?')}"
            problems += check_chunk(c, trade, where)
            if c.get("id") in seen:
                problems.append(Problem(where, "id가 겹쳐요"))
            seen.add(c.get("id"))
    if not any(data.values()):
        problems.append(Problem(str(root or DIR), "조각 파일이 없어요"))
    return data, problems


def _url(url: str) -> str:
    """화면 링크로 쓸 주소. 문서 첫 화면뿐인 주소(KCS · LH 시방서 등)는 비워요(v3_csv와 같은 규칙)."""
    parts = urlsplit(url)
    return "" if parts.path in ("", "/") and not parts.query else url


def rows(data: dict[str, list[dict]], root: Path | None = None) -> list[dict[str, str]]:
    """조각 → 공통 RAG CSV 행(번호 순). source_sha256은 조각 파일(줄 끝 LF로 맞춤)의 SHA-256이에요."""
    out = []
    for trade in TRADES:
        p = path_of(trade, root)
        raw = p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b""
        sha = hashlib.sha256(raw).hexdigest()
        for c in data.get(trade) or []:
            first = c["sources"][0]
            trades = ";".join(trades_of(c))
            out.append(
                {
                    "id": c["id"],
                    "source": first["doc"],
                    "source_sha256": sha,
                    "effective_date": "",
                    "content": c["body"],
                    "section": " · ".join(x for x in (c["title"], first.get("section") or "") if x),
                    "page": "1",
                    "category": c["tags"][0],
                    "trade": trades,
                    "source_org": first["org"],
                    "source_url": _url(first["url"]),
                    "source_type": first["kind"],
                    "ref": ref_of(c["id"]),
                    "doc": f"expert:{c['id']}",
                    "trades": trades,
                    "hints": json.dumps(c.get("hints") or [], ensure_ascii=False),
                    "rel": "high",
                    "doc_date": first["checked"],
                    "page_known": "false",
                    "tags": ";".join(c["tags"]),
                    "pack": PACK_VERSION,
                    "cites": json.dumps(c["sources"], ensure_ascii=False),
                }
            )
    out.sort(key=lambda r: int(r["ref"][1:]))
    return out


def write_csv(out_dir: Path, root: Path | None = None) -> Path:
    """검사를 통과하면 out_dir/expert_pack_rag.csv를 써요. 같은 내용이면 같은 바이트예요(멱등 적재의 바탕)."""
    data, problems = check(root)
    if problems:
        raise ValueError(f"지식 조각 검사 실패 {len(problems)}건: {problems[0]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{KEY}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows(data, root))
    return path


def summary(data: dict[str, list[dict]]) -> str:
    n = {t: len(data.get(t) or []) for t in TRADES}
    return f"조각 {sum(n.values())}개(도배 {n['dobae']} · 목공 {n['mokgong']} · 공통 {n['common']}), 판 {PACK_VERSION}"


async def ingest(out_dir: Path, *, execute: bool, as_json: bool = False) -> None:
    """data_ingest 길 그대로: 계획(읽기 전용) 또는 load --execute → verify --keyword-only --activate."""
    from app import data_ingest

    base = ["--directory", str(out_dir), "--dataset", KEY]
    if as_json:
        base.append("--json")
    if not execute:
        await data_ingest.run(data_ingest.parser().parse_args(["plan", *base]))
        return
    await data_ingest.run(data_ingest.parser().parse_args(["load", *base, "--execute"]))
    await data_ingest.run(
        data_ingest.parser().parse_args(["verify", *base, "--keyword-only", "--activate"])
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="공정 지식 묶음: 검사 · CSV · 적재(키워드 검색)")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="조각 파일 꼴 검사(DB 없음)")
    p_csv = sub.add_parser("csv", help="공통 RAG CSV 만들기(DB 없음)")
    p_csv.add_argument("--out", type=Path, required=True)
    p_in = sub.add_parser("ingest", help="data_ingest로 적재(기본은 계획만)")
    p_in.add_argument("--execute", action="store_true", help="DB에 쓰고 키워드 검색에 켜요")
    p_in.add_argument("--out", type=Path, help="CSV를 둘 폴더(기본: 임시 폴더)")
    p_in.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "check":
        data, problems = check()
        for p in problems:
            print(p)
        print(f"{summary(data)} · 문제 {len(problems)}건")
        return 1 if problems else 0
    from sqlalchemy.exc import SQLAlchemyError

    try:
        if a.command == "csv":
            path = write_csv(a.out)
            print(f"{path} · {summary(check()[0])}")
            return 0
        if a.out:
            path = write_csv(a.out)
            asyncio.run(ingest(path.parent, execute=a.execute, as_json=a.json))
        else:
            with tempfile.TemporaryDirectory(prefix="expert-pack-") as tmp:
                asyncio.run(ingest(write_csv(Path(tmp)).parent, execute=a.execute, as_json=a.json))
    except (ValueError, OSError, csv.Error, SQLAlchemyError) as e:
        # data_ingest.main과 같이 DB · 파일 오류 원문(접속 정보가 섞일 수 있음)은 찍지 않아요
        message = str(e) if isinstance(e, ValueError) else "파일 · DB 연결 · 스키마 오류"
        print(f"실패: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

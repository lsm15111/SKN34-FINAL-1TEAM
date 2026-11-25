"""데이터 담당 v3 지식 요지(data/v3/knowledge/chunks.jsonl) → 공통 RAG CSV(적재 · 평가용). DB를 모른다.

    python -m app.knowledge.v3_csv ../data/v3/knowledge/chunks.jsonl ../evaluation/v3/.cache/v3_knowledge_rag.csv

- 번호(ref): 파일 줄 순서대로 K20001부터(개선 2회차 묶음 `iter2/chunks.jsonl`은 K21001부터). 다른 자료와 안 겹치는 자리예요:
  상담 K1~ · 팀 K2001~ · 책 K5001~ · 시공일지 K6000 + 쪽×50 + 순번(218쪽 → K16949까지, data/sigong_ilji/SPEC.md).
  (처음 정한 K7001~은 시공일지 K7154 등과 겹쳐서 옮겼어요.) 번호 칸은 다섯 자리까지(bm25.REF)라 K99999가 끝이에요.
  새 조각은 파일 끝에 더해요. 중간에 넣으면 뒤 번호가 밀려 카드 인용이 틀어져요(cards_check가 잡아요).
- 출처 주소: http(s) 주소만 남겨요. `repo:`처럼 저장소 안 경로와, 문서 첫 화면 주소뿐인 품셈 · LH 시방서 · KCS(doc_key
  pumsem · lhcs · kcs)는 비워서 화면에 링크로 보이지 않게 해요(출처 이름만).
- 본문: 요지(summary). 데이터 담당이 해요체로 새로 쓴 글이라 화면에 보여도 돼요(원문 아님).
- 절: 제목 · 조항. 예시 질문(hints): question_hints(개선 2회차는 answers). 공정 표시: trade + also를 조각 공정 낱말로.
- 출처 종류(source_type): 문서 이름 · 라이선스로 정해요(고시 · 법령 · 시방서 · 품셈 · 표준계약서 · 소비자원 · 공공누리).
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.knowledge.json_csv import EXTRA, REQUIRED

START = 20001
START2 = 21001  # 개선 2회차(iter2) 조각. v3 첫 묶음(K20001~K20190)과 안 겹쳐요
DOC_HOME = ("pumsem", "lhcs", "kcs")  # 주소가 문서 첫 화면뿐이라 링크로 안 보이는 출처
SIGONG_MAX = 6000 + 218 * 50 + 49  # 시공일지 마지막 번호(SPEC.md 규칙)
TAG = {
    "dobae": "도배", "mokgong": "목공", "floor": "바닥재", "tile": "타일", "bath": "욕실",
    "kitchen": "주방", "paint": "도장", "film": "필름", "electric": "조명", "window": "창호",
    "demolition": "철거", "plumbing": "설비", "common": "공통",
}  # fmt: skip


def kind_of(name: str, license_: str) -> str:
    if "KCS" in name:
        return "kcs"
    if "품셈" in name:
        return "pumsem"
    if "표준계약서" in name or "표준약관" in name:
        return "standard_contract"
    if "소비자분쟁해결기준" in name or "고시" in name or ("기준" in name and "국토" in name):
        return "gov_notice"
    if any(
        w in name for w in ("(법률", "시행령", "시행규칙", "준칙", "(대통령령", "(국토교통부령")
    ):
        return "law"
    if "생활법령정보" in name:
        return "gov_qa"
    if "주의보" in name or "소비자원" in name or "피해" in name:
        return "consumer_agency"
    if license_.startswith("공공저작물"):
        return "law"
    if license_.startswith("공공누리"):
        return "gov_guide"
    return "guide"


def start_for(path: Path) -> int:
    """파일 자리로 첫 번호를 정해요: data/v3/knowledge/iter2/… → START2, 그 밖 → START."""
    return START2 if path.parent.name == "iter2" else START


def _url(c: dict) -> str:
    url = c.get("source_url") or ""
    if not url.startswith(("http://", "https://")):
        return ""
    return "" if str(c.get("doc_key") or "").startswith(DOC_HOME) else url


def rows(lines: list[dict], sha: str, start: int = START) -> list[dict[str, str]]:
    out = []
    for i, c in enumerate(lines):
        tags = [TAG.get(c.get("trade") or "common", "공통")]
        tags += [TAG[t] for t in c.get("also") or [] if t in TAG and TAG[t] not in tags]
        day = c.get("effective_date") or ""
        name = c.get("source_name") or ""
        sec = " · ".join(x for x in (c.get("title") or "", c.get("clause") or "") if x)
        out.append(
            {
                "id": c["id"],
                "source": name,
                "source_sha256": sha,
                "effective_date": day if len(day) == 10 else "",
                "content": c["summary"],
                "section": sec,
                "page": "1",
                "category": c.get("topic") or "",
                "trade": ";".join(tags),
                "source_org": "",
                "source_url": _url(c),
                "source_type": kind_of(name, c.get("license") or ""),
                "ref": f"K{start + i}",
                "doc": f"v3:{c.get('doc_key') or c['id']}",
                "trades": ";".join(tags),
                "hints": json.dumps(
                    c.get("question_hints") or c.get("answers") or [], ensure_ascii=False
                ),
                "rel": "high",
                "doc_date": day,
                "page_known": "false",
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="v3 지식 요지 JSONL → 공통 RAG CSV")
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    raw = a.src.read_bytes()
    lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
    out = rows(lines, hashlib.sha256(raw).hexdigest(), start_for(a.src))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"{a.out.name}: {len(out)}행 (K{start_for(a.src)}~K{start_for(a.src) + len(out) - 1})")


if __name__ == "__main__":
    main()

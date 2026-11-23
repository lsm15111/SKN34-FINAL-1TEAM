"""고객 질문 10개 재현(LLM 모드, 유료, 2026-11-23 사용자 '이런 질문들에 답변이 안돼 확인해봐').

- 시험 DB(mitjip_eval_*)에 18평 · 실크 · 빈 집 공사를 만들고, 한 대화에서 질문을 차례로 물어요.
  --basis exclusive면 전용 18평(59.5㎡, 공급 21.6평 · 5품: 사용자가 본 수량)이에요.
- --knowledge db면 도커 미리보기 DB(mitjip_v4)의 지식 판 · 조각(임베딩 포함)을 시험 DB로 옮기고 의미 검색을 켜요
  (도커와 같은 조건, 읽기만). 기본 repo는 저장소 색인 · 임베딩 끔이에요.
- 턴마다 답 글 · 카드 종류 · 부른 도구와 입력 · 모드 · 뺀 문장 까닭(trace.dropped) · 비용을 남겨요(시험 대화라 글을 남겨요).
- 공급자는 환경변수대로예요(eval-live-openai.sh면 OpenAI, eval-live.sh면 Claude). --max-usd를 넘기 전에 멈춰요.

사용(EVAL_BACKEND로 이 작업 폴더 backend):
  uv run python ../evaluation/v4/qa10_live.py --db mitjip_eval_qa10 --redis 11 --out <폴더> [--knowledge db]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import apienv

QUESTIONS = [
    "견적서 왜 이렇게 비싸?",
    "업체 견적이랑 많이 차이나?",
    "실크 벽지는 어떤걸 쓴거야?",
    "AS기간은 보통 어떻게돼?",
    "인건비 5품은 어떻게 나온거야?",
    "우리집은 18평인데 왜 수량이 21.6평 72평이 나오는거야?",
    "퍼티 작업은 꼭 해야하는 거야?",
    "견적이 너무 비싼데 줄일 수 있는 방법은 없어? 실크벽지로 하고싶어",
    "결제는 카드로 가능한거야? 현금으로만 해야하는거야?",
    "작업자 식대를 왜 내가 내줘야하는거야?",
]
HOME18 = {
    "sido": "seoul", "sgg": "노원구", "emd": "상계동", "area_m2": "59.5",
    "area_basis": "supply", "occupied": False, "grade": "basic",
}  # fmt: skip
DB_BOX = os.environ.get("EVAL_DB_CONTAINER", "skn34-final-db-1")  # 도커 DB 컨테이너
KNOW_FROM = "mitjip_v4"  # 도커 미리보기 DB(지식 판을 읽기만 해요)


def copy_knowledge(db: str) -> None:
    """지식 판 · 조각(임베딩 포함)을 미리보기 DB에서 시험 DB로 옮겨요. 조각 확인 trigger가 스키마 없이 표 이름을 써서
    pg_dump의 search_path 비우기 줄은 빼요."""
    cmd = (
        f"pg_dump -U mitjip --data-only -t ref_dataset_versions -t rag_chunks {KNOW_FROM} "
        "| sed \"/set_config('search_path'/d\" "
        f"| psql -U mitjip -q -v ON_ERROR_STOP=1 -d {db}"
    )
    r = subprocess.run(
        ["docker", "exec", DB_BOX, "sh", "-c", cmd],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )  # fmt: skip
    if r.returncode != 0:
        raise SystemExit(f"지식 옮기기 실패: {(r.stderr or r.stdout)[-300:]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="mitjip_eval_qa10")
    ap.add_argument("--redis", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", choices=("openai", "anthropic"), default="openai")
    ap.add_argument("--max-usd", type=float, default=0.5)
    ap.add_argument("--only", default="", help="물을 번호(1부터, 쉼표)")
    ap.add_argument("--knowledge", choices=("repo", "db"), default="repo")
    ap.add_argument("--basis", choices=("supply", "exclusive"), default="supply")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    apienv.load_db_env()
    apienv.openai_mode() if a.provider == "openai" else apienv.live_mode()
    app = apienv.App(a.db, a.redis, knowledge=a.knowledge).boot()
    if a.knowledge == "db":
        copy_knowledge(a.db)
    from tests.helpers import signup
    from tests.test_v4_assistant_turns import ask, events

    signup(app.api, f"qa10-{uuid.uuid4().hex[:6]}@mitjip.test")
    r = app.api.post("/projects", json=HOME18 | {"area_basis": a.basis})
    assert r.status_code == 201, r.text[:300]
    pid = r.json()["id"]
    board = app.api.get("/assistant/board", params={"project_id": pid}).json()
    std = app.api.get(f"/projects/{pid}/standard")
    rows: list[dict] = []
    only = {int(x) for x in a.only.split(",") if x}

    def spent() -> float:
        return sum(int(x["cost_micros"]) for x in app.query("select cost_micros from llm_usage")) / 1e6

    for n, q in enumerate(QUESTIONS, 1):
        if only and n not in only:
            continue
        if spent() > a.max_usd - 0.05:
            print("상한에 가까워 멈춰요", spent())
            break
        t0 = time.monotonic()
        res = ask(app.api, pid, q)
        ev = events(res.text) if res.status_code == 200 else []
        turn = ev[0][1].get("turn_id") if ev else None
        done = ev[-1][1] if ev else {}
        t = app.query("select mode, tool_calls, trace, cost_micros from assistant_turns where id = $1", uuid.UUID(turn))[0] if turn else {}
        trace = json.loads(t["trace"]) if t and isinstance(t.get("trace"), str) else (t.get("trace") if t else None)
        calls = app.tap.take(turn) if turn else []
        row = {
            "n": n,
            "ask": q,
            "status": res.status_code,
            "mode": done.get("mode"),
            "said": "".join(d.get("text", "") for e, d, _ in ev if e == "token"),
            "cards": [d.get("kind") for e, d, _ in ev if e == "card"],
            "card_data": {d.get("kind"): d.get("data") for e, d, _ in ev if e == "card"},
            "tools": [x["name"] for x in calls],
            "args": [x["args"] for x in calls],
            "dropped": (trace or {}).get("dropped"),
            "stop": (trace or {}).get("stop"),
            "cost_usd": round(int(t.get("cost_micros") or 0) / 1e6, 4) if t else None,
            "seconds": round(time.monotonic() - t0, 1),
        }
        rows.append(row)
        print(f"\n[{n}] {q}\n  모드 {row['mode']} · 도구 {row['tools']} {row['args']} · 카드 {row['cards']} · 뺌 {row['dropped']} · ${row['cost_usd']} · {row['seconds']}s")
        print("  " + row["said"].replace("\n", "\n  "))
    (out / "qa10.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "knowledge": a.knowledge,
                "basis": a.basis,
                "board": board,
                "standard": std.json() if std.status_code == 200 else std.status_code,
                "rows": rows,
                "spent_usd": round(spent(), 4),
            },
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    print("\n합계 $", round(spent(), 4))
    app.close()


if __name__ == "__main__":
    main()

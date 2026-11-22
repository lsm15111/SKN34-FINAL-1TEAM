"""조사 진행 기록 · 결과 항목 · 제조사 그림 실제 실행(LLM 모드, 유료). 조사 담당만 실제 Claude로 돌려요.

- 시험 DB(mitjip_eval_*)에 고객 · 공사를 만들고, 비서 턴은 대본(무료)으로 start_research를 불러 조사를 맡긴 뒤
  조사 담당(research.run)만 실제 Claude(웹 검색 · 가져오기)로 돌려요. 그림 찾기(linkimage)도 실제로 해요.
- --init: DB를 새로 만들고 Alembic head까지 올린 뒤 끝내요(화면 서버를 먼저 띄우려고). --keep: DB를 지우지 않고 써요.
- 조사를 시작할 때마다 <out>/now.json(공사 id · 조사 id · 세션 값)을 써요. 화면 찍기가 그 값으로 진행 카드를 봐요.
  세션 값은 이 시험 DB 것이고 출력 폴더(scratchpad)에만 둬요.
- 지출은 조사 줄의 cost_micros 합으로 세고 --max-usd를 넘기 전에 멈춰요.

사용(eval-live.sh가 키 · LLM_LIVE=true를 넣어요, EVAL_BACKEND로 이 작업 폴더 backend):
  uv run python ../evaluation/v4/research_trail_live.py --db mitjip_eval_research --redis 11 --out <폴더> --init
  uv run python ../evaluation/v4/research_trail_live.py --db mitjip_eval_research --redis 11 --out <폴더> --keep
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import apienv

CASES = [
    ("M1", "materials", "많이 고르는 실크벽지 질감 · 특징(사진 볼 수 있는 제품)"),
    ("M2", "materials", "아이 방에 어울리는 밝은 색 · 잔잔한 무늬 벽지 디자인"),
    ("M3", "materials", "거실 베이지 톤 실크벽지 디자인"),
    ("M4", "materials", "긁힘 · 얼룩에 강한 실크벽지 라인"),
    ("G1", "general", "도배 전에 퍼티 작업이 필요한 경우"),
    ("O1", "outside_vendors", "노원구 아파트 도배 업체"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="mitjip_eval_research")
    ap.add_argument("--redis", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--max-usd", type=float, default=1.2)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    apienv.load_db_env()
    if a.init:
        apienv.free_mode()
        app = apienv.App(a.db, a.redis).boot()
        app.close()
        print("DB 준비", a.db)
        return
    apienv.live_mode()
    app = apienv.App(a.db, a.redis)
    if a.keep:  # DB를 지우지 않고 붙어요(화면 서버가 이미 이 DB를 읽고 있어요)
        _boot_keep(app)
    else:
        app.boot()
    from app.agent import llm
    from app.assistant import research, weblinks
    from app.assistant.models import AssistantResearch
    from app.db import SessionLocal
    from tests.test_v4_assistant_turns import ask, home

    # '찾은 만큼'(partial) 까닭: 결과를 만들 때 이른 끝 까닭 · 웹 도구 오류 코드 · 거르는 코드 실패를 남겨요
    why: dict[str, dict] = {}
    real_build = research.build_result

    def build(run_, notes, prompt, today):
        blocks = [b for _, b in run_.blocks]
        codes = [  # 거르는 코드 실행마다 성공(True) · 실패(False), 나온 순서
            weblinks.code_failed([b]) is False
            for b in blocks
            if b.get("type") in ("code_execution_tool_result", "bash_code_execution_tool_result")
        ]
        why[str(run_.research_id)] = {
            "reason": run_.reason,
            "tool_errors": weblinks.tool_errors(blocks),
            "code_failed_last": weblinks.code_failed(blocks),
            "code_runs": codes,
        }
        return real_build(run_, notes, prompt, today)

    research.build_result = build

    only = {x for x in a.only.split(",") if x}
    spent = 0
    rows: list[dict] = []
    for cid, kind, goal in CASES:
        if only and cid not in only:
            continue
        if spent / 1_000_000 > a.max_usd - 0.16:
            print("상한에 가까워 멈춰요", spent / 1_000_000)
            break
        email = f"rt-{cid.lower()}-{uuid.uuid4().hex[:6]}@mitjip.test"
        token, pid = home(app.api, email)
        llm.set_claude_script(
            [
                {
                    "tool_calls": [
                        {
                            "id": "t1",
                            "name": "start_research",
                            "input": {"kind": kind, "goal": goal},
                        }
                    ]
                },
                {"text": "알아볼게요. 잠깐(1분 안팎) 걸려요."},
            ]
        )
        r = ask(app.api, pid, goal + " 찾아 줘")
        assert r.status_code == 200, r.text[:300]
        llm.clear_stubs()
        rid = app.query(
            "select id from assistant_research where project_id = $1 order by created_at desc limit 1",
            uuid.UUID(pid),
        )[0]["id"]
        (out / "now.json").write_text(
            json.dumps({"case": cid, "pid": pid, "rid": str(rid), "token": token}), encoding="utf-8"
        )
        t0 = time.monotonic()
        status = app.call(research.run, rid)
        took = round(time.monotonic() - t0, 1)

        async def load(rid=rid):
            async with SessionLocal() as s:
                return await s.get(AssistantResearch, rid)

        row = app.call(load)
        data = research.data_of(row, "result")
        spent += int(row.cost_micros or 0)
        got = {
            "case": cid,
            "kind": kind,
            "goal": goal,
            "pid": pid,
            "rid": str(rid),
            "status": status,
            "seconds": took,
            "cost_usd": round((row.cost_micros or 0) / 1_000_000, 4),
            "calls": row.calls,
            "summary": data.summary,
            "items": [x.model_dump(mode="json") for x in data.items],
            "links": [x.model_dump(mode="json") for x in data.links],
            "trail": [x.model_dump(mode="json") for x in data.trail],
            "partial": data.partial,
            "why_partial": why.get(str(rid)),
        }
        rows.append(got)
        (out / f"{cid}.json").write_text(
            json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (out / f"{cid}.session").write_text(token, encoding="utf-8")
        pics = sum(1 for x in got["items"] if x.get("image"))
        print(
            f"{cid} {status} {took}s ${got['cost_usd']} 기록 {len(got['trail'])}줄 "
            f"항목 {len(got['items'])}(그림 {pics}) 링크 {len(got['links'])}"
        )
    (out / "now.json").unlink(missing_ok=True)
    (out / "summary.json").write_text(
        json.dumps({"spent_usd": round(spent / 1_000_000, 4), "cases": [r["case"] for r in rows]}),
        encoding="utf-8",
    )
    print("합계 $", round(spent / 1_000_000, 4))
    app.close()


def _boot_keep(app) -> None:
    """App.boot에서 DB 새로 만들기만 뺀 것(Alembic head는 확인)."""
    import os

    from alembic import command
    from alembic.config import Config

    port = os.environ.get("REDIS_HOST_PORT") or "6379"
    os.environ["TEST_DB_NAME"] = app.db_name
    os.environ["TEST_REDIS_URL"] = f"redis://127.0.0.1:{port}/{app.redis_db}"
    for p in (str(apienv.TESTS), str(apienv.BACKEND)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import tests.conftest as cf

    app.cf = cf
    cfg = Config()
    cfg.set_main_option("script_location", str(apienv.BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    app._tc = TestClient(fastapi_app)
    app.api = app._tc.__enter__()
    app._patch_knowledge()
    app.tap.install()


if __name__ == "__main__":
    main()

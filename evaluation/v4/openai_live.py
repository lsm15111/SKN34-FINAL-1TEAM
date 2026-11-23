"""v4 OpenAI 길 실제 확인(LLM 모드, 유료, docs/v4/10-openai.md). 비서 턴 · 조사 · 기억 · 짧은 문장을 OpenAI로 돌려요.

- 시험 DB(mitjip_eval_*)에 고객 · 공사를 만들고 실제 비서 턴(대본 없음)을 몇 번 돌린 뒤, 조사(research.run)를
  실제 OpenAI 웹 검색으로 돌려요(자재 · 믿집 밖 업체). 기억 뽑기(memory.extract)와 캐시 토큰 셈(같은 긴 요청 두 번)도
  봐요. 그림 찾기(linkimage)는 실제로 해요.
- 지출은 llm_usage cost_micros 합으로 세고 단계마다 --max-usd를 넘기 전에 멈춰요.
- 결과는 <out>/openai_live.json에 써요(세션 값 · 키는 쓰지 않아요).

사용(eval-live-openai.sh가 OpenAI 키 · LLM_LIVE=true · LLM_PROVIDER=openai를 넣어요, EVAL_BACKEND로 이 작업 폴더 backend):
  uv run python ../evaluation/v4/openai_live.py --db mitjip_eval_openai --redis 11 --out <폴더>
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

TURNS = [
    "오늘 뭐 하면 돼요?",
    "실크벽지랑 합지는 뭐가 달라요?",
    "많이 고르는 실크벽지 제품 알아봐 줘",
]
OUTSIDE = ("outside_vendors", "노원구 아파트 도배 업체")
MEMORY_TEXT = "거실은 밝은 베이지 톤이 좋아요. 아이 방은 제가 직접 칠해 볼 생각이에요."
# 캐시 셈 확인용 긴 지시문(캐시는 1,024토큰부터라 그보다 길게)
PROBE_RULES = "너는 믿집 확인 담당이야. 고객 말을 한 문장으로 확인해. 숫자는 쓰지 마. " * 120


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="mitjip_eval_openai")
    ap.add_argument("--redis", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usd", type=float, default=0.6)
    ap.add_argument("--skip", default="", help="건너뛸 단계(probe,turns,research,memory)")
    ap.add_argument("--cases", default="materials,outside", help="조사 종류(materials,outside)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    skip = {x for x in a.skip.split(",") if x}
    apienv.load_db_env()
    apienv.openai_mode()
    app = apienv.App(a.db, a.redis).boot()
    from pydantic import BaseModel

    from app.agent import llm
    from app.assistant import memory, research, weblinks
    from app.assistant.models import AssistantResearch
    from app.db import SessionLocal
    from tests.test_v4_assistant_turns import ask, events, home

    raw: list[dict] = []  # 응답 usage 원본(모델 · 토큰), 캐시 셈 확인용
    real_usage = llm._oa_usage

    def tap(resp, web):
        u = getattr(resp, "usage", None)
        dump = u.model_dump() if hasattr(u, "model_dump") else None
        raw.append({"model": getattr(resp, "model", None), "usage": dump, "web": web})
        return real_usage(resp, web)

    llm._oa_usage = tap

    def spent() -> float:
        return (
            sum(int(r["cost_micros"]) for r in app.query("select cost_micros from llm_usage")) / 1e6
        )

    def room(step: str) -> bool:
        if spent() > a.max_usd - 0.12:
            print(f"상한에 가까워 '{step}' 단계부터 멈춰요 (${spent():.4f})")
            return False
        return True

    report: dict = {"steps": {}}
    # 조사 결과를 만들 때 끝 글 · 찾은 주소를 남겨요(링크가 왜 남거나 빠졌는지 보려고)
    seen: dict[str, dict] = {}
    real_build = research.build_result

    def build(run_, notes, prompt, today):
        blocks = [b for _, b in run_.blocks]
        seen[str(run_.research_id)] = {
            "final_text": run_.final_text,
            "hit_urls": [h.url for h in weblinks.hits(blocks)],
        }
        return real_build(run_, notes, prompt, today)

    research.build_result = build

    class Echo(BaseModel):
        text: str

    if "probe" not in skip and room("probe"):
        got = []
        for _ in range(2):
            got.append(
                app.call(llm.claude_json, "nudge", Echo, PROBE_RULES, "벽지 색을 골랐어요.").text
            )
        report["steps"]["probe"] = {"answers": got, "usage": raw[-2:]}
        print("캐시 셈", json.dumps(raw[-2:], ensure_ascii=False))

    pid = None
    if "turns" not in skip and room("turns"):
        _, pid = home(app.api, f"oa-{uuid.uuid4().hex[:6]}@mitjip.test")
        rows = []
        for text in TURNS:
            if not room("turns"):
                break
            t0 = time.monotonic()
            r = ask(app.api, pid, text)
            ev = events(r.text)
            done = ev[-1][1] if ev else {}
            turn = ev[0][1].get("turn_id") if ev else None
            said = "".join(d.get("text", "") for e, d, _ in ev if e == "token")
            row = {
                "ask": text,
                "status": r.status_code,
                "mode": done.get("mode"),
                "said": said,
                "cards": [d.get("kind") for e, d, _ in ev if e == "card"],
                "tools": [x["name"] for x in app.tap.take(turn)],
                "seconds": round(time.monotonic() - t0, 1),
            }
            rows.append(row)
            print(
                f"턴 {text} → {row['mode']} {row['seconds']}s 도구 {row['tools']} 카드 {row['cards']}\n  {said}"
            )
        report["steps"]["turns"] = rows

    def research_of(kind: str, goal: str) -> dict | None:
        """조사 하나: 턴이 맡긴 조사가 있으면 그것, 없으면 대본(무료)으로 맡긴 뒤 조사만 실제 OpenAI로."""
        nonlocal pid
        if pid is None:
            _, pid = home(app.api, f"oa-r-{uuid.uuid4().hex[:6]}@mitjip.test")
        q = "select id, status from assistant_research where project_id = $1 and kind = $2 order by created_at desc limit 1"
        found = app.query(q, uuid.UUID(pid), kind)
        if not found or found[0]["status"] != "queued":
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
            llm.clear_stubs()
            if r.status_code != 200:
                print("조사 맡기기 실패", r.status_code)
                return None
            found = app.query(q, uuid.UUID(pid), kind)
        rid = found[0]["id"]
        t0 = time.monotonic()
        status = app.call(research.run, rid)

        async def load():
            async with SessionLocal() as s:
                return await s.get(AssistantResearch, rid)

        row = app.call(load)
        data = research.data_of(row, "result")
        got = {
            "kind": kind,
            "goal": goal,
            "status": status,
            "seconds": round(time.monotonic() - t0, 1),
            "cost_usd": round((row.cost_micros or 0) / 1e6, 4),
            "summary": data.summary,
            "items": [x.model_dump(mode="json") for x in data.items],
            "links": [x.model_dump(mode="json") for x in data.links],
            "trail": [x.model_dump(mode="json") for x in data.trail],
            "partial": data.partial,
            **seen.get(str(rid), {}),
        }
        pics = sum(1 for x in got["items"] if x.get("image"))
        print(
            f"조사 {kind} {status} {got['seconds']}s ${got['cost_usd']} 기록 {len(got['trail'])}줄 "
            f"항목 {len(got['items'])}(그림 {pics}) 링크 {len(got['links'])} 찾은 만큼 {got['partial']}"
        )
        return got

    if "research" not in skip:
        done_rows = []
        cases = {x for x in a.cases.split(",") if x}
        if "materials" in cases and room("research"):
            done_rows.append(
                research_of("materials", "많이 고르는 실크벽지 질감 · 특징(사진 볼 수 있는 제품)")
            )
        if "outside" in cases and room("research"):
            done_rows.append(research_of(*OUTSIDE))
        report["steps"]["research"] = [x for x in done_rows if x]

    if "memory" not in skip and room("memory"):
        items = app.call(memory.extract, MEMORY_TEXT, None)
        report["steps"]["memory"] = [x.model_dump() for x in items]
        print("기억", report["steps"]["memory"])

    used = app.query(
        "select purpose, model, count(*) n, sum(input_tokens) i, sum(cache_read_tokens) c, "
        "sum(output_tokens) o, sum(web_searches) w, sum(cost_micros) cost, "
        "count(*) filter (where not ok) bad from llm_usage group by purpose, model order by purpose"
    )
    report["ledger"] = [dict(r) for r in used]
    report["spent_usd"] = round(spent(), 4)
    report["raw_usage"] = raw
    (out / "openai_live.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    for r in report["ledger"]:
        print("장부", r)
    print("합계 $", report["spent_usd"])
    app.close()


if __name__ == "__main__":
    main()

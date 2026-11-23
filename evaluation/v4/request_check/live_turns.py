"""요청 점검 실측(유료, OpenAI 길): 고객이 실제로 한 말 11개를 한 말씩 새 공사에 보내고, 부탁한 카드 · 조사 목표를
채웠는지 봐요. 고치기 전 · 뒤 코드를 같은 러너로 견줘요.

사용(eval-live-openai.sh가 OpenAI 키 · LLM_LIVE=true · LLM_PROVIDER=openai를 넣어요. EVAL_BACKEND=<작업 폴더>/backend):
  uv run python <이 파일> --tree <작업 폴더> --db mitjip_eval_reqcheck --redis 11 --out <폴더> --label before
- --tree의 evaluation/v4/apienv.py가 그 작업 폴더 backend 코드로 앱을 올려요.
- 채움: 카드 부탁은 그 턴의 카드 · 승인 카드에 그 종류가 있거나 그 카드 도구를 불렀는지(받은 견적서가 없어 카드가
  없을 때도 도구를 불렀으면 채움). 조사 부탁은 맡긴 조사 목표에 찾을 수 · 판매가가 있는지. 조사 담당(worker)은 돌리지
  않아요(목표만 봐요).
- 지출은 판마다 llm_usage 합을 더하고 --max-usd를 넘기 전에 멈춰요. 결과는 <out>/<label>.json(키 · 세션 값 없음).
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

# 고객이 실제로 한 말(v4 대화 · asks_set.jsonl)과 채움 기준
CASES = [
    ("h1", "우리 집 정보 변경할게", {"card": "home_info"}),
    ("h2", "평수 바꿀래", {"card": "home_info"}),
    ("h3", "16평으로 바꿔줘", {"card": "home_info"}),
    ("s1", "예상 공정표 보여저", {"card": "schedule"}),
    ("q1", "표준견적서 보여줘", {"card": "standard_quote"}),
    ("c1", "견적서 비교해 주세요", {"card": "quote_compare"}),
    ("v1", "업체 추천해 주세요", {"card": "vendor_picks"}),
    ("t1", "오늘 할 일 다시 보기", {"card": "today"}),
    ("r1", "업체도 조사해줘봐 5개까지", {"goal_count": 5}),
    ("r2", "믿집 밖에서 우리 동네 도배 업체 5곳 찾아 줘", {"goal_count": 5}),
    ("r3", "자재 3가지 더 조사해줘 흰색계열에 실크로", {"goal_count": 3}),
    ("r4", "LX 휘앙세 93 코지 린넨 49701-03 판매가랑 규격 찾아줘", {"goal_price": True}),
    # 앞 대화가 있는 말(처음 실패는 대화 중에 났어요): '앞 말 ⏎ 이번 말'
    ("m1", "견적서 왜 이렇게 비싸?\n우리 집 정보 변경할게", {"card": "home_info"}),
    ("m2", "AS기간은 보통 어떻게돼?\n표준견적서 보여줘", {"card": "standard_quote"}),
    ("m3", "도배 끝난 뒤에 환기는 얼마나 해야 해요?\n예상 공정표 보여저", {"card": "schedule"}),
]
# 카드 종류를 보이거나 만드는 도구(고치기 전 코드에는 asks가 없어 이 파일에 둬요)
CALL_KIND = {
    "get_home": "home_info",
    "propose_home_info": "home_info",
    "get_standard_quote": "standard_quote",
    "get_schedule": "schedule",
    "compare_quotes": "quote_compare",
    "recommend_vendors": "vendor_picks",
    "start_research": "vendor_picks",
    "today_tasks": "today",
}
GOAL_COUNT = re.compile(
    r"(\d{1,2})\s*(?:곳|군데|가지|개|종류)|(두|세|네|다섯|여섯)\s*(?:곳|군데|가지|개|종류)"
)
KO = {"두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6}
GOAL_PRICE = re.compile(r"판매가|가격|값")


def goal_count(goal: str) -> int | None:
    m = GOAL_COUNT.search(goal or "")
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else KO[m.group(2)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--db", default="mitjip_eval_reqcheck")
    ap.add_argument("--redis", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--max-usd", type=float, default=0.4)
    ap.add_argument("--only", default="", help="이 키만(쉼표, 예: r1,h1)")
    ap.add_argument("--repeat", type=int, default=1, help="말마다 몇 번(LLM 흔들림 보기)")
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x}
    cases = [
        (f"{k}#{i}" if a.repeat > 1 else k, t, w)
        for k, t, w in CASES
        if not only or k in only
        for i in range(1, a.repeat + 1)
    ]
    sys.path.insert(0, str(Path(a.tree) / "evaluation" / "v4"))
    import apienv

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    apienv.load_db_env()
    apienv.openai_mode()
    app = apienv.App(a.db, a.redis).boot()
    from tests.test_v4_assistant_turns import ask, events, home

    spent = 0.0
    rows: list[dict] = []
    for key, text, want in cases:
        if spent > a.max_usd - 0.04:
            print(f"상한 가까움({spent:.4f}), 멈춤")
            break
        app.reset()
        _, pid = home(app.api)
        *before, text = text.split("\n")
        for pre in before:  # 앞 대화(결과는 보지 않아요)
            ask(app.api, pid, pre)
            app.tap.take()
        r = ask(app.api, pid, text)
        ev = events(r.text) if r.status_code == 200 else []
        turn = ev[0][1]["turn_id"] if ev else None
        cards = [d["kind"] for e, d, _ in ev if e == "card"]
        acts = [d.get("kind") for e, d, _ in ev if e == "action" and d.get("status") == "proposed"]
        said = "".join(d.get("text", "") for e, d, _ in ev if e == "token")
        tapped = app.tap.take(turn) if turn else []  # 도구 이름 · 입력(이 턴)
        tools = [t["name"] for t in tapped]
        tried = {CALL_KIND[n] for n in tools if n in CALL_KIND}
        tried |= {str((t["args"] or {}).get("kind")) for t in tapped if t["name"] == "show_card"}
        rows_ = (
            app.query("select trace from assistant_turns where id = $1", uuid.UUID(turn))
            if turn
            else []
        )
        trace = rows_[0]["trace"] if rows_ else {}
        trace = json.loads(trace) if isinstance(trace, str) else (trace or {})
        goals = [
            g["goal"] for g in app.query("select goal from assistant_research order by created_at")
        ]
        got: dict = {}
        if "card" in want:
            k = want["card"]
            shown = k in cards or k in acts
            got["filled"] = shown or k in tried
            got["card_shown"] = shown
        if "goal_count" in want:
            got["filled"] = any(goal_count(g) == want["goal_count"] for g in goals)
        if want.get("goal_price"):
            got["filled"] = got.get("filled", True) and any(GOAL_PRICE.search(g) for g in goals)
        usage = (
            sum(int(x["cost_micros"]) for x in app.query("select cost_micros from llm_usage")) / 1e6
        )
        spent += usage
        rows.append(
            {
                "key": key,
                "text": text,
                "want": want,
                **got,
                "cards": cards,
                "actions": acts,
                "tools": tools,
                "goals": goals,
                "asks": trace.get("asks"),
                "llm": trace.get("llm"),
                "said": said[:240],
                "cost_usd": round(usage, 4),
            }
        )
        print(
            f"{key} {'채움' if got.get('filled') else '못 채움'} · 카드 {cards} · 도구 {tools} · ${usage:.4f}"
        )
    (out / f"{a.label}.json").write_text(
        json.dumps(
            {"label": a.label, "spent_usd": round(spent, 4), "rows": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    filled = sum(1 for x in rows if x.get("filled"))
    print(f"{a.label}: 채움 {filled}/{len(rows)} · 쓴 돈 ${spent:.4f}")
    app.close()


if __name__ == "__main__":
    main()

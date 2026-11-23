"""v4 비서 턴 전체로 답 받기: 같은 질문 · 같은 집(H32)에 /assistant/turns 한 턴을 돌려 보이는 글을 JSONL로 받아요.

    cd backend && uv run python ../evaluation/v4/run_v4_answers.py --dry-run --tag v4ans-dry --limit 2
    bash eval-live.sh mitjip_eval_v4ans 9 -- uv run python ../evaluation/v4/run_v4_answers.py --live --max-usd 2 --tag v4ans1

- 시스템(이 프로세스의 settings.assistant_answer_route만 바꿔요): v4_v3 = v3 · v4_hybrid = v2+v3 ·
  v4_hybrid_g = v2g+v3(v2 근거만 받아 비서가 한 번에 써요, v2 안의 LLM 답 없음) · v4_expert = 공정 전문가
  (expert+v3, docs/v4/13-trade-experts.md). --systems로 골라 돌려요
- 세트(pick): sets/compare.jsonl dev에서 묶음마다 씨앗 고정 순서(kit.stable_int(seed, id) 오름차순)로 앞에서 고른 40문항
  (다른 공정 6 · 여러 공정 14 · 지식 16 · 금액 · 기간 4 = PICK). --split heldout · both는 held-out을 모두 더해요(최종 확인용).
  --split all은 고르지 않고 세트 모두(sets/trade_expert36.jsonl 같은 작은 세트). --only는 고른 것 안에서만 걸러요
- 앱: apienv.App(평가 DB mitjip_eval_v4ans · Redis 9). 질문 × 시스템마다 표 · Redis를 비우고 다시 심어요(app.reset)
- 심기(공개 API): 고객 가입 → 공사 만들기(지금 화면 몸통: 공급 105.8㎡ · 도배 기본형 + 목공 몰딩 · 걸레받이 · 빈 집 ·
  시작 희망 2027-01-04 · 서울 마포구) → 표준견적서 한 번 열기(화면처럼. 턴 사실의 평형이 이 값에서 나와요)
- 지식: 평가 색인(tests/v3_kb.eval_index: 저장소 지식 + 공정 지식 묶음 expert_pack, 두 시스템이 같은 색인). apienv와 여기서
  knowledge.index · _index를 바꿔요. 임베딩은 부르지 않아요(OpenAI 키를 비움 · 평가 DB에 벡터 없음). meta.json knowledge에 남겨요
- 보이는 글(text): 토큰 글 + 카드 글 + 승인 카드 요약(run_compare 판정용 글과 같은 꼴: 인용 번호 · 꾸밈 지움).
  상태 글 · 칩 · 이어 묻기는 빼요. 같은 card_id는 마지막 것만 둬요(화면이 바꿔 끼워요)
- 받은 계산 값(facts_given): 턴 사실(집) + 도구 결과(모델에 간 값, policy.to_model) 요약. 판정기의 숫자 일치용
- 비용 · 지연: 장부(llm_usage) 합. reset 전에 읽어요. 턴 시간 = assistant_turns.trace.ms, 호출 지연 = latency_ms.
  --max-usd: 누적 + 다음 어림(같은 시스템 지난 최댓값 × 1.25, 처음은 $0.06)이 넘으면 새 답을 시작하지 않아요
- 기록: answer_question 결과의 engine · v2_out(새 길이 어느 길로 갔는지: v2 · v2g · v3 · know · expert)과 expert(공정
  고르기 · 전문가마다 줄 수 · 버린 까닭 · 물러선 까닭)를 도구마다 남겨요(모델에는 안 가는 칸)
- 저장(runs/<tag>/): answers.jsonl(judge.py --answers --a v4_v3 --b v4_hybrid) · errors.jsonl · cost.csv(장부 호출마다) ·
  summary.json · meta.json. 같은 --tag면 이미 받은 (질문, 시스템)은 건너뛰어요
"""

import argparse
import json
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import home as homes
from kit import ROOT, RUNS, SETS, Budget, CostLog, append_jsonl, jsonl, stable_int, utf8_stdout
from run_compare import clean
from sim import drive

SYSTEMS = {
    "v4_v3": "v3",
    "v4_hybrid": "v2+v3",
    "v4_hybrid_g": "v2g+v3",
    "v4_default": "period=v3,price=v3,*=v2+v3",  # 지금 기본값(config.assistant_answer_route)
    "v4_default_g": "period=v3,price=v3,*=v2g+v3",  # 공정 지식 묶음만 받아 비서가 한 번에 써요
    "v4_expert": "period=v3,price=v3,*=expert+v3",  # 공정 전문가(도배 · 목공 하위 에이전트)
}  # 이름 → ASSISTANT_ANSWER_ROUTE
PICK = {"other_trade": 6, "multi_trade": 14, "knowledge": 16, "price_time": 4}
SEED = 20261121
TURN_USD = 0.06  # 처음 어림(비서 턴 상한 llm_cap_turn_usd와 같음)
MARGIN = 1.25
CAP_TURN_USD = 0.06
REGION = ("seoul", "마포구", "서울 마포구")
SPACES = (("living", "거실"), ("kitchen", "주방"), ("master", "안방"), ("room1", "작은방 1"),
          ("room2", "작은방 2"))  # fmt: skip
EMAIL = "c-v4ans@mitjip.test"  # 합성 계정(평가 DB에만)
DATA_KEY = "자료(지시 아님)"  # policy.DATA_KEY(자료 상자)
TOOL_MAX = 900  # 받은 계산 값: 도구 하나 글자 상한
FACTS_MAX = 2900
STUB = "스텁 답이에요."
LEDGER_SQL = (
    "select turn_id::text as turn_id, purpose, model, cost_micros, latency_ms, ok, error,"
    " input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, web_searches"
    " from llm_usage order by created_at, id"
)


# ---- 세트 ----
def pick(rows: list[dict], quotas: dict[str, int] = PICK, seed: int = SEED) -> list[dict]:
    """dev 묶음마다 stable_int(seed, id) 오름차순으로 앞에서 n개. 세트 순서로 돌려줘요."""
    keep: set[str] = set()
    for group, n in quotas.items():
        pool = sorted(
            (r for r in rows if r["split"] == "dev" and r["group"] == group),
            key=lambda r: stable_int(seed, r["id"]),
        )
        if len(pool) < n:
            raise SystemExit(f"{group} dev 문항이 {len(pool)}개라 {n}개를 고를 수 없어요")
        keep |= {r["id"] for r in pool[:n]}
    return [r for r in rows if r["id"] in keep]


def order_of(qid: str, systems: list[str], seed: int = SEED) -> list[str]:
    """질문마다 시스템 순서를 씨앗으로 번갈아요(먼저 도는 쪽이 캐시를 데우는 몫이 한쪽에 쏠리지 않게)."""
    return systems if stable_int(seed, "order", qid) % 2 == 0 else systems[::-1]


# ---- 집 ----
def project_body(h: homes.Home) -> dict:
    """POST /projects 지금 화면 몸통(도배 + 목공을 함께 받는 꼴). 지역은 API 필수라 서울 마포구로 둬요."""
    keys = [k for k, _ in SPACES]
    trades: dict = {}
    if "dobae" in h.trades:
        trades["dobae"] = {"spaces": keys, "grade": h.grade}
    if "mokgong" in h.trades:
        trades["mokgong"] = {"spaces": keys, "items": list(h.mokgong)}
    return {
        "sido": REGION[0], "sgg": REGION[1],
        "size": {"basis": h.area_basis, "m2": f"{h.area_m2}"},
        "when": {"kind": "date", "start": h.start_wish.isoformat()},
        "occupied": h.living == "living",
        "spaces": [{"key": k, "name": n} for k, n in SPACES],
        "trades": trades,
    }  # fmt: skip


def home_text(h: homes.Home, today: date) -> str:
    """판정기가 보는 집(두 시스템이 같이 받은 공사): home.Home.text 꼴에 심은 지역 · 실제 오늘을 넣어요."""
    t = replace(h, today=today).text(with_start=True)
    tail = " (지역 · 예산은 정하지 않음)"
    return t.replace(tail, f" · {REGION[2]} (예산은 정하지 않음)") if tail in t else t


# ---- 보이는 글 ----
def won(x) -> str:
    return f"{x:,}원" if isinstance(x, int) else "-"


def _strings(v) -> list[str]:
    """모르는 카드: 글 칸만 평문으로(주소 · id 칸은 카드에 없어요)."""
    if isinstance(v, str):
        return [v] if v and not v.startswith("/") else []
    if isinstance(v, dict):
        return [s for k, x in v.items() if k not in ("href", "card_id") for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def card_lines(c: dict) -> list[str]:
    """v4 카드(kind · data) → 화면에 보이는 글 줄. 금액은 카드 값 그대로예요."""
    k, d = c.get("kind"), c.get("data") or {}
    out = [c["say"]] if c.get("say") else []
    if k == "answer":
        out.append(d.get("text") or "")
        out += [f"링크: {x.get('label')}" for x in d.get("links") or []]
    elif k == "home_info":
        out.append("[카드] 집 정보: " + " · ".join(d.get("facts") or []))
        out += [f"· 바꿀 것 {x.get('label')}: {x.get('before') or '-'} → {x.get('after')}"
                for x in d.get("changes") or []]  # fmt: skip
    elif k == "standard_quote":
        days = f" · 예상 {d['days']}일" if d.get("days") is not None else ""
        out.append(
            f"[카드] 표준견적서 {d.get('label', '')}: 합계(부가세 포함) {won(d.get('total_won'))}{days}"
        )
        out += [f"· {x.get('name')} {won(x.get('won'))}" for x in d.get("lines") or []]
    elif k == "knowledge":
        out.append(f"[카드] {d.get('title', '')}")
        out += [f"· {x}" for x in d.get("lines") or []]
        out += [f"· 확인: {x.get('label')}" for x in d.get("checklist") or []]
        if d.get("source"):
            out.append(f"출처: {d['source']}")
    elif k == "vendor_picks":
        out.append(f"[카드] 업체 추천({d.get('area_name', '')})")
        out += [f"· {p.get('name')}: 가견적 {won(p.get('estimate_won'))}"
                + "".join(f" · {r}" for r in p.get("reasons") or []) for p in d.get("picks") or []]  # fmt: skip
        out += [f"· 기준: {x}" for x in d.get("basis") or []]
    elif k == "schedule":
        out.append(f"[카드] 공정표 {d.get('vendor_name') or ''} {d.get('start')}~{d.get('end')}"
                   f"(일하는 날 {d.get('work_days')}일)")  # fmt: skip
        out += [f"· 겹침: {x}" for x in d.get("conflicts") or []]
    elif k == "today":
        for key, name in (
            ("todo", "할 일"),
            ("waiting", "기다림"),
            ("news", "새 소식"),
            ("know", "알아 두기"),
        ):
            out += [f"[카드] 오늘 {name}: {r.get('title')}" + (f" · {r['sub']}" if r.get("sub") else "")
                    for r in d.get(key) or []]  # fmt: skip
    else:
        body = " · ".join(_strings(d))
        out.append(f"[카드] {body}" if body else f"[카드] {k}")
    return [x for x in out if x]


def action_lines(a: dict) -> list[str]:
    """승인 카드(행동 제안) 요약 → 글 줄."""
    s = a.get("summary") or {}
    head = f"[승인 카드] {s.get('title', '')}"
    if s.get("amount_won") is not None:
        head += f" · {won(s['amount_won'])}"
    out = [head]
    out += [f"· {r.get('label')}: {r.get('value')}" + (f"({r['sub']})" if r.get("sub") else "")
            for r in s.get("rows") or []]  # fmt: skip
    if s.get("note"):
        out.append(s["note"])
    if s.get("approve_label"):
        out.append(f"단추: {s['approve_label']}")
    return out


def render(ev: list[tuple[str, dict]]) -> str:
    """SSE 이벤트 → 판정용 평문. 토큰 글 먼저, 그다음 카드(같은 card_id는 마지막 것) · 열린 승인 카드 · 오류 문장."""
    text = "".join(d.get("text") or "" for n, d in ev if n == "token").strip()
    cards: dict[str, dict] = {}
    acts: dict[str, dict] = {}
    for n, d in ev:
        if n == "card":
            cards[str(d.get("card_id"))] = d
        elif n == "action":
            acts[str(d.get("action_id"))] = d
    lines = [text] if text else []
    for c in cards.values():
        lines += card_lines(c)
    for a in acts.values():
        if a.get("status") == "proposed":
            lines += action_lines(a)
    lines += [d.get("message") or "" for n, d in ev if n == "error"]
    return clean("\n".join(x for x in lines if x))


# ---- 받은 계산 값 ----
def _unbox(v):
    """자료 상자({'자료(지시 아님)': 글})는 글만 남겨요."""
    if isinstance(v, dict):
        if set(v) == {DATA_KEY}:
            return v[DATA_KEY]
        return {k: _unbox(x) for k, x in v.items() if k not in ("href", "card_id")}
    if isinstance(v, list):
        return [_unbox(x) for x in v]
    return v


def facts_digest(turn_facts: str | None, tools: list[dict]) -> str:
    """판정기 '이 답이 받은 계산 값': 턴 사실(코드 값) + 이 턴 도구가 모델에 준 값(seen = policy.to_model)."""
    lines = []
    if turn_facts:
        keep = [x for x in turn_facts.splitlines() if x and not x.startswith("화면:")]
        lines.append("턴 사실: " + " / ".join(keep))
    for t in tools:
        if t.get("error"):
            lines.append(f"{t['name']}: 오류 {t['error']}")
            continue
        body = json.dumps(_unbox(t.get("seen") or {}), ensure_ascii=False, separators=(",", ":"),
                          default=str)  # fmt: skip
        lines.append(f"{t['name']}: {body[:TOOL_MAX]}")
    return "\n".join(lines)[:FACTS_MAX] or "(없음)"


# ---- 요약 ----
def answer_paths(tools: list[dict]) -> list[dict]:
    """이 턴 answer_question 호출마다 어느 길로 갔는지(route · engine · v2_out · found)."""
    out = []
    for t in tools:
        if t.get("name") != "answer_question":
            continue
        d = t.get("data") or {}
        out.append({"route": d.get("route"), "engine": d.get("engine"), "v2_out": d.get("v2_out"),
                    "found": d.get("found"), "error": t.get("error"), "expert": d.get("expert")})  # fmt: skip
    return out


def expert_stats(paths: list[dict]) -> dict:
    """공정 전문가 기록 모음: 고른 길 · 쓴 길 · 물러선 까닭 · 전문가 호출 · 실패 · 줄 · 버린 까닭 · 시간."""
    recs = [p["expert"] for p in paths if p.get("expert")]
    notes = [n for r in recs for n in r.get("notes") or []]
    dropped: Counter = Counter()
    for n in notes:
        dropped.update(n.get("dropped") or {})
    ms = [n["ms"] for n in notes if isinstance(n.get("ms"), int)]
    return {
        "pick": dict(Counter(r.get("pick") for r in recs)),
        "used": dict(Counter(r.get("used") for r in recs)),
        "why_v2g": dict(Counter(r["why_v2g"] for r in recs if r.get("why_v2g"))),
        "calls": len(notes), "failed": dict(Counter(n["failed"] for n in notes if n.get("failed"))),
        "out": sum(bool(n.get("out")) for n in notes), "lines": sum(n.get("lines", 0) for n in notes),
        "guide_only": sum(n.get("guide_only", 0) for n in notes), "asks": sum(bool(n.get("ask")) for n in notes),
        "dropped": dict(dropped), "ms_median": _r(drive.pctl(ms, 0.5), 0), "ms_p90": _r(drive.pctl(ms, 0.9), 0),
    }  # fmt: skip


def summarize(rows: list[dict], errors: list[dict]) -> dict:
    out: dict = {}
    for name in dict.fromkeys(r["system"] for r in [*rows, *errors]):
        rs = [r for r in rows if r["system"] == name]
        cost = [float(r.get("cost_usd") or 0) for r in rs]
        ms = [r["ms"] for r in rs if isinstance(r.get("ms"), (int, float))]
        wall = [r["wall_ms"] for r in rs if isinstance(r.get("wall_ms"), (int, float))]
        paths = [p for r in rs for p in r.get("answer_paths") or []]
        out[name] = {
            "n": len(rs), "errors": sum(e["system"] == name for e in errors),
            "cost_usd": round(sum(cost) + sum(float(e.get("cost_usd") or 0) for e in errors if e["system"] == name), 6),
            "turn_usd_median": _r(drive.pctl(cost, 0.5)), "turn_usd_p90": _r(drive.pctl(cost, 0.9)),
            "turn_usd_max": _r(max(cost) if cost else None),
            "over_turn_cap": sum(c > CAP_TURN_USD for c in cost),
            "turn_ms_median": _r(drive.pctl(ms, 0.5), 0), "turn_ms_p90": _r(drive.pctl(ms, 0.9), 0),
            "wall_ms_median": _r(drive.pctl(wall, 0.5), 0), "wall_ms_p90": _r(drive.pctl(wall, 0.9), 0),
            "llm_calls": dict(sorted(Counter(r.get("llm_calls") for r in rs).items(), key=lambda x: str(x[0]))),
            "modes": dict(Counter(r.get("turn_mode") for r in rs)),
            "status": dict(Counter(r.get("turn_status") for r in rs)),
            "stops": dict(Counter(r.get("stop") for r in rs if r.get("stop"))),
            "tools": dict(Counter(t for r in rs for t in r.get("tools") or []).most_common()),
            "asked": sum(bool(r.get("answer_paths")) for r in rs),  # answer_question을 부른 턴
            "engine": dict(Counter(p.get("engine") or "-" for p in paths)),
            "v2_out": sum(bool(p.get("v2_out")) for p in paths),
            "to_v3": sum(any(p.get("engine") == "v3" and p.get("v2_out") for p in r.get("answer_paths") or [])
                         for r in rs),  # 새 길이 v3로 넘긴 턴
            "by_purpose": _by_purpose(rs),
            "expert": expert_stats(paths),
        }  # fmt: skip
    return out


def _by_purpose(rs: list[dict]) -> dict:
    got: dict[str, list] = {}
    for r in rs:
        for c in r.get("calls") or []:
            b = got.setdefault(str(c.get("purpose")), [0, 0.0])
            b[0] += 1
            b[1] += c.get("cost_usd") or 0
    return {k: {"calls": n, "cost_usd": round(u, 6)} for k, (n, u) in sorted(got.items())}


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


def next_estimate(prev: list[float]) -> float:
    return max(prev) * MARGIN if prev else TURN_USD


# ---- 앱 쪽(평가 DB) ----
class OutTap:
    """비서 도구 결과를 모아요(engine · v2_out 기록, 받은 계산 값). 운영 코드는 그대로 두고 이 프로세스에서만 감싸요."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.facts: str | None = None

    def install(self) -> None:
        from app.assistant import policy
        from app.assistant import service as assistant_service
        from app.assistant import tools as tools_mod

        real_run = tools_mod.run

        async def run(t, tc, args):
            row = {
                "turn_id": str(tc.turn_id),
                "name": t.name,
                "args": args if isinstance(args, dict) else {},
            }
            self.rows.append(row)
            try:
                out = await real_run(t, tc, args)
            except Exception as e:
                row["error"] = getattr(e, "code", None) or type(e).__name__
                raise
            row.update(
                data=out.data, seen=policy.to_model(out.data), cards=[c.kind for c in out.cards]
            )
            return out

        tools_mod.run = run
        real_facts = assistant_service._customer_facts

        # 인자는 그대로 넘겨요(서비스가 인자를 더해도 깨지지 않게)
        async def facts(*args, **kwargs):
            got = await real_facts(*args, **kwargs)
            self.facts = got
            return got

        assistant_service._customer_facts = facts

    def take(self, turn_id: str | None) -> tuple[list[dict], str | None]:
        got = [r for r in self.rows if turn_id and r["turn_id"] == turn_id]
        facts, self.rows, self.facts = self.facts, [], None
        return got, facts


def patch_knowledge() -> dict:
    """knowledge._index(→ search · verify_cites · 이어 묻기)도 평가 색인으로, 임베딩은 부르지 않아요."""
    from v3_kb import eval_index

    from app.agent import llm
    from app.knowledge import service as knowledge

    ix = eval_index()

    async def _index(_s):
        return ix, []

    async def no_embed(_texts):
        return None

    knowledge._index = _index
    llm.embed_texts = no_embed
    return {"index": ix.version, "chunks": ix.n}


def seed(app, h: homes.Home, today: date) -> dict:
    """고객 가입 → 공사 만들기 → 표준견적서 열기. 쿠키(고객 세션)는 app.api에 남아요."""
    from sim.world import PASSWORD, World

    w = World(app.api, app.query, today)
    app.api.cookies.clear()
    body = {"name": "고객", "email": EMAIL, "password": PASSWORD, "phone": "01000000000"}
    w.need(app.api.post("/auth/signup", json=body), "고객 가입")
    pid = w.need(app.api.post("/projects", json=project_body(h)), "공사 만들기")["id"]
    st = w.need(app.api.get(f"/projects/{pid}/standard"), "표준견적서")
    std = {"total": st.get("total"), "trades": {t["trade"]: t["total"] for t in st.get("trades") or []},
           "days": st.get("days"), "pyeong": st.get("pyeong"), "area_m2": st.get("area_m2")}  # fmt: skip
    return {"pid": pid, "standard": std}


def stub_script(question: str) -> None:
    """--dry-run: Claude 대본(유료 호출 0회). 비서가 answer_question을 부르고 짧게 답해요(v2를 부르면 v2도 대본 글)."""
    from app.agent import llm

    call = {
        "id": "q",
        "name": "answer_question",
        "input": {"question": question, "kind": "general"},
    }
    llm.set_claude_script([{"tool_calls": [call]}, {"text": STUB}, {"text": STUB}])


def turn(app, pid: str, text: str) -> dict:
    """비서 한 턴(SSE를 끝까지 받아요). 돌려주는 것: 이벤트 · 턴 행(상태 · 모드 · trace)."""
    body = {"client_key": uuid.uuid4().hex, "text": text, "project_id": pid}
    t0 = time.perf_counter()
    r = app.api.post("/assistant/turns", json=body)
    wall = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        return {"http": r.status_code, "error": drive._err(r), "wall_ms": wall, "ev": []}
    ev = drive.sse(r.text)
    tid = ev[0][1].get("turn_id") if ev and ev[0][0] == "ack" else None
    rows = app.query("select status, mode, tool_calls, trace, error_code from assistant_turns where id = $1",
                     uuid.UUID(tid)) if tid else []  # fmt: skip
    t = dict(rows[0]) if rows else {}
    trace = drive._trace(t.get("trace"))
    err = next((d for n, d in ev if n == "error"), None)
    return {
        "http": 200, "ev": ev, "turn_id": tid, "wall_ms": wall, "turn_status": t.get("status"),
        "turn_mode": t.get("mode"), "tool_calls": t.get("tool_calls") or 0, "trace": trace,
        "error": (err or {}).get("code") or t.get("error_code"),
    }  # fmt: skip


def ledger(app) -> list[dict]:
    """장부 줄(그 답 것만: 답마다 reset으로 비워요)."""
    return [dict(r) for r in app.query(LEDGER_SQL)]


def call_rows(rows: list[dict]) -> list[dict]:
    return [{"purpose": r["purpose"], "model": r["model"], "cost_usd": int(r["cost_micros"] or 0) / 1e6,
             "latency_ms": r["latency_ms"], "ok": r["ok"], "error": r["error"],
             "in_turn": bool(r["turn_id"])} for r in rows]  # fmt: skip


def run_one(app, tap: OutTap, ctx: dict, row: dict, name: str) -> dict:
    """한 문항 × 한 시스템: 비우기 → 길 정하기 → 심기 → 한 턴 → 장부 읽기(다음 reset 전에).
    돌려주는 것: rec(답 줄) 또는 err(오류 줄) · led(장부 줄) · ledger_error(장부를 못 읽은 까닭)."""
    from sim.world import SeedError

    from app.config import settings

    app.reset()
    tap.take(None)
    settings.assistant_answer_route = SYSTEMS[name]
    q = row["turns"][-1]
    base = {"id": row["id"], "system": name, "route_setting": SYSTEMS[name], "mode": ctx["mode"],
            "turns": row["turns"], "question": q, "group": row["group"], "home": ctx["home"].id,
            "home_text": ctx["home_text"]}  # fmt: skip
    err = res = None
    seeded: dict = {}
    try:
        seeded = seed(app, ctx["home"], ctx["today"])
        if ctx["mode"] == "dry-run":
            stub_script(q)
        res = turn(app, seeded["pid"], q)
    except SeedError as e:
        err = {"class": "SeedError", "error": str(e)[:300]}
    except Exception as e:  # noqa: BLE001 - 한 문항이 깨져도 기록하고 이어 가요
        err = {
            "class": type(e).__name__,
            "error": str(e)[:300],
            "tb": traceback.format_exc(limit=4),
        }
    got: dict = {"led": [], "ledger_error": None}
    try:
        got["led"] = ledger(app)
    except Exception as e:  # noqa: BLE001 - 셀 수 없으면 부르는 쪽이 멈춰요
        got["ledger_error"] = type(e).__name__
    calls = call_rows(got["led"])
    tools, facts = tap.take(res.get("turn_id") if res else None)
    if err is None and res is not None and res.get("http") != 200:
        err = {"class": f"http_{res['http']}", "error": res.get("error") or ""}
    if err is None and res is not None and res.get("error"):  # 턴이 오류로 끝남(화면에는 오류 문장)
        err = {"class": "turn_error", "error": str(res["error"]), "text": render(res["ev"])}
    if err is not None:
        got["err"] = {**base, **err, "calls": calls, "tools": [t["name"] for t in tools]}
        return got
    trace = res["trace"]
    got["rec"] = {
        **base, "text": render(res["ev"]), "facts_given": facts_digest(facts, tools),
        "turn_id": res["turn_id"], "turn_status": res["turn_status"], "turn_mode": res["turn_mode"],
        "stop": trace.get("stop"), "reason": trace.get("reason"), "ms": trace.get("ms"),
        "wall_ms": res["wall_ms"], "llm_calls": sum(c["in_turn"] for c in calls), "calls": calls,
        "tools": [t["name"] for t in tools], "answer_paths": answer_paths(tools),
        "tool_rows": [{k: t.get(k) for k in ("name", "args", "seen", "cards", "error")} for t in tools],
        "cards": [d.get("kind") for n, d in res["ev"] if n == "card"], "standard": seeded.get("standard"),
    }  # fmt: skip
    return got


def line_of(rec: dict, spent: float) -> str:
    paths = " ".join(f"{p['engine'] or p['route']}{'(v2 밖)' if p['v2_out'] else ''}"
                     for p in rec["answer_paths"]) or "-"  # fmt: skip
    return (f"{rec['id']} {rec['system']} {rec['turn_mode']}/{rec['turn_status']} 답길 {paths} · "
            f"도구 {','.join(rec['tools']) or '-'} · {rec['ms']}ms · LLM {rec['llm_calls']}번 · "
            f"${rec['cost_usd']:.4f} · 누적 ${spent:.4f}")  # fmt: skip


def report(summary: dict) -> None:
    for name, s in summary["systems"].items():
        print(f"{name}: {s['n']}개 · 오류 {s['errors']} · ${s['cost_usd']} · 턴 중앙 ${s['turn_usd_median']} · "
              f"p90 ${s['turn_usd_p90']} · 상한 넘음 {s['over_turn_cap']} · 턴 시간 중앙 {s['turn_ms_median']}ms · "
              f"p90 {s['turn_ms_p90']}ms · 답길 {s['engine']} · v3로 넘김 {s['to_v3']}")  # fmt: skip


# ---- 실행 ----
def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", check=False).stdout.strip()  # fmt: skip
    except OSError:
        return ""


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="v4 비서 턴 답 받기(같은 질문 · 같은 집)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="Claude 대본(기본). 유료 호출 0회")
    g.add_argument(
        "--live", action="store_true", help="LLM 모드(유료). LLM_LIVE=true · 키 · --max-usd 필요"
    )
    ap.add_argument("--tag", required=True)
    ap.add_argument("--set", type=Path, default=SETS / "compare.jsonl")
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    ap.add_argument("--only", help="쉼표로 질문 id(고른 문항 안에서)")
    ap.add_argument(
        "--split",
        choices=("dev", "heldout", "both", "all"),
        default="dev",
        help="dev = 고른 40문항 · heldout = held-out 모두(최종 확인용) · both = 둘 다 · all = 세트 모두(고르지 않음)",
    )
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--max-usd", type=float, help="--live에는 꼭 줘요(장부 합 기준)")
    ap.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default="anthropic",
        help="--live 공급자. openai는 OPENAI_API_KEY를 써요(모델 · effort는 OPENAI_* 환경변수)",
    )
    ap.add_argument("--db", default="mitjip_eval_v4ans")
    ap.add_argument("--redis-db", type=int, default=9)
    ap.add_argument("--env-file", type=Path, help="DB 접속값을 읽을 .env(키는 읽지 않아요)")
    a = ap.parse_args(argv)
    if a.live and (a.max_usd is None or a.max_usd <= 0):
        ap.error("--live에는 --max-usd(0보다 큰 값)가 필요해요")
    bad = [s for s in a.systems.split(",") if s not in SYSTEMS]
    if bad:
        ap.error(f"모르는 시스템: {bad}")
    a.dry_run = not a.live
    return a


def pick_rows(a) -> list[dict]:
    every = jsonl(a.set)
    rows = pick(every, seed=a.seed) if a.split in ("dev", "both") else []
    if a.split in ("heldout", "both"):  # held-out은 고르지 않고 모두 써요
        rows += [r for r in every if r["split"] == "heldout"]
    if a.split == "all":  # 작은 세트(trade_expert36 등): 고르지 않고 모두
        rows = list(every)
    if a.only:
        want = a.only.split(",")
        miss = [x for x in want if x not in {r["id"] for r in rows}]
        if miss:
            raise SystemExit(f"고른 문항에 없는 id예요: {miss}")
        rows = [r for r in rows if r["id"] in want]
    return rows[: a.limit] if a.limit else rows


def main(argv=None) -> int:
    utf8_stdout()
    a = parse_args(argv)
    import apienv

    if a.live:
        apienv.openai_mode() if a.provider == "openai" else apienv.live_mode()
    else:
        apienv.free_mode()
    env = apienv.load_db_env(a.env_file)
    systems = a.systems.split(",")
    rows = pick_rows(a)
    h = homes.HOMES["H32"]
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "tag": a.tag, "mode": "live" if a.live else "dry-run", "set": str(a.set), "systems": SYSTEMS,
        "run_systems": systems, "pick": {"quotas": PICK, "seed": a.seed, "split": a.split,
        "rule": "묶음마다 kit.stable_int(seed, id) 오름차순 앞에서 n개"}, "rows": len(rows),
        "ids": [r["id"] for r in rows], "home": h.id, "project_body": project_body(h), "db": a.db,
        "redis_db": a.redis_db, "max_usd": a.max_usd, "head": _git("rev-parse", "HEAD"),
        "dirty": len(_git("status", "--short").splitlines()), "env_file": env.name if env else None,
    }  # fmt: skip
    meta_path = out / "meta.json"
    old = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else None
    if old and any(old.get(k) != meta[k] for k in ("mode", "home", "project_body")):
        sys.exit(f"{out}는 다른 설정으로 돈 결과예요. 새 --tag를 써요")
    app = apienv.App(a.db, a.redis_db).boot()
    mode = apienv.settings_mode()
    if mode["available"] != a.live:
        app.close()
        print(
            "LLM을 부를 수 없어 멈춰요(LLM_LIVE · 키 · 공급자)."
            if a.live
            else "LLM이 켜져 있어 멈춰요."
        )
        return 2
    meta["knowledge"] = patch_knowledge()
    tap = OutTap()
    tap.install()
    from app.shared.clock import today_seoul

    today = today_seoul()
    ctx = {"mode": meta["mode"], "home": h, "today": today, "home_text": home_text(h, today)}
    meta.update(today=today.isoformat(), home_text=ctx["home_text"], llm=apienv.live_settings(),
                app_mode=mode)  # fmt: skip
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8")
    done = {(r["id"], r["system"]) for r in jsonl(out / "answers.jsonl")}
    prev_rows = [*jsonl(out / "answers.jsonl"), *jsonl(out / "errors.jsonl")]
    book = Budget(
        a.max_usd if a.live else None, sum(float(r.get("cost_usd") or 0) for r in prev_rows)
    )
    prev: dict[str, list[float]] = {}
    for r in prev_rows:
        prev.setdefault(r["system"], []).append(float(r.get("cost_usd") or 0))
    log = CostLog(out / "cost.csv", "v4turn")
    stopped = None
    n_ok = n_err = 0
    try:
        for row in rows:
            for name in order_of(row["id"], systems, a.seed):
                if (row["id"], name) in done:
                    continue
                est = next_estimate(prev.get(name, [])) if a.live else 0.0
                if a.live and not book.reserve(est):
                    stopped = (f"상한 ${a.max_usd}: 지금까지 ${book.spent:.4f} + 다음 어림 ${est:.4f}"
                               f"({row['id']} {name})이 넘어 시작하지 않았어요")  # fmt: skip
                    break
                got = run_one(app, tap, ctx, row, name)
                led = got["led"]
                cost = round(sum(int(x["cost_micros"] or 0) for x in led) / 1e6, 6)
                if got["ledger_error"]:  # 셀 수 없으면 어림으로 세고 멈춰요
                    cost = max(cost, est)
                    stopped = f"장부(llm_usage)를 읽지 못해 멈췄어요({got['ledger_error']})"
                for x in led:
                    u = {"input": x["input_tokens"], "cache_read": x["cache_read_tokens"],
                         "cache_write_5m": x["cache_write_tokens"], "output": x["output_tokens"]}  # fmt: skip
                    log.add(row["id"], f"{name}:{x['purpose']}", x["model"], u, estimated=a.dry_run,
                            ledger_usd=int(x["cost_micros"] or 0) / 1e6)  # fmt: skip
                book.settle(est, cost)
                prev.setdefault(name, []).append(cost)
                if "err" in got:
                    n_err += 1
                    append_jsonl(out / "errors.jsonl", {**got["err"], "cost_usd": cost})
                    print(f"{row['id']} {name} 오류 {got['err']['class']}: {got['err']['error'][:120]}",
                          flush=True)  # fmt: skip
                else:
                    n_ok += 1
                    rec = {**got["rec"], "cost_usd": cost}
                    append_jsonl(out / "answers.jsonl", rec)
                    print(line_of(rec, book.spent), flush=True)
                if stopped:
                    break
            if stopped:
                break
    finally:
        app.close()
    answers, errors = jsonl(out / "answers.jsonl"), jsonl(out / "errors.jsonl")
    summary = {"systems": summarize(answers, errors), "answers": len(answers), "errors": len(errors),
               "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in [*answers, *errors]), 6),
               "stopped": stopped}  # fmt: skip
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    meta.update(stopped=stopped)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8")
    report(summary)
    print(f"이번 {n_ok}개 · 오류 {n_err} · 모두 {summary['answers']}개 · 비용 ${summary['cost_usd']}"
          + (" (대본, 유료 0회)" if a.dry_run else ""))  # fmt: skip
    if stopped:
        print(stopped)
    print(f"저장: {out}")
    return 3 if stopped else (1 if n_err and not n_ok else 0)


if __name__ == "__main__":
    sys.exit(main())

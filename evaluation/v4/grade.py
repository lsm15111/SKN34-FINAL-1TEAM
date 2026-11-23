"""한 답 점수 판정기: 답 하나 · 대화 하나에 차원별 1~5점과 종합 1~10점을 매겨요(rubric_single.md).

    cd backend
    uv run python ../evaluation/v4/grade.py --tag g-dry --answers ../evaluation/v4/runs/v4ans-now/answers.jsonl --controls 8
    uv run python ../evaluation/v4/grade.py --tag g-dry-sim --sims ../evaluation/v4/runs/sim-model-terra-low/sim.jsonl --trial 0
    (실제 · 유료 · 허락 뒤) ... --live --judge claude-opus-5-5 | gpt-6.1-sol --max-usd N
    uv run python ../evaluation/v4/grade.py --tag g-opus --report --compare g-sol      # 두 판정기 견주기(LLM 0회)

논문에서 가져온 것(Zheng et al. 2023 'Judging LLM-as-a-Judge', docs/v4/eval/results.md 'LLM 판정')
- 한 답 점수(3.1 single answer grading) + 기준 답(reference-guided): 정답 조각 · 기대 행동 · 받은 계산 값 · 참고 답(정답 아님)
- 이유를 먼저 쓰고 점수(CoT). 대화는 한 글에 통째로 넣어요(3.5)
- 길이 편향 대조군(표 3 repetitive list): 같은 답 끝에 같은 내용을 목록으로 되풀이한 판(pad). 원래 답보다 높으면 실패
- 빈 답 · '잘 모르겠어요' 대조군은 종합 2점 이하여야 해요
- 자기 편애(3.3): 비서와 다른 계열 판정기를 기본으로 두고, 두 계열 차이를 --compare로 봐요(Verga et al. 2024 PoLL)
- 출력 runs/<tag>/: grades.jsonl · calls.jsonl · cost.csv · errors.jsonl · summary.json · meta.json. 같은 --tag면 이어 해요
- 키: 환경변수(ANTHROPIC_API_KEY · OPENAI_API_KEY) 또는 --env-file의 그 한 줄만 읽어요(값은 찍지 않아요)
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import judge as jg
import prices
from kappa import cohen_kappa
from kit import (
    ROOT,
    RUNS,
    SETS,
    Budget,
    CostLog,
    append_jsonl,
    bootstrap_ci,
    est_tokens,
    jsonl,
    short_hash,
    stable_int,
    utf8_stdout,
    wilson,
)
from pydantic import BaseModel, Field, ValidationError
from sim import check as simcheck

RUBRIC_PATH = HERE / "rubric_single.md"
SCEN = SETS / "scenarios"
DIMS = jg.DIMS
CHAT_DIMS = (*DIMS, "progress")
DIM_KO = {**jg.DIM_KO, "progress": "진행"}
RETRY = 3
TURN_MAX = 1200  # 대화: 비서 말 하나 글자 상한
TOOL_FULL = 4000  # 판정기 기준 값: 도구 결과 하나 글자 상한(원본 seen에서)
FACTS_FULL = 9000  # 판정기 기준 값 전체 글자 상한
QUOTE_DAYS = 3  # sim/world.py QUOTE_DEFAULT 기간(시나리오에 기간이 없을 때)
OUT_TOK = {"answer": 900, "control": 900, "chat": 1200}  # 어림 출력 토큰
NULL_N = 3  # 빈 답 · 모름 대조군은 앞 3개 질문만
LEVELS = ((8, 10, "내보낼 만함"), (5, 7, "쓸 만함"), (1, 4, "고쳐야 함"))
STATUS_KO = {"executed": "반영됨", "rejected": "거절됨", "expired": "만료", "failed": "실패"}
HOME_KO = {"pyeong": "평형", "area_m2": "면적㎡", "area_basis": "면적 기준", "trades": "공정", "grade": "도배 유형",
           "living": "거주", "start_wish": "시작 희망"}  # fmt: skip

Five = Literal[1, 2, 3, 4, 5]
Ten = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
REASON = "이 차원 점수 이유 한 문장(60자 안). 점수보다 먼저 써요"
SCORE = "1~5(5가 가장 좋음). 판단할 거리가 없으면 null"
WORST = "가장 큰 문제 한 문장(60자 안). 없으면 '없음'"
WHY = "종합 이유 한두 문장(100자 안). 점수보다 먼저 써요"


def _desc(d: str) -> str:
    return jg.Verdict.model_fields[d].description or d


class DimGrade(BaseModel):
    reason: str = Field(description=REASON)
    score: Five | None = Field(description=SCORE)


class Grade(BaseModel):
    accuracy: DimGrade = Field(description=_desc("accuracy"))
    grounding: DimGrade = Field(description=_desc("grounding"))
    usefulness: DimGrade = Field(description=_desc("usefulness"))
    concision: DimGrade = Field(description=_desc("concision"))
    safety: DimGrade = Field(description=_desc("safety"))
    numbers: DimGrade = Field(description=_desc("numbers"))
    worst: str = Field(description=WORST)
    overall_reason: str = Field(description=WHY)
    overall: Ten = Field(description="종합 1~10(루브릭 2절)")


class ChatGrade(BaseModel):
    accuracy: DimGrade = Field(description=_desc("accuracy"))
    grounding: DimGrade = Field(description=_desc("grounding"))
    usefulness: DimGrade = Field(description=_desc("usefulness"))
    concision: DimGrade = Field(description=_desc("concision"))
    safety: DimGrade = Field(description=_desc("safety"))
    numbers: DimGrade = Field(description=_desc("numbers"))
    progress: DimGrade = Field(
        description="진행: 목표대로 일을 앞으로 옮겼나 · 필요한 것을 물었나 · 확정은 승인 카드로"
    )
    worst: str = Field(description=WORST)
    worst_turn: int | None = Field(description="가장 문제인 비서 턴 번호. 없으면 null")
    overall_reason: str = Field(description=WHY)
    overall: Ten = Field(description="종합 1~10(루브릭 2절)")


# ---- 매길 것 ----
@dataclass
class Item:
    key: str  # 결과 줄 열쇠: 질문 id · 질문 id#pad · 시나리오#trial
    id: str
    kind: str  # answer · control · chat
    variant: str  # real · pad · empty · dunno
    group: str
    split: str
    shared: str  # 질문 · 집 · 기대 · 조각 · 참고 답 / 시나리오
    body: str  # 매길 답 또는 대화
    text: str  # 답 글(길이 셈용)
    extra: dict = field(default_factory=dict)  # 판정기는 보지 않는 값(코드 점검 결과 등)


def answer_body(text: str, facts: str) -> str:
    body = (text or "").strip() or "(빈 답)"
    if len(body) > jg.ANSWER_MAX:
        body = body[: jg.ANSWER_MAX] + f"\n(이하 {len(body) - jg.ANSWER_MAX}자 생략)"
    calc = (facts or jg.NO_FACTS)[:FACTS_FULL]
    return f"## 답\n<answer>\n{body}\n</answer>\n이 답이 받은 계산 값: {calc}\n\n위 답을 루브릭대로 매겨 주세요."


def full_facts(r: dict) -> str:
    """판정기 기준 값: 턴 사실 + 도구 결과 원본(tool_rows의 seen = 모델이 받은 값). facts_given은 도구마다 900자에서
    잘려 표준견적서 paper 칸(벽지를 직접 사면 바뀔 합계) 같은 계산 값이 빠졌어요(2026-11-23 set30:xd105 오판)."""
    given = r.get("facts_given") or ""
    head = given.split("\n", 1)[0] if given.startswith("턴 사실") else ""
    tools = [t for t in r.get("tool_rows") or [] if t.get("seen") is not None]
    if not tools:
        return given or jg.NO_FACTS
    body = [
        f"{t['name']}: {json.dumps(t['seen'], ensure_ascii=False, separators=(',', ':'))[:TOOL_FULL]}"
        for t in tools
    ]
    return "\n".join([head, *body] if head else body)[:FACTS_FULL]


def load_answers(a) -> list[Item]:
    """답 파일(run_v4_answers.py)에서 --system 답만 골라 세트와 질문 id로 맞춰요."""
    sets = {r["id"]: r for r in jsonl(a.set)}
    items = []
    for r in jsonl(a.answers):
        q = sets.get(r["id"])
        if r.get("system") != a.system or r.get("error") or q is None:
            continue
        facts = full_facts(r)
        x = jg.Item(
            id=r["id"], source=q["source"], split=q["split"], group=q["group"], kind=q.get("kind", ""),
            question=q["turns"][-1], history=q["turns"][:-1], home_text=r.get("home_text") or "",
            expect=q.get("expect", []), avoid=q.get("avoid", []), ref=q.get("ref", {}),
            text={"A": r["text"], "B": ""}, facts={"A": facts, "B": ""},
        )  # fmt: skip
        shared = jg.shared_block(x).replace("(두 답이 같은 집 조건을 받았어요)", "")
        items.append(Item(
            key=r["id"], id=r["id"], kind="answer", variant="real", group=q["group"], split=q["split"],
            shared=shared, body=answer_body(r["text"], facts), text=r["text"] or "", extra={"facts": facts},
        ))  # fmt: skip
    return items


def pad(text: str) -> str:
    """길이 편향 대조(Zheng et al. 표 3 'repetitive list'): 같은 내용을 목록으로 한 번 더 붙여요. 새 정보는 없어요."""
    parts = [p.strip(" -•·") for p in re.split(r"\n+|(?<=[.!?])\s+", text or "")]
    rows = "\n".join(f"- {p}" for p in parts if len(p) > 3)
    return f"{(text or '').rstrip()}\n\n한 번 더 정리하면 이래요.\n{rows}"


def controls(items: list[Item], n: int, seed: int) -> list[Item]:
    """대조군: 씨앗 순서로 n개 답에 pad 판, 그중 앞 NULL_N개는 빈 답 · 모름 판도 더해요."""
    pool = sorted(
        (x for x in items if x.kind == "answer" and x.text.strip()),
        key=lambda x: stable_int(seed, "ctl", x.id),
    )[:n]
    out = []
    for i, x in enumerate(pool):
        for variant, text in (("pad", pad(x.text)), *(jg.NULLS if i < NULL_N else ())):
            out.append(Item(
                key=f"{x.key}#{variant}", id=x.id, kind="control", variant=variant, group=x.group,
                split=x.split, shared=x.shared, body=answer_body(text, x.extra["facts"]), text=text,
                extra={"of": x.key},
            ))  # fmt: skip
    return out


def _who(r: dict) -> str:
    return "업체" if r.get("surface") == "vendor" else "고객"


def world_lines(sc: dict, days: int) -> list[str]:
    """시나리오가 대화 전에 만들어 둔 상태 중 시뮬레이터가 실제로 심는 것만(sim/world.py). 날짜는 시뮬레이터처럼 days만큼
    옮겨요. 업체 별점 · 후기 · 빈 반나절은 심지 않아 빼고(2026-11-23 S05 오판), 견적서 기간은 정수 일로 올려 심어서
    똑같이 올려요(S06 오판). 연락처 · 주소는 넣지 않아요."""
    w = simcheck.shift_obj(sc.get("world") or {}, days)
    names = {v.get("ref"): v.get("name") for v in w.get("vendors") or []}
    home = {k: v for k, v in (w.get("home") or {}).items() if v not in (None, "", [])}
    out = []
    if home:  # 비어 있는 칸은 대화에서 채우는 값이에요
        out.append("- 집: " + " · ".join(f"{HOME_KO.get(k, k)} {v}" for k, v in home.items()))
    if (w.get("project") or {}).get("stage"):
        out.append(f"- 공사 단계: {w['project']['stage']}")
    for v in w.get("vendors") or []:
        info = [f"{v.get('gu', '')} · 공정 {v.get('trades')}"] + (
            ["단가 확인함"] if v.get("price_confirmed") else []
        )
        out.append(f"- 업체 {v.get('name')}: " + " · ".join(info))
    for x in w.get("visits") or []:
        q = x.get("quote") or {}
        line = f"- 실측 요청 {names.get(x.get('vendor'), x.get('vendor'))}({x.get('trade')}): {x.get('status')}"
        line += f" · 희망 {x['wish']}" if x.get("wish") else ""
        if q:
            qd = math.ceil(q.get("days") or QUOTE_DAYS)  # sim/world.py가 심는 값(정수 일)
            line += (
                f" · 견적 {q.get('version')}판 {q.get('total')}원(부가세 {q.get('vat')}) · {qd}일"
            )
        out.append(line)
    deals = {d.get("ref"): d for d in w.get("deals") or []}
    for d in deals.values():
        line = f"- 업체 확정 {names.get(d.get('vendor'), d.get('vendor'))}({d.get('trade')}): {d.get('status')}"
        out.append(line + (f" · 공사 {d['start']}~{d.get('end')}" if d.get("start") else ""))
    for p in w.get("date_proposals") or []:
        vendor = names.get((deals.get(p.get("deal")) or {}).get("vendor"), "")
        line = f"- 날짜 제안 {vendor}: {p.get('kind')} · {p.get('status')} · {p.get('start')}~{p.get('end')}"
        out.append(line + (f" · 사유 {p['reason']}" if p.get("reason") else ""))
    return out


def chat_head(sc: dict, r: dict) -> str:
    p = sc.get("persona") or {}
    who = _who(r)
    lines = [
        "## 시나리오(평가 세트)",
        f"제목: {sc.get('title', '')}",
        f"오늘: {r.get('today', '')}",
        f"{who}: {p.get('who', '')} · 목표: {p.get('goal', '')}",
    ]
    if p.get("style"):
        lines.append(f"{who} 말투: {p['style']}")
    if p.get("knows"):
        subj = "업체가" if who == "업체" else "고객이"
        lines.append(f"{subj} 아는 것: " + " · ".join(f"{k} {v}" for k, v in p["knows"].items()))
    state = world_lines(sc, int(r.get("shift_days") or 0))
    if state:
        lines += ["", "## 대화 전 상태(시나리오가 미리 만든 것, 비서도 알고 시작해요)", *state]
    if r.get("notes"):  # 시나리오와 실제로 심은 상태가 다른 점(빈 반나절 · 임시 면적 등)
        lines += [
            "",
            "## 시뮬레이터 메모(위 상태보다 이것이 맞아요)",
            *(f"- {n}" for n in r["notes"]),
        ]
    if sc.get("judge"):
        lines += ["", "## 이 대화에서 특히 볼 것", *(f"- {h}" for h in sc["judge"])]
    return "\n".join(lines)


def timeline(r: dict) -> list[dict]:
    """시뮬레이터 기록 → 차례. {"kind": "before" | "turn" | "screen" | "marks", "n": 말 턴 번호, "turn": 기록, ...}.
    결정 · 바깥 일은 시뮬레이터처럼 대본 글 턴 번호로 묶어 그 묶음의 마지막 기록 뒤에 둬요(sim/run.py: 단추 · 되묻기 턴은
    번호에 안 들고, 턴마다 바깥 일을 먼저 일으킨 뒤 사람이 결정해요. 0번은 대화 전). 누르지 못한 단추 걸음은 빼요."""
    who = _who(r)
    marks: dict[int, list[str]] = defaultdict(list)
    for e in r.get("events") or []:
        marks[int(e.get("after_turn") or 0)].append(f"[일어난 일: {e.get('do')}]")
    for d in r.get("decisions") or []:
        did = {"approve": "승인", "reject": "거절"}.get(d.get("do"), d.get("do"))
        res = STATUS_KO.get(d.get("status") or "") or "반영 안 됨" + (
            f"({d['code']})" if d.get("code") else ""
        )
        marks[int(d.get("turn") or 0)].append(f"[{who}: {d.get('kind')} {did} → {res}]")
    out = [{"kind": "before", "marks": marks[0]}] if marks.get(0) else []
    n = script = 0
    for t in r.get("turns") or []:
        if t.get("kind") == "screen":
            out.append({"kind": "screen", "screen": t.get("screen")})
            continue
        if t.get("kind") == "press":
            continue
        if not t.get("press") and not t.get(
            "ask_for"
        ):  # 대본 글 턴: 앞 묶음의 결정 · 바깥 일을 먼저
            if script and marks.get(script):
                out.append({"kind": "marks", "marks": marks[script]})
            script += 1
        n += 1
        out.append({"kind": "turn", "n": n, "turn": t})
    if script and marks.get(script):
        out.append({"kind": "marks", "marks": marks[script]})
    return out


def turn_lines(t: dict, n: int, who: str, cap: int = TURN_MAX) -> list[str]:
    text = (t.get("text") or "").strip() or "(글 없음)"
    if len(text) > cap:
        text = text[:cap] + " …(생략)"
    said = f"{who}: {t.get('say', '')}"
    if t.get("press"):
        said += f" [카드 단추로 보냄: {t['press'].get('kind')}]"
    lines = [f"### 턴 {n}", said, f"비서: {text}"]
    shown = [f"[카드: {c}]" for c in dict.fromkeys(t.get("cards") or [])]  # 같은 카드는 한 번
    shown += [f"[승인 카드: {x.get('kind')}]" for x in t.get("actions") or []]
    if t.get("turn_status") not in (None, "done"):
        shown.append(f"[턴 {t.get('turn_status')} · {t.get('reason')}]")
    return lines + ([" ".join(shown)] if shown else [])


def chat_body(r: dict) -> str:
    """대화를 한 글로(timeline 차례). 카드 · 승인 카드 · 결정 · 화면 · 일어난 일을 표시로 넣어요."""
    who, out = _who(r), []
    for s in timeline(r):
        if s["kind"] == "before":
            out.append("### 대화 전\n" + "\n".join(s["marks"]))
        elif s["kind"] == "marks":
            out.append("\n".join(s["marks"]))
        elif s["kind"] == "screen":
            out.append(f"[화면: {s['screen']}]")
        else:
            out.append("\n".join(turn_lines(s["turn"], s["n"], who)))
    return "## 대화\n" + "\n\n".join(out) + "\n\n위 대화의 비서 말 전체를 루브릭대로 매겨 주세요."


def load_sims(a) -> list[Item]:
    items = []
    for r in jsonl(a.sims):
        if a.trial is not None and int(r.get("trial", 0)) != a.trial:
            continue
        sc = json.loads((SCEN / f"{r['scenario']}.json").read_text("utf-8"))
        says = [t for t in r.get("turns") or [] if t.get("kind") == "say"]
        items.append(Item(
            key=f"{r['scenario']}#{r.get('trial', 0)}", id=r["scenario"], kind="chat", variant="real",
            group=sc.get("surface") or r.get("surface") or "", split=r.get("split") or sc.get("split") or "",
            shared=chat_head(sc, r), body=chat_body(r), text="\n".join(t.get("text") or "" for t in says),
            extra={"passed": bool(r.get("passed")), "turns": len(says)},
        ))  # fmt: skip
    return items


# ---- 부르기 ----
def stub_grade(x: Item, schema: type[BaseModel]) -> dict:
    """배관 확인용 가짜 점수(유료 호출 없음). 빈 답 · 모름은 1점, 나머지는 씨앗으로 정해요."""
    low = x.variant in ("empty", "dunno")
    dims = CHAT_DIMS if schema is ChatGrade else DIMS
    out: dict = {
        d: {
            "reason": "스텁 점수(유료 호출 없음)",
            "score": 1 if low else (None if d == "numbers" and stable_int(x.key, d) % 3 == 0
                                     else 2 + stable_int("stub", x.key, d) % 4),
        }
        for d in dims
    }  # fmt: skip
    out.update(
        worst="없음", overall_reason="스텁", overall=1 if low else 4 + stable_int("o", x.key) % 6
    )
    if schema is ChatGrade:
        out["worst_turn"] = None
    return schema.model_validate(out).model_dump()


class Grader:
    def __init__(self, a, out: Path, log: CostLog, budget: Budget, system: str):
        self.a, self.out, self.log, self.budget, self.system = a, out, log, budget, system
        self.openai = a.judge.startswith("gpt")
        self.sys_tok = est_tokens(system)
        self.warm = False
        self.fatal: str | None = None
        self.client = None
        if not a.dry_run:  # 실제 실행에서만 SDK를 불러와요
            if self.openai:
                import openai as sdk

                self.client = sdk.OpenAI(max_retries=2, timeout=240.0)
            else:
                import anthropic as sdk

                self.client = sdk.Anthropic(max_retries=2, timeout=240.0)
            self.sdk = sdk

    def estimate(self, x: Item, warm: bool | None = None) -> float:
        warm = self.warm if warm is None else warm
        out = OUT_TOK[x.kind] * (2 if self.openai else 1)  # OpenAI는 생각 토큰이 출력으로 잡혀요
        u = {
            "input": est_tokens(x.shared) + est_tokens(x.body) + 50,
            "cache_write": 0 if warm else self.sys_tok,
            "cache_read": self.sys_tok if warm else 0,
            "output": out,
        }
        return prices.cost_usd(self.a.judge, u) or 0.05

    def call(self, x: Item) -> tuple[dict, dict, dict]:
        schema = ChatGrade if x.kind == "chat" else Grade
        if self.a.dry_run:
            u = {"input": est_tokens(x.shared) + est_tokens(x.body), "output": OUT_TOK[x.kind],
                 "cache_write": 0 if self.warm else self.sys_tok, "cache_read": self.sys_tok if self.warm else 0}  # fmt: skip
            return stub_grade(x, schema), u, {"model": self.a.judge, "stop_reason": "stub"}
        return self._openai(x, schema) if self.openai else self._anthropic(x, schema)

    def _send(self, fn):
        m = self.sdk
        fatal = tuple(
            getattr(m, n)
            for n in ("AuthenticationError", "PermissionDeniedError", "NotFoundError",
                      "PaymentRequiredError", "CredentialsError")
            if hasattr(m, n)
        )  # fmt: skip
        cut = tuple(
            getattr(m, n)
            for n in ("LengthFinishReasonError", "ContentFilterFinishReasonError")
            if hasattr(m, n)
        )
        est = {"input": 0, "cache_write": 0, "cache_read": 0, "output": self.a.max_tokens}
        for attempt in range(1, RETRY + 1):
            try:
                return fn()
            except fatal as e:
                raise jg.Fatal(f"{type(e).__name__}: 키 · 권한 · 모델 · 결제를 확인해요") from e
            except m.BadRequestError as e:
                raise jg.Fatal(f"요청이 거절됐어요(400): {getattr(e, 'message', '')}") from e
            except (m.RateLimitError, m.APIConnectionError, m.InternalServerError) as e:
                if attempt == RETRY:
                    raise jg.CallError("rate_or_server", type(e).__name__) from e
                time.sleep(min(60, 2**attempt + random.random() * 2))
            except m.APIStatusError as e:
                raise jg.CallError(f"api_{e.status_code}", type(e).__name__) from e
            except (*cut, ValidationError) as e:  # 잘림 · 꼴 틀림은 usage를 못 받아 크게 어림해요
                raise jg.CallError(
                    "parse_error", type(e).__name__, est, self.a.judge, estimated=True
                ) from e
        raise jg.CallError("retry", "다시 해도 안 됐어요")

    def _anthropic(self, x: Item, schema) -> tuple[dict, dict, dict]:
        kw = {
            "model": self.a.judge,
            "max_tokens": self.a.max_tokens,
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": x.shared},
                                                       {"type": "text", "text": x.body}]}],
            "output_format": schema,
        }  # fmt: skip
        if self.a.effort:
            kw["output_config"] = {"effort": self.a.effort}
        resp = self._send(lambda: self.client.messages.parse(**kw))
        usage = prices.usage_of(resp.usage)
        meta = {"model": resp.model, "stop_reason": resp.stop_reason,
                "request_id": getattr(resp, "_request_id", None)}  # fmt: skip
        if resp.model != self.a.judge:
            raise jg.Fatal(
                f"부른 모델({self.a.judge})과 답한 모델({resp.model})이 달라요", usage, resp.model
            )
        if resp.parsed_output is None:
            raise jg.CallError(f"no_output:{resp.stop_reason}", "판정 JSON 없음", usage, resp.model)
        return resp.parsed_output.model_dump(), usage, meta

    def _openai(self, x: Item, schema) -> tuple[dict, dict, dict]:
        kw = {
            "model": self.a.judge,
            "instructions": self.system,
            "input": [{"role": "user", "content": f"{x.shared}\n\n{x.body}"}],
            "text_format": schema,
            "reasoning": {"effort": self.a.effort or "low"},
            "max_output_tokens": self.a.max_tokens,
            "store": False,
            "prompt_cache_key": "mitjip-grade",
        }
        resp = self._send(lambda: self.client.responses.parse(**kw))
        u = resp.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        usage = prices.usage_of(
            {"input": u.input_tokens, "cached": cached, "output": u.output_tokens}
        )
        got = str(getattr(resp, "model", "") or "")
        meta = {"model": got, "stop_reason": getattr(resp, "status", None),
                "request_id": getattr(resp, "_request_id", None)}  # fmt: skip
        if not got.startswith(self.a.judge):
            raise jg.Fatal(
                f"부른 모델({self.a.judge})과 답한 모델({got})이 달라요", usage, self.a.judge
            )
        if resp.output_parsed is None:
            raise jg.CallError(
                f"no_output:{meta['stop_reason']}", "판정 JSON 없음", usage, self.a.judge
            )
        return resp.output_parsed.model_dump(), usage, meta

    def run_item(self, x: Item, held: float) -> None:
        spent = 0.0
        try:
            g, usage, meta = self.call(x)
            self.warm = True  # 루브릭 캐시가 생겼어요
            cost = self.log.add(x.key, "grade", self.a.judge, usage, estimated=self.a.dry_run)
            spent += cost or 0
            append_jsonl(self.out / "calls.jsonl", {"key": x.key, "grade": g, "usage": usage, **meta,
                                                     "cost_usd": cost, "estimated": self.a.dry_run})  # fmt: skip
            append_jsonl(self.out / "grades.jsonl", self.row(x, g))
        except jg.CallError as e:
            if e.usage:  # 돈이 나간 실패도 비용에 넣어요
                est = e.estimated or self.a.dry_run
                spent += (
                    self.log.add(x.key, "grade", e.model or self.a.judge, e.usage, estimated=est)
                    or 0
                )
            append_jsonl(self.out / "errors.jsonl", {"key": x.key, "class": e.cls, "message": str(e),
                                                      "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})  # fmt: skip
        except jg.Fatal as e:
            if e.usage:
                spent += (
                    self.log.add(x.key, "fatal", e.model or self.a.judge, e.usage, estimated=False)
                    or 0
                )
            self.fatal = str(e)
        except Exception as e:  # noqa: BLE001 — 도구 버그는 이 항목만 오류로 남기고 계속해요
            append_jsonl(self.out / "errors.jsonl", {"key": x.key, "class": "harness_error",
                                                      "message": f"{type(e).__name__}: {e}"[:300]})  # fmt: skip
        finally:
            self.budget.settle(held, spent)

    def row(self, x: Item, g: dict) -> dict:
        return {
            "key": x.key, "id": x.id, "kind": x.kind, "variant": x.variant, "group": x.group, "split": x.split,
            "chars": len(x.text), "flags": jg.flags(x.text) if x.kind != "chat" else [], "extra": x.extra,
            "grade": g, "judge": self.a.judge, "mode": "dry-run" if self.a.dry_run else "live",
            "rubric": short_hash(self.system),
        }  # fmt: skip


def run(a, g: Grader, items: list[Item], budget: Budget) -> str | None:
    """첫 항목은 혼자 돌려 루브릭 캐시를 데우고, 나머지는 일꾼 여럿. 어림이 상한을 넘으면 새 항목을 멈춰요."""
    stopped = None
    if items:
        est = g.estimate(items[0])
        if not budget.reserve(est):
            return "max_usd"
        g.run_item(items[0], est)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = []
        for x in items[1:]:
            if g.fatal:
                break
            est = g.estimate(x)
            if not budget.reserve(est):
                stopped = "max_usd"
                break
            futs.append(ex.submit(g.run_item, x, est))
        for f in futs:
            f.result()
    return f"fatal: {g.fatal}" if g.fatal else stopped


# ---- 요약 ----
def mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 3) if v else None


def stats(v: list[float]) -> dict:
    return {"n": len(v), "mean": mean(v), "ci": bootstrap_ci(v)}


def ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    out = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    """스피어만 순위 상관(같은 값은 평균 순위)."""
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((p - mx) * (q - my) for p, q in zip(rx, ry, strict=True))
    vx, vy = sum((p - mx) ** 2 for p in rx), sum((q - my) ** 2 for q in ry)
    return round(cov / (vx * vy) ** 0.5, 3) if vx and vy else None


def level(score: int) -> str:
    return next(name for lo, hi, name in LEVELS if lo <= score <= hi)


def dim_scores(rows: list[dict], d: str) -> list[float]:
    return [
        r["grade"][d]["score"]
        for r in rows
        if d in r["grade"] and r["grade"][d]["score"] is not None
    ]


def summarize(rows: list[dict]) -> dict:
    s: dict = {}
    real = [r for r in rows if r["variant"] == "real"]
    for kind, dims in (("answer", DIMS), ("chat", CHAT_DIMS)):
        rs = [r for r in real if r["kind"] == kind]
        if not rs:
            continue
        ov = [r["grade"]["overall"] for r in rs]
        part: dict = {
            "n": len(rs),
            "overall": stats(ov),
            "levels": {name: sum(1 for v in ov if lo <= v <= hi) for lo, hi, name in LEVELS},
            "dims": {d: stats(dim_scores(rs, d)) for d in dims},
            "by_group": {k: stats([r["grade"]["overall"] for r in rs if r["group"] == k])
                         for k in sorted({r["group"] for r in rs})},
            "by_split": {k: stats([r["grade"]["overall"] for r in rs if r["split"] == k])
                         for k in sorted({r["split"] for r in rs})},
            "lowest": [{"key": r["key"], "overall": r["grade"]["overall"], "worst": r["grade"]["worst"]}
                       for r in sorted(rs, key=lambda r: (r["grade"]["overall"], r["key"]))[:8]],
        }  # fmt: skip
        if kind == "answer":
            part["length_bias"] = spearman(
                [r["chars"] for r in rs], ov
            )  # 0에 가까우면 길이와 점수가 따로 놀아요
            part["flags"] = dict(Counter(f for r in rs for f in r.get("flags") or []))
        else:
            part["vs_code"] = {
                "passed": stats([r["grade"]["overall"] for r in rs if r["extra"].get("passed")]),
                "failed": stats(
                    [r["grade"]["overall"] for r in rs if not r["extra"].get("passed")]
                ),
            }
        s[kind] = part
    by_key = {r["key"]: r for r in rows}
    pads = [(r, by_key.get(r["extra"].get("of"))) for r in rows if r["variant"] == "pad"]
    pads = [(p, o) for p, o in pads if o]
    if pads:
        fail = sum(1 for p, o in pads if p["grade"]["overall"] > o["grade"]["overall"])
        s["pad"] = {
            "n": len(pads), "fail": fail, "fail_rate": round(fail / len(pads), 3), "ci": wilson(fail, len(pads)),
            "mean_delta": mean([p["grade"]["overall"] - o["grade"]["overall"] for p, o in pads]),
            "concision_delta": mean([p["grade"]["concision"]["score"] - o["grade"]["concision"]["score"]
                                     for p, o in pads
                                     if p["grade"]["concision"]["score"] and o["grade"]["concision"]["score"]]),
        }  # fmt: skip
    nulls = [r for r in rows if r["variant"] in ("empty", "dunno")]
    if nulls:
        s["null"] = {"n": len(nulls), "ok": sum(1 for r in nulls if r["grade"]["overall"] <= 2),
                     "max": max(r["grade"]["overall"] for r in nulls)}  # fmt: skip
    return s


def agree(x: list[int], y: list[int]) -> dict:
    """같은 항목 두 점수 줄의 일치: 스피어만 · 같은 점수 · ±1 · 수준(3칸) 카파 · 평균 차(x − y)."""
    pairs = list(zip(x, y, strict=True))
    if not pairs:
        return {"n": 0}
    return {
        "n": len(pairs), "spearman": spearman(x, y),
        "exact": round(sum(1 for i, j in pairs if i == j) / len(pairs), 3),
        "within1": round(sum(1 for i, j in pairs if abs(i - j) <= 1) / len(pairs), 3),
        "mean_diff": mean([i - j for i, j in pairs]),
        "kappa_level": cohen_kappa([level(i) for i in x], [level(j) for j in y]),
    }  # fmt: skip


def compare(ra: list[dict], rb: list[dict]) -> dict:
    """두 판정기(같은 항목)의 일치. 평균 차는 이쪽 − 저쪽이에요."""
    other = {r["key"]: r for r in rb}
    pairs = [(r, other[r["key"]]) for r in ra if r["key"] in other]
    if not pairs:
        return {"n": 0}
    out: dict = {}
    for name, ps in (
        ("all", pairs),
        *((k, [p for p in pairs if p[0]["kind"] == k]) for k in ("answer", "chat")),
    ):
        if ps:
            out[name] = agree(
                [p["grade"]["overall"] for p, _ in ps], [q["grade"]["overall"] for _, q in ps]
            )
    out["dims"] = {
        d: mean([p["grade"][d]["score"] - q["grade"][d]["score"] for p, q in pairs
                 if d in p["grade"] and p["grade"][d]["score"] and q["grade"][d]["score"]])
        for d in CHAT_DIMS
    }  # fmt: skip
    out["far"] = [{"key": p["key"], "this": p["grade"]["overall"], "other": q["grade"]["overall"]}
                  for p, q in pairs if abs(p["grade"]["overall"] - q["grade"]["overall"]) >= 3][:10]  # fmt: skip
    return out


HUMAN = ("번호", "종류", "질문 · 자료", "답 · 대화", "종합(1~10)", "가장 큰 문제(적고 싶으면)")


def human_sample(a, out: Path, rows: list[dict], items: dict[str, Item]) -> Path:
    """사람 확인 표본(Zheng et al. 4절 사람과의 일치): 판정기 수준(3칸)을 돌아가며 N개(씨앗 고정).
    사람 파일에는 판정기 점수를 넣지 않고 열쇠 파일에만 둬요. 기준은 rubric_single.md."""
    pool: dict[str, list[dict]] = defaultdict(list)
    real = [r for r in rows if r["variant"] == "real" and r["key"] in items]
    for r in sorted(real, key=lambda r: stable_int(a.seed, "human", r["key"])):
        pool[level(r["grade"]["overall"])].append(r)
    picked: list[dict] = []
    while len(picked) < a.human and any(pool.values()):
        for _, _, name in LEVELS:
            if pool[name] and len(picked) < a.human:
                picked.append(pool[name].pop(0))
    path = out / f"human_{a.human}.csv"
    with (
        path.open("w", encoding="utf-8-sig", newline="") as f,
        path.with_name(f"{path.stem}_key.csv").open("w", encoding="utf-8-sig", newline="") as k,
    ):
        w, wk = csv.writer(f), csv.writer(k)
        w.writerow(HUMAN)
        wk.writerow(("번호", "key", "판정기", "판정기 종합"))
        for i, r in enumerate(picked, 1):
            x = items[r["key"]]
            w.writerow((i, "대화" if x.kind == "chat" else "답", x.shared, x.body, "", ""))
            wk.writerow((i, r["key"], r["judge"], r["grade"]["overall"]))
    return path


def read_csv_any(path: Path) -> list[dict]:
    """엑셀이 'CSV UTF-8'이 아닌 꼴로 저장해도 읽어요."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{path.name}을 읽지 못했어요(UTF-8 · CP949가 아니에요)")


def human_agree(path: Path, rows: list[dict]) -> dict:
    """채운 사람 파일과 이 판정기의 일치. 평균 차는 판정기 − 사람이에요."""
    keys = {r["번호"]: r["key"] for r in read_csv_any(path.with_name(f"{path.stem}_key.csv"))}
    by = {r["key"]: r["grade"]["overall"] for r in rows}
    x, y = [], []
    for h in read_csv_any(path):
        v, k = (h.get(HUMAN[4]) or "").strip(), keys.get(h.get("번호", ""))
        if v.isdigit() and 1 <= int(v) <= 10 and k in by:
            x.append(by[k])
            y.append(int(v))
    return {"file": path.name, **agree(x, y)}


def _m(st: dict) -> str:
    if not st or st.get("mean") is None:
        return "-"
    ci = st.get("ci")
    return f"{st['mean']:.2f}" + (f"({ci[0]:.2f}~{ci[1]:.2f})" if ci else "") + f" n={st['n']}"


def report(s: dict) -> str:
    lines = []
    for kind, name in (("answer", "답"), ("chat", "대화")):
        p = s.get(kind)
        if not p:
            continue
        lv = " · ".join(f"{k} {v}" for k, v in p["levels"].items())
        lines.append(f"{name} {p['n']}개 · 종합 {_m(p['overall'])} · {lv}")
        lines.append(
            "  차원: " + " · ".join(f"{DIM_KO[d]} {p['dims'][d]['mean']}" for d in p["dims"])
        )
        lines.append("  묶음: " + " · ".join(f"{k} {_m(v)}" for k, v in p["by_group"].items()))
        lines.append("  나눔: " + " · ".join(f"{k} {_m(v)}" for k, v in p["by_split"].items()))
        if kind == "answer":
            lines.append(
                f"  길이와 점수 순위 상관 ρ={p['length_bias']} · 코드 표시 {p['flags'] or '없음'}"
            )
        else:
            vc = p["vs_code"]
            lines.append(f"  코드 점검 통과 {_m(vc['passed'])} · 실패 {_m(vc['failed'])}")
        for r in p["lowest"][:5]:
            lines.append(f"  낮음 {r['key']} {r['overall']}점: {r['worst']}")
    if "pad" in s:
        p = s["pad"]
        lines.append(
            f"길이 편향(되풀이 붙인 판이 더 높음) {p['fail']}/{p['n']} = {p['fail_rate']} (95% {p['ci']}) · "
            f"종합 변화 평균 {p['mean_delta']} · 간결 변화 {p['concision_delta']}"
        )
    if "null" in s:
        p = s["null"]
        lines.append(f"빈 답 · 모름 {p['ok']}/{p['n']}이 2점 이하(가장 높은 점수 {p['max']})")
    c = s.get("compare")
    if c:
        for k in ("all", "answer", "chat"):
            if k in c:
                v = c[k]
                lines.append(
                    f"판정기 비교({c['with']} · {k}) n={v['n']} · ρ={v['spearman']} · 같은 점수 {v['exact']} · "
                    f"±1 {v['within1']} · 수준 κ={v['kappa_level']} · 평균 차 {v['mean_diff']}"
                )
    h = s.get("human")
    if h and h.get("n"):
        lines.append(
            f"사람과 일치({h['file']}) n={h['n']} · ρ={h['spearman']} · 같은 점수 {h['exact']} · "
            f"±1 {h['within1']} · 수준 κ={h['kappa_level']} · 판정기 − 사람 {h['mean_diff']}"
        )
    if "cost" in s:
        lines.append(
            f"비용 ${s['cost']['usd']:.4f}(실제 ${s['cost']['real_usd']:.4f}) · 멈춤 {s['cost']['stopped']}"
        )
    return "\n".join(lines)


# ---- 실행 ----
def load_key(a) -> None:
    name = "OPENAI_API_KEY" if a.judge.startswith("gpt") else "ANTHROPIC_API_KEY"
    if os.environ.get(name):
        return
    if a.env_file.exists():
        for line in a.env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].split(" #")[0].strip().strip('"').strip("'")
                if value:
                    os.environ[name] = value
                    return
    sys.exit(f"{name}가 없어요(환경변수나 --env-file)")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="한 답 점수 판정기(유료는 --live)")
    ap.add_argument("--tag", required=True)
    ap.add_argument(
        "--live", action="store_true", help="실제 판정(유료). 없으면 가짜 점수로 배관만 봐요"
    )
    ap.add_argument("--answers", type=Path, help="run_v4_answers.py의 answers.jsonl")
    ap.add_argument("--system", default="v4_default_g", help="답 파일에서 매길 시스템")
    ap.add_argument("--set", type=Path, default=SETS / "compare.jsonl")
    ap.add_argument(
        "--controls", type=int, default=0, help="pad 대조군 수(앞 3개는 빈 답 · 모름도)"
    )
    ap.add_argument("--sims", type=Path, help="sim/run.py의 sim.jsonl")
    ap.add_argument("--trial", type=int, help="시뮬레이터 결과에서 이 trial만")
    ap.add_argument("--judge", default="claude-opus-5-5")
    ap.add_argument(
        "--effort", help="Claude output_config effort · OpenAI reasoning effort(기본 low)"
    )
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--max-usd", type=float)
    ap.add_argument(
        "--allow-partial", action="store_true", help="어림이 상한을 넘어도 넘기 전까지만 돌려요"
    )
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261123)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--report", action="store_true", help="판정 없이 이 --tag 요약만 다시 만들어요")
    ap.add_argument("--compare", help="같은 항목을 매긴 다른 판정기 tag")
    ap.add_argument("--human", type=int, help="--report와 함께: 사람 확인 표본 N개 CSV를 만들어요")
    ap.add_argument(
        "--human-file", type=Path, help="--report와 함께: 채운 사람 CSV(열쇠는 옆 _key.csv)"
    )
    a = ap.parse_args(argv)
    if a.judge not in prices.PRICES:
        ap.error(f"가격표에 없는 판정기예요: {a.judge}")
    if a.live and not a.max_usd:
        ap.error("--live에는 --max-usd가 필요해요")
    if not a.report and not (a.answers or a.sims):
        ap.error("--answers나 --sims가 필요해요")
    a.dry_run = not a.live
    return a


def finish(a, out: Path, extra: dict) -> dict:
    rows = jsonl(out / "grades.jsonl") if (out / "grades.jsonl").exists() else []
    s = summarize(rows)
    if a.compare:
        s["compare"] = {
            "with": a.compare,
            **compare(rows, jsonl(RUNS / a.compare / "grades.jsonl")),
        }
    if a.human_file:
        s["human"] = human_agree(a.human_file, rows)
    s.update(extra)
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report(s))
    return s


def main(argv=None) -> int:
    utf8_stdout()
    a = parse_args(argv)
    out = RUNS / a.tag
    if a.report:
        old = (
            json.loads((out / "summary.json").read_text("utf-8"))
            if (out / "summary.json").exists()
            else {}
        )
        keep = (
            ("cost",) if a.human_file else ("cost", "human")
        )  # 새 사람 파일이면 사람 일치는 다시 셈해요
        s = finish(a, out, {k: old[k] for k in keep if k in old})
        if a.human:
            meta = json.loads((out / "meta.json").read_text("utf-8"))
            a.set = Path(meta.get("set") or a.set)
            a.answers = Path(meta["answers"]) if meta.get("answers") else None
            a.sims = Path(meta["sims"]) if meta.get("sims") else None
            a.system, a.trial = meta.get("system", a.system), meta.get("trial")
            items = (load_answers(a) if a.answers else []) + (load_sims(a) if a.sims else [])
            path = human_sample(a, out, jsonl(out / "grades.jsonl"), {x.key: x for x in items})
            print(f"사람 확인 표본: {path} (열쇠 {path.stem}_key.csv는 채우는 사람이 열지 않아요)")
        return 0 if s else 1
    items: list[Item] = []
    if a.answers:
        base = load_answers(a)
        items += base + (controls(base, a.controls, a.seed) if a.controls else [])
    if a.sims:
        items += load_sims(a)
    items = items[: a.limit] if a.limit else items
    if not items:
        sys.exit("매길 항목이 없어요(--system · --trial을 확인해요)")
    system = RUBRIC_PATH.read_text("utf-8")
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "tag": a.tag, "judge": a.judge, "effort": a.effort, "mode": "dry-run" if a.dry_run else "live",
        "rubric": short_hash(system), "answers": str(a.answers or ""), "set": str(a.set), "system": a.system,
        "sims": str(a.sims or ""),
        "trial": a.trial, "controls": a.controls, "items": len(items), "head": jg._git("rev-parse", "HEAD"),
    }  # fmt: skip
    meta_path = out / "meta.json"
    old = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else None
    if old and any(old.get(k) != meta[k] for k in ("judge", "mode", "rubric")):
        sys.exit(f"{out}는 다른 판정기 · 모드 · 루브릭으로 돈 결과예요. 새 --tag를 써요")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.live:
        load_key(a)
    log = CostLog(out / "cost.csv", "grade")
    budget = Budget(a.max_usd, log.spent)
    g = Grader(a, out, log, budget, system)
    done = (
        {r["key"] for r in jsonl(out / "grades.jsonl")}
        if (out / "grades.jsonl").exists()
        else set()
    )
    todo = [x for x in items if x.key not in done]
    est = sum(g.estimate(x, warm=i > 0) for i, x in enumerate(todo))
    print(
        f"판정기 {a.judge} · 매길 것 {len(todo)}개(이미 {len(done)}개) · 어림 ${est:.3f} · 상한 {a.max_usd}"
    )
    if a.max_usd and log.spent + est > a.max_usd and not a.allow_partial:
        print("어림이 상한을 넘어 시작하지 않아요(--allow-partial이면 넘기 전까지만)")
        return 2
    stopped = run(a, g, todo, budget)
    finish(
        a,
        out,
        {"cost": {"usd": round(log.spent, 4), "real_usd": round(log.real, 4), "stopped": stopped}},
    )
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())

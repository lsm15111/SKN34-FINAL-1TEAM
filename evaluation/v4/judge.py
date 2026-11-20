"""쌍대 판정기: 같은 질문의 두 답(A · B)을 순서를 바꿔 두 번 판정하고, 두 번 모두 같은 쪽일 때만 승이에요(아니면 무승부).

    cd backend
    uv run python ../evaluation/v4/judge.py --dry-run --answers ../evaluation/v4/runs/dry1/answers.jsonl --tag dry1-judge
    uv run python ../evaluation/v4/judge.py --dry-run --controls 2 --tag dry-ctl          # 판정기 점검(대조군)
    uv run --with anthropic python ../evaluation/v4/judge.py --answers <답 파일> --tag j1 --max-usd 5   # 유료 · 리드 허락 뒤

- 차원: 정확 · 근거 · 유용 · 간결 · 안전 · 숫자 일치 + 종합. 차원마다 이유를 먼저 쓰고 고르며 unknown을 허용해요(rubric.md)
- 판정기 지시문은 rubric.md 전체예요(사람이 보는 루브릭과 같은 글). 판 번호 대신 글 해시를 결과에 남겨요
- 라벨을 숨겨요: 판정기는 '답 1 · 답 2'만 봐요. 첫 순서는 씨앗 고정 난수로 정하고 두 번째는 뒤집어요
- 기준 답: ChatGPT 참고 답(core32) · 정답 조각(set30) · 기대 행동(모든 질문). 답마다 그 답이 받은 계산 값(숫자 일치용)
- 출력: Pydantic(Verdict) + messages.parse. 결과는 runs/<tag>/
  - judgments.jsonl: 질문 하나 = 한 줄(차원별 두 순서 판정 · 최종 · 일관성 · 코드 점검 표시)
  - calls.jsonl(호출마다 원문 판정 · usage) · cost.csv(호출마다 토큰 · 비용, 스텁은 estimated=1) · errors.jsonl
  - summary.json(차원별 승 · 무 · 위치 일관성 · B 승률 구간 · 출처별) · meta.json
- 상한 --max-usd: 시작 전 어림이 넘으면 시작하지 않아요(--allow-partial이면 넘기 전까지만). 돌다가 넘을 것 같으면 새 질문을 멈춰요
- 이어 하기: 같은 --tag면 judgments.jsonl에 있는 질문은 건너뛰어요. 모드 · 모델 · 루브릭이 다르면 멈춰요
- 키: 환경변수 ANTHROPIC_API_KEY 또는 --env-file의 그 한 줄만 읽어요(값은 찍지 않아요). --dry-run은 SDK도 불러오지 않아요
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import budget as bud
import prices
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

RUBRIC_PATH = HERE / "rubric.md"
MODEL = "claude-opus-5-5"
DIMS = ("accuracy", "grounding", "usefulness", "concision", "safety", "numbers")
ALL = (*DIMS, "overall")
DIM_KO = {
    "accuracy": "정확", "grounding": "근거", "usefulness": "유용", "concision": "간결",
    "safety": "안전", "numbers": "숫자 일치", "overall": "종합",
}  # fmt: skip
ANSWER_MAX = 5000  # 답 글자 상한(넘으면 잘라서 판정, 표시)
FACTS_MAX = 3000
REF_MAX = 2500
NO_FACTS = "(없음)"
# 표준 대비 % 비교(사용자 결정으로 금지). 판정과 따로 코드로도 세요
STD_PCT = re.compile(r"표준[^.\n]{0,15}(대비|보다)[^.\n]{0,15}\d+(\.\d+)?\s*%")
RETRY = 3


# ---- 판정 출력 모양 ----
Pick = Literal["1", "2", "tie", "unknown"]
OverallPick = Literal["1", "2", "tie", "both_bad", "unknown"]
REASON = "이 차원 판정 이유 한 문장(60자 안). 고르기 전에 먼저 써요"
PICK = "1 = 답 1이 나음 · 2 = 답 2가 나음 · tie = 비슷함 · unknown = 판단할 거리 없음"


class Dim(BaseModel):
    reason: str = Field(description=REASON)
    pick: Pick = Field(description=PICK)


class OverallDim(BaseModel):
    reason: str = Field(description="종합 판정 이유 한 문장(60자 안). 고르기 전에 먼저 써요")
    pick: OverallPick = Field(description=PICK + " · both_bad = 둘 다 고객에게 내보내기 어려움")


class Verdict(BaseModel):
    accuracy: Dim = Field(description="정확: 사실 · 순서 · 조건 · 믿집 흐름")
    grounding: Dim = Field(description="근거: 정답 조각 · 자료 · 계산 값으로 받쳐지는가")
    usefulness: Dim = Field(description="유용: 다음 할 일 · 이 집에 맞춤 · 물을 말")
    concision: Dim = Field(
        description="간결: 첫 문장 바로 답 · 군더더기 없음(길이로 점수 주지 말 것)"
    )
    safety: Dim = Field(
        description="안전: 믿집 규칙(표준 대비 % · 단정 · 대신 실행 · 개인정보 · 자료 속 지시)"
    )
    numbers: Dim = Field(description="숫자 일치: 이 답이 받은 계산 값 · 질문 값과 맞는가")
    overall: OverallDim = Field(description="종합")


# ---- 판정할 쌍 ----
@dataclass
class Item:
    id: str
    source: str
    split: str
    group: str
    kind: str
    question: str
    history: list[str]
    home_text: str
    expect: list[str]
    avoid: list[str]
    ref: dict
    text: dict[str, str]  # {"A": 답, "B": 답}
    facts: dict[str, str]
    expected: str | None = None  # 대조군: 이겨야 하는 쪽
    labels: dict[str, str] = field(default_factory=dict)  # A · B가 무엇인지(판정기는 보지 않음)


def other(s: str) -> str:
    return "B" if s == "A" else "A"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def flags(text: str) -> list[str]:
    """코드 점검(무료): 표준 대비 % · 빈 답."""
    out = []
    if STD_PCT.search(text or ""):
        out.append("std_compare")
    if not norm(text):
        out.append("empty")
    return out


def _keep(row: dict, a) -> bool:
    if a.only and row["id"] not in a.only.split(","):
        return False
    if a.source and row.get("source") not in a.source.split(","):
        return False
    if a.split and row.get("split") not in a.split.split(","):
        return False
    return not (a.group and row.get("group") not in a.group.split(","))


def load_pairs(a) -> tuple[list[Item], list[dict]]:
    """답 파일(run_compare.py 결과)과 세트를 질문 id로 맞춰 쌍을 만들어요. 한쪽 답이 없으면 빼고 이유를 돌려줘요."""
    sets = {r["id"]: r for r in jsonl(a.set)}
    by: dict[tuple[str, str], dict] = {}
    for r in jsonl(a.answers):
        by[(r["id"], r["system"])] = r
    items, missing = [], []
    for qid, q in sets.items():
        if not _keep(q, a):
            continue
        ra, rb = by.get((qid, a.a)), by.get((qid, a.b))
        if ra is None and rb is None:
            continue
        bad = [s for s, r in ((a.a, ra), (a.b, rb)) if r is None or r.get("error")]
        if bad:
            missing.append(
                {"id": qid, "class": "missing_answer", "message": f"답 없음 · 오류: {bad}"}
            )
            continue
        items.append(Item(
            id=qid, source=q["source"], split=q["split"], group=q["group"], kind=q.get("kind", ""),
            question=q["turns"][-1], history=q["turns"][:-1], home_text=ra.get("home_text") or "",
            expect=q.get("expect", []), avoid=q.get("avoid", []), ref=q.get("ref", {}),
            text={"A": ra["text"], "B": rb["text"]},
            facts={"A": ra.get("facts_given") or NO_FACTS, "B": rb.get("facts_given") or NO_FACTS},
            labels={"A": a.a, "B": a.b},
        ))  # fmt: skip
    if a.limit:
        items = items[: a.limit]
    return items, missing


NULLS = (("empty", ""), ("dunno", "잘 모르겠어요."))


def load_controls(a) -> list[Item]:
    """판정기 점검용 대조군: A = 참고 답(ChatGPT), B = 빈 답 · '모르겠어요' · 다른 질문의 답. A가 이겨야 해요."""
    pool = [r for r in jsonl(a.set) if (r.get("ref") or {}).get("gpt")]
    rnd = random.Random(a.seed)
    rnd.shuffle(pool)
    picked = pool[: a.controls]
    items = []
    for i, q in enumerate(picked):
        good = q["ref"]["gpt"][:1500]
        wrong = pool[(i + len(pool) // 2) % len(pool)]["ref"]["gpt"][:1500]
        ref = {**q["ref"], "gpt": ""}
        for name, bad in (*NULLS, ("wrong_q", wrong)):
            items.append(Item(
                id=f"ctl:{q['src_id']}:{name}", source="control", split="control", group=name,
                kind=q.get("kind", ""), question=q["turns"][-1], history=[], home_text="집 정보 없음",
                expect=q.get("expect", []), avoid=q.get("avoid", []), ref=ref,
                text={"A": good, "B": bad}, facts={"A": NO_FACTS, "B": NO_FACTS}, expected="A",
                labels={"A": "참고 답", "B": f"대조({name})"},
            ))  # fmt: skip
    return items


# ---- 판정 글 ----
def shared_block(x: Item) -> str:
    """두 순서가 같이 쓰는 앞부분(캐시 표시를 붙여요): 질문 · 집 · 기대 · 정답 조각 · 참고 답."""
    lines = ["## 고객 질문"]
    if x.history:
        lines += ["앞 대화(고객 말):", *(f"- {h}" for h in x.history), "마지막 말:"]
    lines += [
        x.question,
        "",
        "## 이 고객의 집(두 답이 같은 집 조건을 받았어요)",
        x.home_text or "집 정보 없음",
    ]
    if x.expect or x.avoid:
        lines += ["", "## 이 질문에서 기대하는 것(평가 세트)"]
        lines += [f"- 해야 할 것: {e}" for e in x.expect]
        lines += [f"- 피할 것: {e}" for e in x.avoid]
    gold = x.ref.get("gold") or []
    if gold:
        lines += ["", "## 정답 조각(믿집 자료)"]
        for g in gold:
            head = " · ".join(v for v in (g.get("ref"), g.get("title")) if v)
            lines.append(f"- [{head}] {g.get('text') or g.get('why', '')}")
    if x.ref.get("gpt"):
        cut = " · 뒤 잘림" if x.ref.get("gpt_cut") else ""
        lines += [
            "",
            f"## 참고 답(ChatGPT · 정답 아님 · 집 사실 모름{cut})",
            x.ref["gpt"][:REF_MAX],
        ]
    if x.ref.get("note"):
        lines += ["", f"메모: {x.ref['note']}"]
    return "\n".join(lines)


def answer_block(i: int, text: str, facts: str) -> str:
    body = (text or "").strip() or "(빈 답)"
    cut = ""
    if len(body) > ANSWER_MAX:
        cut = f"\n(이하 {len(body) - ANSWER_MAX}자 생략)"
        body = body[:ANSWER_MAX]
    return f"## 답 {i}\n<answer_{i}>\n{body}{cut}\n</answer_{i}>\n이 답이 받은 계산 값: {(facts or NO_FACTS)[:FACTS_MAX]}"


def answers_block(x: Item, first: str) -> str:
    s1, s2 = first, other(first)
    return "\n\n".join([
        answer_block(1, x.text[s1], x.facts[s1]),
        answer_block(2, x.text[s2], x.facts[s2]),
        "위 두 답을 루브릭대로 차원마다 견줘 주세요.",
    ])  # fmt: skip


# ---- 순서 두 번 → 최종 ----
def to_system(pick: str, first: str) -> str:
    return {"1": first, "2": other(first)}.get(pick, pick)


def combine(p1: str, first1: str, p2: str, first2: str) -> dict:
    """두 순서의 판정을 시스템(A · B)으로 옮겨, 같으면 그대로 · 다르면 무승부(tie)."""
    m1, m2 = to_system(p1, first1), to_system(p2, first2)
    return {"raw": [p1, p2], "order1": m1, "order2": m2, "final": m1 if m1 == m2 else "tie",
            "consistent": m1 == m2}  # fmt: skip


def judgment_row(x: Item, first: str, verdicts: list[dict], meta: dict) -> dict:
    dims = {}
    for d in ALL:
        c = combine(verdicts[0][d]["pick"], first, verdicts[1][d]["pick"], other(first))
        c["reasons"] = [verdicts[0][d]["reason"], verdicts[1][d]["reason"]]
        dims[d] = c
    return {**_head(x), "order1_first": first, "dims": dims, "auto": None, **meta}


def same_row(x: Item, meta: dict) -> dict:
    """두 답 글이 같으면 부르지 않고 모든 차원 무승부."""
    dims = {d: {"raw": ["tie", "tie"], "order1": "tie", "order2": "tie", "final": "tie", "consistent": True,
                "reasons": ["같은 글", "같은 글"]} for d in ALL}  # fmt: skip
    return {**_head(x), "order1_first": "A", "dims": dims, "auto": "same_text", **meta}


def _head(x: Item) -> dict:
    return {
        "id": x.id, "source": x.source, "split": x.split, "group": x.group, "kind": x.kind,
        "labels": x.labels, "expected": x.expected, "question": x.question, "home_text": x.home_text,
        "texts": x.text, "facts": x.facts, "flags": {"A": flags(x.text["A"]), "B": flags(x.text["B"])},
    }  # fmt: skip


# ---- 부르기(스텁 · 실제) ----
class Fatal(Exception):
    """키 · 권한 · 모델 · 요청 모양 오류처럼 다시 해도 안 되는 것. 전체를 멈춰요(돈이 나간 호출이면 usage를 같이 남겨요)."""

    def __init__(self, msg: str, usage: dict | None = None, model: str | None = None):
        super().__init__(msg)
        self.usage, self.model = usage, model


class CallError(Exception):
    """이 질문만 실패. usage가 있으면 비용에 넣어요(estimated = 응답 usage가 없어 어림한 값)."""

    def __init__(
        self, cls: str, msg: str, usage: dict | None = None, model: str | None = None,
        estimated: bool = False,
    ):  # fmt: skip
        super().__init__(msg)
        self.cls, self.usage, self.model, self.estimated = cls, usage, model, estimated


STUB_P = (
    ("1", 40),
    ("2", 35),
    ("tie", 18),
    ("unknown", 7),
)  # 위치 1 쪽으로 조금 기운 가짜 분포(배관 확인용)


def first_of(x: Item, seed: int) -> str:
    """순서 1에서 '답 1'이 될 쪽(씨앗 고정). 순서 2는 뒤집어요."""
    return "A" if stable_int(seed, x.id) % 2 == 0 else "B"


def item_estimate(x: Item, a, sys_tok: int, warm: bool = True) -> float:
    """쌍 하나(두 순서) 어림 비용. 같은 글이면 부르지 않아 0이에요."""
    if norm(x.text["A"]) == norm(x.text["B"]):
        return 0.0
    first = first_of(x, a.seed)
    shared = est_tokens(shared_block(x))
    a1 = est_tokens(answers_block(x, first))
    a2 = est_tokens(answers_block(x, other(first)))
    return bud.judge_item_usd(a.model, sys_tok, shared, a1, a2, warm=warm)


def stub_verdict(x: Item, order: int) -> dict:
    out = {}
    for d in ALL:
        r, acc, pick = stable_int("stub", x.id, order, d) % 100, 0, "tie"
        for p, w in STUB_P:
            acc += w
            if r < acc:
                pick = p
                break
        out[d] = {"reason": "스텁 판정(유료 호출 없음)", "pick": pick}
    return Verdict.model_validate(out).model_dump()


class Judge:
    def __init__(self, a, out: Path, log: CostLog, budget: Budget, system: str):
        self.a, self.out, self.log, self.budget, self.system = a, out, log, budget, system
        self.sys_tok = est_tokens(system)
        self.warm = False
        self.lock = threading.Lock()
        self.fatal: str | None = None
        self.client = None
        if not a.dry_run:
            import anthropic  # 실제 실행에서만 불러와요

            self.anthropic = anthropic
            self.client = anthropic.Anthropic(max_retries=2, timeout=180.0)

    def item_estimate(self, x: Item) -> float:
        return item_estimate(x, self.a, self.sys_tok, self.warm)

    def first(self, x: Item) -> str:
        return first_of(x, self.a.seed)

    def call(self, x: Item, order: int, shared: str, answers: str) -> tuple[dict, dict, dict]:
        if self.a.dry_run:
            with self.lock:
                warm, self.warm = self.warm, True
            usage = bud.judge_call_usage(
                self.sys_tok, est_tokens(shared), est_tokens(answers), order, warm,
                bud.JUDGE_OUT.get(self.a.model, 1800),
            )  # fmt: skip
            return stub_verdict(x, order), usage, {"model": self.a.model, "stop_reason": "stub"}
        return self._live(shared, answers)

    def _live(self, shared: str, answers: str) -> tuple[dict, dict, dict]:
        ant = self.anthropic
        kw = {
            "model": self.a.model,
            "max_tokens": self.a.max_tokens,
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": shared, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": answers},
            ]}],
            "output_format": Verdict,
        }  # fmt: skip
        if self.a.effort:
            kw["output_config"] = {"effort": self.a.effort}
        for attempt in range(1, RETRY + 1):
            try:
                resp = self.client.messages.parse(**kw)
                break
            except (
                ant.AuthenticationError, ant.PermissionDeniedError, ant.NotFoundError,
                ant.PaymentRequiredError, ant.CredentialsError,
            ) as e:  # fmt: skip
                raise Fatal(f"{type(e).__name__}: 키 · 권한 · 모델 · 결제를 확인해요") from e
            except ant.BadRequestError as e:
                raise Fatal(f"요청이 거절됐어요(400): {e.message}") from e
            except (ant.RateLimitError, ant.APIConnectionError, ant.InternalServerError) as e:
                if attempt == RETRY:  # SDK 재시도(2번) 뒤에도 실패하면 이 질문만 오류로 남겨요
                    raise CallError("rate_or_server", type(e).__name__) from e
                time.sleep(min(60, 2**attempt + random.random() * 2))  # 흔들림 있는 물러서기
            except ant.APIStatusError as e:
                raise CallError(f"api_{e.status_code}", type(e).__name__) from e
            except ValidationError as e:
                # 모양이 틀린 JSON(잘림 등)은 응답 usage를 못 받아요. 출력 상한만큼 나갔다고 크게 어림해요
                est = {"input": 0, "cache_write": 0, "cache_read": 0, "output": self.a.max_tokens}
                raise CallError(
                    "parse_error", str(e)[:200], est, self.a.model, estimated=True
                ) from e
        usage = prices.usage_of(resp.usage)
        meta = {
            "model": resp.model,
            "stop_reason": resp.stop_reason,
            "request_id": getattr(resp, "_request_id", None),
        }
        if resp.model != self.a.model:  # 다른 모델이 답하면 비교가 깨져요
            raise Fatal(
                f"부른 모델({self.a.model})과 답한 모델({resp.model})이 달라요", usage, resp.model
            )
        v = resp.parsed_output
        if v is None:
            raise CallError(f"no_output:{resp.stop_reason}", "판정 JSON 없음", usage, resp.model)
        return v.model_dump(), usage, meta

    def run_item(self, x: Item, held: float) -> None:
        spent = 0.0
        try:
            if norm(x.text["A"]) == norm(x.text["B"]):
                append_jsonl(self.out / "judgments.jsonl", same_row(x, self.meta()))
                return
            first = self.first(x)
            shared = shared_block(x)
            verdicts = []
            for order, f in ((1, first), (2, other(first))):
                answers = answers_block(x, f)
                try:
                    v, usage, meta = self.call(x, order, shared, answers)
                except CallError as e:
                    if e.usage:  # 돈이 나간 실패도 비용에 넣어요
                        est = e.estimated or self.a.dry_run
                        spent += (
                            self.log.add(x.id, f"order{order}", e.model, e.usage, estimated=est)
                            or 0
                        )
                    append_jsonl(self.out / "errors.jsonl", {
                        "id": x.id, "order": order, "class": e.cls, "message": str(e), "model": e.model,
                        "usage": e.usage, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    })  # fmt: skip
                    return
                self.warm = True  # 루브릭(system) 캐시가 생겼어요. 다음 어림은 캐시 읽기로 셈해요
                cost = self.log.add(
                    x.id, f"order{order}", meta["model"], usage, estimated=self.a.dry_run
                )
                spent += cost or 0
                append_jsonl(self.out / "calls.jsonl", {
                    "id": x.id, "order": order, "first": f, "verdict": v, "usage": usage, **meta,
                    "cost_usd": cost, "estimated": self.a.dry_run,
                })  # fmt: skip
                verdicts.append(v)
            append_jsonl(
                self.out / "judgments.jsonl", judgment_row(x, first, verdicts, self.meta())
            )
        except Fatal as e:
            if e.usage:
                spent += self.log.add(x.id, "fatal", e.model, e.usage, estimated=False) or 0
            self.fatal = str(e)
        except Exception as e:  # noqa: BLE001 — 도구 버그는 이 질문만 오류로 남기고 계속해요
            append_jsonl(self.out / "errors.jsonl", {
                "id": x.id, "class": "harness_error", "message": f"{type(e).__name__}: {e}"[:300],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })  # fmt: skip
        finally:
            self.budget.settle(held, spent)

    def meta(self) -> dict:
        return {"model": self.a.model, "mode": "dry-run" if self.a.dry_run else "live",
                "rubric": short_hash(self.system)}  # fmt: skip


# ---- 요약 ----
def score_b(final: str) -> float | None:
    return {"B": 1.0, "A": 0.0, "tie": 0.5, "both_bad": 0.5}.get(final)


def win_stats(rows: list[dict], dim: str) -> dict:
    fin = Counter(r["dims"][dim]["final"] for r in rows)
    scores = [s for r in rows if (s := score_b(r["dims"][dim]["final"])) is not None]
    cons = sum(r["dims"][dim]["consistent"] for r in rows)
    decided = fin["A"] + fin["B"]
    return {
        "n": len(rows), "A": fin["A"], "B": fin["B"], "tie": fin["tie"], "both_bad": fin["both_bad"],
        "unknown": fin["unknown"],
        "b_win_rate": round(sum(scores) / len(scores), 3) if scores else None,  # 무승부는 반
        "b_win_rate_ci95": bootstrap_ci(scores),
        "b_win_of_decided": round(fin["B"] / decided, 3) if decided else None,
        "consistency": round(cons / len(rows), 3) if rows else None,
        "consistency_ci95": wilson(cons, len(rows)),
    }  # fmt: skip


def summarize(rows: list[dict]) -> dict:
    judged = [r for r in rows if r.get("auto") is None]
    picks = Counter(p for r in judged for d in ALL for p in r["dims"][d]["raw"] if p in ("1", "2"))
    n12 = picks["1"] + picks["2"]
    out: dict = {
        "n": len(rows), "auto_same_text": len(rows) - len(judged),
        "labels": rows[0]["labels"] if rows else {},
        "dims": {d: win_stats(rows, d) for d in ALL},
        "consistency_all": round(
            sum(r["dims"][d]["consistent"] for r in judged for d in ALL) / (len(judged) * len(ALL)), 3
        ) if judged else None,
        "position_first_share": round(picks["1"] / n12, 3) if n12 else None,  # 0.5에서 멀면 위치 편향
        "position_ci95": wilson(picks["1"], n12),
        "flags": {s: dict(Counter(f for r in rows for f in r["flags"][s])) for s in ("A", "B")},
    }  # fmt: skip
    for key in ("source", "split", "group"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        out[f"overall_by_{key}"] = {k: win_stats(v, "overall") for k, v in sorted(groups.items())}
    ctl = [r for r in rows if r.get("expected")]
    if ctl:
        ok = sum(r["dims"]["overall"]["final"] == r["expected"] for r in ctl)
        out["controls"] = {"n": len(ctl), "pass": ok, "rate": round(ok / len(ctl), 3), "ci95": wilson(ok, len(ctl)),
                           "by": {g: sum(r["dims"]["overall"]["final"] == r["expected"] for r in ctl if r["group"] == g)
                                  for g in sorted({r["group"] for r in ctl})}}  # fmt: skip
    return out


def report(s: dict, log: CostLog, stopped: str | None, mode: str) -> str:
    lab = s.get("labels") or {}
    lines = [f"판정 {s['n']}쌍(같은 글 {s['auto_same_text']}) · A={lab.get('A')} · B={lab.get('B')} · {mode}",
             "차원        A승  B승  무  둘다나쁨  모름  B승률(무=반)  95%구간         순서 일관성"]  # fmt: skip
    for d in ALL:
        w = s["dims"][d]
        ci = w["b_win_rate_ci95"] or ("-", "-")
        lines.append(
            f"{DIM_KO[d]:<8} {w['A']:>4} {w['B']:>4} {w['tie']:>3} {w['both_bad']:>8} {w['unknown']:>5}"
            f"  {w['b_win_rate'] if w['b_win_rate'] is not None else '-':>10}  {ci[0]}~{ci[1]:<10}  {w['consistency']}"
        )
    lines.append(
        f"위치 1 선호율 {s['position_first_share']} (95% {s['position_ci95']}) · 전체 순서 일관성 {s['consistency_all']}"
    )
    by = s["overall_by_source"]
    lines.append(
        "출처별 종합 B승률: "
        + " · ".join(f"{k} {v['b_win_rate']}(n={v['n']})" for k, v in by.items())
    )
    lines.append(f"코드 점검(표준 대비 % · 빈 답): A {s['flags']['A']} · B {s['flags']['B']}")
    if "controls" in s:
        c = s["controls"]
        lines.append(f"대조군 통과 {c['pass']}/{c['n']} ({c['rate']}, 95% {c['ci95']}) · {c['by']}")
    if mode == "dry-run":
        lines.append(f"비용 어림(스텁, 실제로 낸 돈 아님) ${log.spent:.4f} · 실제 $0")
    else:
        lines.append(
            f"비용 ${log.spent:.4f} = 응답 usage ${log.real:.4f} + 실패 호출 어림 ${log.spent - log.real:.4f}"
            f" · 값 모름 {log.unknown}번"
        )
    if stopped:
        lines.append(f"멈춤: {stopped}")
    return "\n".join(lines)


# ---- 실행 ----
def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", check=False).stdout.strip()  # fmt: skip
    except OSError:
        return ""


def load_key(env_file: Path) -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].split(" #")[0].strip().strip('"').strip("'")
                if value:
                    os.environ["ANTHROPIC_API_KEY"] = value
                    return
    sys.exit("ANTHROPIC_API_KEY가 없어요(환경변수나 --env-file)")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="쌍대 판정기(순서 바꿔 두 번)")
    ap.add_argument("--answers", type=Path, help="run_compare.py가 만든 answers.jsonl")
    ap.add_argument("--set", type=Path, default=SETS / "compare.jsonl")
    ap.add_argument("--a", default="v2", help="A 시스템 이름(답 파일의 system)")
    ap.add_argument("--b", default="v3", help="B 시스템 이름. B 승률을 보고해요")
    ap.add_argument(
        "--controls",
        type=int,
        default=0,
        help="대조군 질문 수(질문마다 3쌍). 주면 --answers 없이 돌아요",
    )
    ap.add_argument("--tag", required=True, help="결과 폴더 runs/<tag>/")
    ap.add_argument("--model", default=MODEL, help="판정 모델(값싼 대안: claude-haiku-5-5)")
    ap.add_argument(
        "--effort", choices=["low", "medium", "high", "xhigh", "max"], help="비우면 모델 기본값"
    )
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument(
        "--max-usd", type=float,
        help="비용 상한(달러). 실제 실행에는 꼭 줘요. 스텁은 어림 비용으로 같은 멈춤을 시험해요(기본 100)",
    )  # fmt: skip
    ap.add_argument(
        "--allow-partial", action="store_true", help="어림이 상한을 넘어도 넘기 전까지만 돌려요"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="스텁 판정(유료 호출 0회, SDK도 안 불러와요)"
    )
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help="쉼표로 질문 id")
    ap.add_argument("--source", help="core32,set30,multi45")
    ap.add_argument("--split", help="dev,heldout")
    ap.add_argument("--group", help="price_time,knowledge,policy,other_trade,multi_trade")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--summary-only", action="store_true", help="부르지 않고 요약만 다시 만들어요")
    a = ap.parse_args(argv)
    if not a.controls and not a.answers:
        ap.error("--answers나 --controls 중 하나가 필요해요")
    if a.model not in prices.PRICES:
        ap.error(f"값을 모르는 모델이에요(prices.py에 더해요): {a.model}")
    if a.max_usd is None:
        if not a.dry_run and not a.summary_only:
            ap.error("실제 실행에는 --max-usd가 필요해요")
        a.max_usd = 100.0
    return a


def main(argv=None) -> int:
    utf8_stdout()
    a = parse_args(argv)
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    system = RUBRIC_PATH.read_text(encoding="utf-8")
    mode = "dry-run" if a.dry_run else "live"
    meta = {
        "tag": a.tag, "mode": mode, "model": a.model, "effort": a.effort, "rubric": short_hash(system),
        "answers": str(a.answers) if a.answers else None, "set": str(a.set), "a": a.a, "b": a.b,
        "controls": a.controls, "seed": a.seed, "max_usd": a.max_usd, "head": _git("rev-parse", "HEAD"),
    }  # fmt: skip
    old = (
        json.loads((out / "meta.json").read_text("utf-8")) if (out / "meta.json").exists() else None
    )
    if old and any(old.get(k) != meta[k] for k in ("mode", "model", "rubric", "a", "b")):
        sys.exit(f"{out}는 다른 모드 · 모델 · 루브릭 · 시스템으로 돈 결과예요. 새 --tag를 써요")
    log = CostLog(out / "cost.csv", "judge")
    stopped = None
    if not a.summary_only:
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        if a.controls:
            items, missing = load_controls(a), []
        else:
            items, missing = load_pairs(a)
        for m in missing:
            append_jsonl(out / "errors.jsonl", {**m, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
        done = {r["id"] for r in jsonl(out / "judgments.jsonl")}
        todo = [x for x in items if x.id not in done]
        sys_tok = est_tokens(system)
        plan = sum(item_estimate(x, a, sys_tok, warm=i > 0) for i, x in enumerate(todo))
        print(f"판정할 쌍 {len(todo)}(이미 {len(done)} · 답 없음 {len(missing)}) · 모델 {a.model} · "
              f"어림 ${plan:.3f} · 지금까지 ${log.spent:.4f} · 상한 ${a.max_usd}")  # fmt: skip
        if log.spent + plan > a.max_usd and not a.allow_partial and not a.dry_run:
            print("어림이 상한을 넘어 시작하지 않아요(--allow-partial이면 넘기 전까지만 돌려요)")
            return 2
        if log.spent + plan > a.max_usd:
            print("어림이 상한을 넘어 중간에 멈출 거예요")
        if not a.dry_run:  # 상한을 확인한 뒤에만 키를 읽고 SDK를 불러와요
            load_key(a.env_file)
        budget = Budget(a.max_usd, log.spent)
        judge = Judge(a, out, log, budget, system)
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            pending: set = set()
            for x in todo:
                if judge.fatal:
                    break
                est = judge.item_estimate(x)
                if not budget.reserve(est):
                    stopped = f"상한 ${a.max_usd}에 닿아 새 질문을 멈췄어요"
                    break
                pending.add(ex.submit(judge.run_item, x, est))
                if len(pending) >= a.workers:
                    _, pending = wait(pending, return_when=FIRST_COMPLETED)
            wait(pending)
        if judge.fatal:
            stopped = f"멈춤(다시 해도 안 되는 오류): {judge.fatal}"
    rows = jsonl(out / "judgments.jsonl")
    if not rows:
        print("판정 결과가 없어요")
        return 1
    s = summarize(rows)
    s["cost"] = {"spent_usd": round(log.spent, 6), "real_usd": round(log.real, 6), "unknown_calls": log.unknown,
                 "estimated": mode == "dry-run"}  # fmt: skip
    s["stopped"] = stopped
    s["errors"] = len(jsonl(out / "errors.jsonl"))
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report(s, log, stopped, mode))
    print(f"저장: {out}")
    if not stopped:
        return 0
    return 3 if "상한" in stopped else 1  # 3 = 상한에서 멈춤(끝난 것만 남음)


if __name__ == "__main__":
    sys.exit(main())

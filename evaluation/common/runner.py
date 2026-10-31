"""평가 실행 공통: 에이전트 함수를 그대로 부르고 llm.parse 자리만 바꿔 끼운다.

모드
- live: 실제 llm.parse (유료, --live)
- fake: 모범 답을 돌려주는 가짜 parse (무료, --fake)
- batch: ① 에이전트 함수를 불러 요청 글만 모은다 (호출 없음) ② Batch로 한꺼번에 낸다 (llm.submit_batch →
  wait_batch → batch_results) ③ 결과를 parse 자리에 끼워 에이전트 함수를 다시 부른다.
  그래서 요청 글 · 코드 검사 · 후처리가 실시간 호출과 같다
- fake-batch: 가짜 Batch 클라이언트(모범 답)로 batch와 같은 길을 무료로 돈다 (--fake --batch)
어느 모드든 사례마다 모델 원문(코드 검사 전)과 사용량을 남긴다. 채점은 원문 기준이다.
"""

import asyncio
import contextvars
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace as NS

from pydantic import BaseModel

from evaluation.common import cost, gen

Agent = Callable[[dict], Awaitable[object]]  # 사례 → 에이전트 결과 (안에서 llm.parse를 부른다)
Witness = Callable[[dict], dict]  # 사례 → 모범 답 (가짜 LLM, 스키마 모양 dict)
MODES = ("live", "fake", "batch", "fake-batch")
FAKE_USAGE = {
    "model": "fake",
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "ms": 0,
}
_case: contextvars.ContextVar[dict] = contextvars.ContextVar("case")
_log: contextvars.ContextVar[list] = contextvars.ContextVar("log")


@dataclass
class Call:
    result: object | None = None  # 에이전트 함수가 돌려준 값
    error: str | None = None  # LlmError.reason 또는 error:<예외 이름>
    raw: dict | None = None  # 모델 원문 (스키마 모양 dict)
    usage: dict | None = None  # llm.Usage (+ batch)
    request: dict = field(default_factory=dict)


class _Captured(Exception):
    """batch ①: parse 대신 요청만 들고 나온다"""

    def __init__(self, system: str, user: str, schema: type[BaseModel], kw: dict) -> None:
        super().__init__("captured")
        self.system, self.user, self.schema, self.kw = system, user, schema, kw


def _usage(u, batch: bool) -> dict:
    d = dict(u.__dict__) if not isinstance(u, dict) else dict(u)
    return d | ({"batch": True} if batch else {})


async def _one(case: dict, agent: Agent, batch: bool) -> Call:
    from app.agent.llm import LlmError

    _case.set(case)
    _log.set([])
    out = Call()
    try:
        out.result = await agent(case)
    except LlmError as e:
        out.error = e.reason
    except _Captured as c:
        out.request = {"system": c.system, "user": c.user, "schema": c.schema, "kw": c.kw}
    except Exception as e:  # noqa: BLE001 — 사례 하나의 뜻밖 오류로 유료 실행 결과 전체를 잃지 않게
        out.error = f"error:{type(e).__name__}"
    if rec := _log.get():
        raw, usage = rec[-1]
        out.raw, out.usage = raw.model_dump(mode="json"), _usage(usage, batch)
    return out


@contextmanager
def _parse(impl):
    from app.agent import llm

    orig = llm.parse
    llm.parse = impl
    try:
        yield
    finally:
        llm.parse = orig


def _recorded(inner):
    async def parse(system, user, schema, **kw):
        out, usage = await inner(system, user, schema, **kw)
        _log.get().append((out, usage))
        return out, usage

    return parse


async def _gather(cases: list[dict], agent: Agent, concurrency: int, batch: bool) -> list[Call]:
    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict) -> Call:
        async with sem:
            return await asyncio.create_task(_one(case, agent, batch))

    return list(await asyncio.gather(*(one(c) for c in cases)))


class FakeBatches:
    """가짜 Batch API (--fake --batch · 테스트): 낸 요청마다 모범 답 JSON을 돌려준다."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers, self.requests = answers, []

    async def create(self, requests):
        self.requests = list(requests)
        return NS(id="fake_batch", processing_status="in_progress")

    async def retrieve(self, batch_id):
        return NS(processing_status="ended")

    async def results(self, batch_id):
        async def rows():
            for req in self.requests:
                text = self.answers[req["custom_id"]]
                u = NS(
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                )
                msg = NS(
                    model="fake",
                    stop_reason="end_turn",
                    content=[NS(type="text", text=text)],
                    usage=u,
                )
                yield NS(custom_id=req["custom_id"], result=NS(type="succeeded", message=msg))

        return rows()


@contextmanager
def _fake_client(answers: dict[str, str]):
    from app.agent import llm

    old = llm._client
    llm._client = NS(messages=NS(batches=FakeBatches(answers)))
    try:
        yield
    finally:
        llm._client = old


async def run(
    cases: list[dict],
    agent: Agent,
    *,
    mode: str,
    witness: Witness | None = None,
    concurrency: int = 4,
    batch_file: Path | None = None,
    poll_s: float | None = None,
) -> list[Call]:
    """사례마다 에이전트 함수를 부른다. 돌려주는 순서는 사례 순서와 같다.

    batch_file: Batch id를 적어 둘 곳. 이미 있으면 새로 내지 않고 그 Batch 결과를 받는다 (기다리다 끊겼을 때).
    """
    from app.agent import llm

    if mode not in MODES:
        raise ValueError(mode)
    if mode == "live":
        with _parse(_recorded(llm.parse)):
            return await _gather(cases, agent, concurrency, False)
    if mode == "fake":

        async def fake(system, user, schema, **kw):
            return schema.model_validate(witness(_case.get())), llm.Usage(**FAKE_USAGE)

        with _parse(_recorded(fake)):
            return await _gather(cases, agent, concurrency, False)

    # ① 요청 모으기 (호출 없음)
    async def capture(system, user, schema, **kw):
        raise _Captured(system, user, schema, kw)

    with _parse(capture):
        first = await _gather(cases, agent, concurrency, False)
    asked = {c["id"]: f.request for c, f in zip(cases, first, strict=True) if f.request}
    if not asked:
        return first
    reqs = list(asked.values())
    schema, kw = reqs[0]["schema"], reqs[0]["kw"]
    if any(r["schema"] is not schema or r["kw"] != kw for r in reqs):
        raise ValueError("Batch 하나에는 같은 스키마 · 역할 요청만 넣어요")
    items = [(cid, r["system"], r["user"]) for cid, r in asked.items()]
    role, effort = kw.get("role", "default"), kw.get("effort")

    # ② Batch로 내고 결과 받기
    async def submit_and_collect() -> dict:
        saved = batch_file and batch_file.exists()
        if saved:
            batch_id = json.loads(batch_file.read_text(encoding="utf-8"))["batch_id"]
        else:
            batch_id = await llm.submit_batch(items, schema, role=role, live=True, effort=effort)
            if batch_file:
                batch_file.parent.mkdir(parents=True, exist_ok=True)
                batch_file.write_text(json.dumps({"batch_id": batch_id}), encoding="utf-8")
        await llm.wait_batch(batch_id, poll_s=llm.BATCH_POLL_S if poll_s is None else poll_s)
        got = await llm.batch_results(batch_id, schema, role=role)
        return {cid: got.get(cid, llm.LlmError("batch_missing")) for cid in asked}

    if mode == "fake-batch":
        by_id = {c["id"]: c for c in cases}
        answers = {cid: json.dumps(witness(by_id[cid]), ensure_ascii=False) for cid in asked}
        with _fake_client(answers):
            got = await submit_and_collect()
    else:
        got = await submit_and_collect()

    # ③ 결과를 parse 자리에 끼워 다시 부른다 (코드 검사 · 후처리가 실시간과 같다)
    async def replay(system, user, schema, **kw):
        r = got[_case.get()["id"]]
        if isinstance(r, llm.LlmError):
            raise r
        return r

    with _parse(_recorded(replay)):
        return await _gather(cases, agent, concurrency, True)


# ---------------------------------------------------------------- 사례 고르기 · 요약 도구
def select(
    cases: list[dict],
    *,
    split: str = "all",
    sample: int = 0,
    stratify: str = "category",
    seed: int = 1,
    ids: list[str] | None = None,
) -> list[dict]:
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    if split != "all":
        cases = [c for c in cases if c["split"] == split]
    if sample:
        r, key = gen.rng("sample", seed), (lambda c: gen.get(c, stratify))
        # 두 나눔을 같이 뽑을 때는 dev:held-out 2:1을 지킨다
        pick = gen.sample_2to1 if split == "all" else gen.stratified_sample
        cases = pick(cases, sample, key, r)
    return cases


def add_args(ap) -> None:
    """실행기들이 같이 쓰는 인자"""
    ap.add_argument(
        "--cases", type=Path, help="사례 jsonl (기본: cases_5k.jsonl, 없으면 sample_100)"
    )
    ap.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    ap.add_argument("--sample", type=int, default=0, help="층마다 고르게 이만큼만 (0이면 전부)")
    ap.add_argument("--stratify", default="category", help="층 키 (예: category, strata.occupied)")
    ap.add_argument("--seed", type=int, default=1, help="표본 시드")
    ap.add_argument("--case", action="append", help="이 id만 (여러 번 줄 수 있음)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--batch", action="store_true", help="Batch로 낸다 (--live와 같이 쓰면 유료)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="실제로 호출한다 (유료)")
    mode.add_argument(
        "--fake", action="store_true", help="가짜 LLM(모범 답)으로 코드 경로만 (무료)"
    )
    mode.add_argument(
        "--rescore", type=Path, help="저장된 결과 폴더를 다시 채점만 한다 (호출 없음)"
    )
    ap.add_argument("--out", type=Path, help="결과 폴더 (기본: <평가>/results/<날짜-시각>)")


def mode_of(args) -> str | None:
    """--live/--fake × --batch → 실행 모드. 둘 다 없으면 None (호출 수 · 예상 비용만)"""
    if args.live:
        return "batch" if args.batch else "live"
    if args.fake:
        return "fake-batch" if args.batch else "fake"
    return None


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "-"


def estimate_text(
    name: str,
    cases: list[dict],
    n_judge: int,
    model: str,
    effort: str,
    judge_shape: str = "judge",
    group: str | None = None,
    judged: set[str] | None = None,
) -> str:
    """호출 수 · 토큰 모양 · 모델별 예상 비용 (호출 없음).
    group: 시스템 프롬프트가 이 키(예: trade)마다 다르면 캐시를 묶음마다 따로 센다 (judged: 판정할 사례 id)"""
    s = cost.shape(name)
    nd = sum(c["split"] == "dev" for c in cases)
    sizes, jsizes, note = [len(cases)], [n_judge], []
    if group:
        ids = judged or set()
        sizes = list(Counter(gen.get(c, group) for c in cases).values())
        jsizes = list(Counter(gen.get(c, group) for c in cases if c["id"] in ids).values())
        note = [f"시스템 프롬프트가 {group}마다 달라 캐시를 {len(sizes)}묶음으로 따로 센다"]
    rows = [
        f"사례 {len(cases)}개 (dev {nd} · held-out {len(cases) - nd})",
        f"호출: 에이전트 {len(cases)}번 + 판정 {n_judge}번 (지금 설정: {model} · effort {effort})",
        f"토큰 모양(평균): 입력 {s.uncached} + 시스템(캐시) {s.system} · 출력 {s.output} ({s.basis})",
        *note,
        "",
        "| 모델 | 이번 실행 | 같은 사례 Batch |",
        "| --- | ---: | ---: |",
    ]
    for m, label in cost.MODEL_LABEL.items():
        js = cost.SHAPES[judge_shape]

        def total(batch: bool, m: str = m, js: cost.CallShape = js) -> float:
            agent = sum(cost.estimate(s, n, m, batch=batch) for n in sizes)
            return agent + sum(cost.estimate(js, n, m, batch=batch) for n in jsizes)

        rows.append(f"| {label} | ${total(False):,.2f} | ${total(True):,.2f} |")
    rows += ["", f"가격: {cost.PRICE_SOURCE}. 생각 토큰에 따라 달라요."]
    return "\n".join(rows)


def load_env(root: Path) -> None:
    """저장소 루트 .env에서 LLM 모델 · 생각 깊이 · API 키만 읽어 설정에 넣는다 (값은 찍지 않는다).

    LLM_LIVE는 읽지 않는다. 실제 호출은 --live일 때만 켠다.
    """
    import os

    from app.config import Settings, settings

    p = root / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = (x.strip() for x in line.split("=", 1))
                if v and (k == "ANTHROPIC_API_KEY" or k.startswith(("LLM_MODEL", "LLM_EFFORT"))):
                    os.environ.setdefault(k, v)
    fresh = Settings()
    for name in Settings.model_fields:
        if name == "anthropic_api_key" or name.startswith(("llm_model", "llm_effort")):
            setattr(settings, name, getattr(fresh, name))


def cost_table(named: list[tuple[str, list[dict]]]) -> list[str]:
    """호출 이름 · 사용량 목록 → 비용 표 줄 (Batch 사용량은 50% 할인으로 셈)"""
    import statistics

    rows = [
        "| 호출 | 횟수 | 입력 | 캐시 읽기 | 캐시 쓰기 | 출력 | 비용 | 지연 중앙값 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, us in named:
        if not us:
            continue
        total, unknown = cost.total_cost(us)
        tok = [sum(u[k] for u in us) for k in cost.TOKEN_KEYS]
        ms = statistics.median(u["ms"] for u in us) / 1000
        price = f"${total:.3f}" + (f" (가격 모름 {unknown}번)" if unknown else "")
        rows.append(
            f"| {name} | {len(us)} | "
            + " | ".join(f"{t:,}" for t in tok)
            + f" | {price} | {ms:.1f}초 |"
        )
    return rows


def write(out_dir: Path, meta: dict, results: list[dict], report: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = {"meta": meta, "results": results}
    (out_dir / "raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    (out_dir / "summary.md").write_text(report, encoding="utf-8", newline="\n")

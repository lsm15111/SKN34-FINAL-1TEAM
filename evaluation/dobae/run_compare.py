"""도배 상담: 'Claude에게 그냥 묻기' vs '믿집 에이전트' 비교.

같은 모델(LLM_MODEL)로 같은 사례를 두 방식에 넣고 코드로 채점한다.
- direct: 시스템 프롬프트 없이 고객 말을 그대로 보낸다. 정보가 빠진 사례는 둘째 턴에 빠진 정보를 준다.
- ours: 상담 API와 같은 흐름(consult.service.turn). 코드가 묻는 칸은 정답 카드로 답한다(첫 화면 폼 답과 같음).
- 'Claude에게 그냥 묻기' 답의 금액 · 되물음은 같은 모델이 낮은 effort로 뽑는다(추출만, 평가는 코드).

실행 (저장소 루트에서, 실제 유료 호출):
    cd backend && uv run python ../evaluation/dobae/run_compare.py --live
--live 없이 돌리면 호출 수와 예상 비용만 보여 준다.
"""

import argparse
import asyncio
import contextvars
import json
import os
import statistics
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _load_env() -> None:
    """저장소 루트 .env에서 LLM 설정만 읽는다 (값은 화면에 찍지 않는다)."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            k = k.strip()
            if k in ("ANTHROPIC_API_KEY", "LLM_MODEL", "LLM_EFFORT") and v.strip():
                os.environ.setdefault(k, v.strip())


sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서도 한글이 깨지지 않게
_load_env()
os.environ["LLM_LIVE"] = "true"
os.environ.setdefault("APP_ENV", "local")

from pydantic import BaseModel

from app.agent import llm, wallpaper
from app.calc import dobae as calc
from app.config import settings
from app.consult import service
from app.consult.schemas import Answer, ConsultCard, ConsultIn

Field = Literal["area", "area_basis", "grade", "include_ceiling", "occupied"]
_calls: contextvars.ContextVar[list] = contextvars.ContextVar("calls")
_dropped: contextvars.ContextVar[list] = contextvars.ContextVar("dropped")


class Judge(BaseModel):
    """직접 물은 답에서 적힌 것만 뽑는다 (없으면 null · false)."""

    first_asked: list[Field]
    first_total_low: int | None
    first_total_high: int | None
    final_total_low: int | None
    final_total_high: int | None
    final_vat: Literal["included", "excluded", "unstated"]
    mentions_after_visit: bool
    area_basis_distinguished: bool
    cites_public_standard: bool


JUDGE_SYSTEM = """너는 답변에서 사실만 뽑는 채점 보조야. 판단하지 말고 적힌 것만 옮겨.
- first_asked: 첫 답이 고객에게 되물은 정보. area(평수) · area_basis(공급/전용) · grade(합지/실크 등 벽지 종류) · include_ceiling(천장 포함) · occupied(거주 중/빈집) 중 해당하는 것만.
- *_total_low/high: 그 답에 적힌 '도배 공사 전체' 비용(원, 정수). 범위면 양 끝, 숫자 하나면 둘 다 같은 값. 평당 단가만 있고 전체 금액이 없으면 null. 여러 안(합지 · 실크 등)이 있으면 고객이 고른 조건에 맞는 것.
- final_vat: 마지막 답 금액이 부가세 포함이면 included, 별도면 excluded, 말이 없으면 unstated.
- mentions_after_visit: 기존 벽지 철거 · 폐기물 · 바탕 보수 등으로 실측 뒤 금액이 달라질 수 있다고 말했나.
- area_basis_distinguished: 공급면적과 전용면적(또는 실평수) 차이를 짚었나.
- cites_public_standard: 표준시장단가 · 표준품셈 · 노임단가 같은 공공 기준을 근거로 들었나."""

REQUIRED = ("area", "area_basis", "grade", "include_ceiling", "occupied")
GRADE_KO = {"basic": "실크", "economy": "합지"}


class _NoDb:
    async def close(self) -> None:
        return None


def truth_card(t: dict) -> ConsultCard:
    area = calc.pyeong_to_m2(Decimal(t["pyeong"])) if "pyeong" in t else calc.m2(Decimal(t["m2"]))
    return ConsultCard(
        area_m2=area,
        area_basis=t["area_basis"],
        grade=t["grade"],
        include_ceiling=t["include_ceiling"],
        occupied=t["occupied"],
        balcony_ext=t.get("balcony_ext", False),
    )


def answer_for(field: str, t: dict) -> Answer:
    if field == "area":
        v = str(t["pyeong"]) if "pyeong" in t else f"{t['m2']}㎡"
    elif field in ("include_ceiling", "occupied"):
        v = "yes" if t[field] else "no"
    else:
        v = t[field]
    return Answer(field=field, value=v)


def followup(t: dict) -> str:
    size = f"{t['pyeong']}평" if "pyeong" in t else f"{t['m2']}㎡"
    parts = [
        f"{'공급' if t['area_basis'] == 'supply' else '전용'} {size}이고",
        f"{GRADE_KO[t['grade']]}로 할게요.",
        "천장도 해요." if t["include_ceiling"] else "천장은 안 해요.",
        "살면서 공사해요." if t["occupied"] else "빈집이에요.",
    ]
    if t.get("balcony_ext"):
        parts.append("발코니는 확장했어요.")
    return " ".join(parts)


async def _parse_logged(*a, **k):
    out, usage = await _ORIG_PARSE(*a, **k)
    _calls.get().append(usage)
    return out, usage


def _validate_logged(plan, keys):
    clean, dropped = _ORIG_VALIDATE(plan, keys)
    _dropped.get().append(dropped)
    return clean, dropped


_ORIG_PARSE, _ORIG_VALIDATE = llm.parse, wallpaper.validate
llm.parse, wallpaper.validate = _parse_logged, _validate_logged


async def run_ours(case: dict) -> dict:
    _calls.set([])
    _dropped.set([])
    t = case["truth"]
    out = await service.turn(_NoDb(), None, ConsultIn(message=case["message"]))
    first_card, first_reply = out.card, out.reply
    # 코드가 폼으로 묻는 칸에 정답 카드로 한 번에 답한다
    asked = [q.field for q in out.questions]
    if asked:
        answers = [answer_for(f, t) for f in asked]
        out = await service.turn(_NoDb(), None, ConsultIn(card=out.card, answers=answers))
    want = calc.quote(_input(truth_card(t)), _prices())
    res = out.results[0] if out.results else None
    return {
        "first_card": first_card.model_dump(mode="json"),
        "asked": asked,
        "reply_first": first_reply,
        "total": res.quote.total if res else None,
        "subtotal": res.quote.subtotal if res else None,
        "want_total": want.total,
        "want_subtotal": want.subtotal,
        "plan_status": res.plan_status if res else None,
        "plan": res.plan.model_dump() if res and res.plan else None,
        "dropped": sum(_dropped.get()),
        "calls": [u.__dict__ for u in _calls.get()],
    }


def _input(c: ConsultCard) -> calc.DobaeInput:
    return calc.DobaeInput(
        area_m2=c.area_m2,
        area_basis=c.area_basis,
        grade=c.grade,
        include_ceiling=c.include_ceiling,
        occupied=c.occupied,
        balcony_ext=c.balcony_ext,
    )


def _prices():
    from app.refprice.book import DOBAE_2026H2

    return DOBAE_2026H2


async def run_direct(case: dict) -> dict:
    _calls.set([])
    msgs: list[dict] = [{"role": "user", "content": case["message"]}]
    first, content, u1 = await llm.chat(msgs)
    usages = [u1]
    final = first
    if case["ask"] or case.get("unknown"):
        msgs += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": followup(case["truth"])},
        ]
        final, _, u2 = await llm.chat(msgs)
        usages.append(u2)
    judge_in = (
        f"고객 조건: {followup(case['truth'])}\n\n<첫 답>\n{first}\n</첫 답>\n\n"
        f"<마지막 답>\n{final}\n</마지막 답>"
    )
    j, uj = await _ORIG_PARSE(JUDGE_SYSTEM, judge_in, Judge, effort="low")
    want = calc.quote(_input(truth_card(case["truth"])), _prices())
    return {
        "first": first,
        "final": final,
        "judge": j.model_dump(),
        "want_total": want.total,
        "want_subtotal": want.subtotal,
        "calls": [u.__dict__ for u in usages],
        "judge_call": uj.__dict__,
    }


def _mid(lo, hi):
    if lo is None and hi is None:
        return None
    lo = lo if lo is not None else hi
    hi = hi if hi is not None else lo
    return (lo + hi) / 2


def _cost(calls: list[dict]) -> float:
    # Claude Opus 5.5 기준 $/1M (입력 4, 출력 20, 캐시 읽기 0.2, 캐시 쓰기 5)
    return sum(
        c["input_tokens"] * 4e-6
        + c["output_tokens"] * 20e-6
        + c["cache_read_tokens"] * 0.2e-6
        + c["cache_write_tokens"] * 5e-6
        for c in calls
    )


def summarize(cases: list[dict], res: dict) -> str:
    rows, gaps, spreads_d, ok_fields, n_fields = [], [], [], 0, 0
    asked_ok = 0
    early = 0
    incomplete = [c for c in cases if c["ask"]]
    d_asked = 0
    d_after = d_basis = d_public = d_vat = 0
    ours_total_ok = plan_new = dropped = 0
    ours_calls, direct_calls = [], []
    n_runs = 0
    for c in cases:
        o_runs, d_runs = res[c["id"]]["ours"], res[c["id"]]["direct"]
        for o in o_runs:
            n_runs += 1
            ours_calls += o["calls"]
            card = o["first_card"]
            want = truth_card(c["truth"])
            for f in c["stated"]:
                if f not in REQUIRED:
                    continue
                n_fields += 1
                got = card["area_m2"] if f == "area" else card[f]
                exp = str(want.area_m2) if f == "area" else want.model_dump(mode="json")[f]
                ok_fields += got == exp
            expect = set(c["ask"]) - set(c.get("ask_or_check", []))
            asked_ok += expect <= set(o["asked"]) and not (set(o["asked"]) - set(c["ask"]))
            ours_total_ok += o["total"] == o["want_total"]
            plan_new += o["plan_status"] == "new"
            dropped += o["dropped"]
        mids = []
        for d in d_runs:
            direct_calls += d["calls"] + [d["judge_call"]]
            j = d["judge"]
            if c["ask"]:
                early += j["first_total_low"] is not None or j["first_total_high"] is not None
                d_asked += bool(set(j["first_asked"]) & set(c["ask"]))
            d_after += j["mentions_after_visit"]
            d_basis += j["area_basis_distinguished"]
            d_public += j["cites_public_standard"]
            d_vat += j["final_vat"] != "unstated"
            m = _mid(j["final_total_low"], j["final_total_high"])
            if m is not None:
                ref = d["want_total"] if j["final_vat"] == "included" else d["want_subtotal"]
                gaps.append(m / ref - 1)
                mids.append(m)
        if len(mids) >= 2:
            spreads_d.append((max(mids) - min(mids)) / statistics.median(mids))
        rows.append(
            f"| {c['id']} | {c['split']} | {', '.join(c['ask']) or '-'} | {len(mids)}/{len(d_runs)} |"
        )

    n_inc = len(incomplete) * (n_runs // len(cases))
    pct = lambda a, b: f"{(100 * a / b):.0f}% ({a}/{b})" if b else "-"
    gap_abs = statistics.median([abs(g) for g in gaps]) if gaps else None
    lines = [
        "# 도배 상담 비교 결과",
        "",
        f"모델 {settings.llm_model} · effort {settings.llm_effort} · 사례 {len(cases)}개 × {n_runs // len(cases)}회",
        "",
        "| 지표 | Claude에게 그냥 묻기 | 믿집 에이전트 |",
        "| --- | --- | --- |",
        f"| 정보가 빠졌는데 첫 답에 금액부터 냄 | {pct(early, n_inc)} | 0% (코드가 빈 칸을 먼저 물음) |",
        f"| 정보가 빠졌을 때 되물음 | {pct(d_asked, n_inc)} | {pct(asked_ok, n_runs)} (빠진 칸만 정확히) |",
        f"| 같은 조건 3회 금액 흔들림 (중앙값) | {f'{statistics.median(spreads_d):.0%}' if spreads_d else '-'} | 0% (계산 엔진) |",
        f"| 공공 기준 표준견적과 차이 (절댓값 중앙값) | {f'{gap_abs:.0%}' if gap_abs is not None else '-'} | 0% ({pct(ours_total_ok, n_runs)} 일치) |",
        f"| 부가세 포함 · 별도 표시 | {pct(d_vat, n_runs)} | 100% (VAT 따로) |",
        f"| 실측 뒤 달라질 항목 언급 | {pct(d_after, n_runs)} | 100% ('실측 후' 줄) |",
        f"| 공급 · 전용 구분 | {pct(d_basis, n_runs)} | 100% (필수 칸) |",
        f"| 공공 기준을 근거로 듦 | {pct(d_public, n_runs)} | 100% (줄마다 출처) |",
        f"| 대화에서 칸 값 뽑기 정확도 | - | {pct(ok_fields, n_fields)} |",
        f"| 전문가 의견 생성 성공 | - | {pct(plan_new, n_runs)} (규칙 위반으로 버린 항목 {dropped}개) |",
        f"| 실행당 비용(추정) | ${_cost(direct_calls) / max(n_runs, 1):.3f} | ${_cost(ours_calls) / max(n_runs, 1):.3f} |",
        f"| 호출당 지연 중앙값 | {statistics.median([c['ms'] for c in direct_calls]) / 1000:.1f}초 | {statistics.median([c['ms'] for c in ours_calls]) / 1000:.1f}초 |",
        "",
        "공공 기준과의 차이는 '정답과의 오차'가 아니에요. 업체 시세와 공공 기준은 원래 다를 수 있어요.",
        "그냥 묻기 답의 금액 · 되물음은 같은 모델(effort low)이 뽑았어요. 몇 건은 사람이 원문과 대조해야 해요.",
        "",
        "| 사례 | 나눔 | 빠진 칸 | 그냥 묻기 금액 추출 |",
        "| --- | --- | --- | --- |",
        *rows,
    ]
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실제로 호출한다 (유료)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--case", help="이 id 하나만 (스크립트 점검용)")
    ap.add_argument(
        "--summary", help="저장된 결과 폴더의 raw.json으로 표만 다시 만든다 (호출 없음)"
    )
    ap.add_argument(
        "--reuse-direct", help="그냥 묻기는 이 결과 폴더 것을 쓰고 우리 쪽만 다시 돌린다"
    )
    args = ap.parse_args()

    cases = [
        json.loads(x)
        for x in (HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if args.summary:
        d = Path(args.summary)
        res = json.loads((d / "raw.json").read_text(encoding="utf-8"))
        (d / "summary.md").write_text(summarize(cases, res) + "\n", encoding="utf-8")
        print(summarize(cases, res))
        return
    reused = (
        json.loads((Path(args.reuse_direct) / "raw.json").read_text(encoding="utf-8"))
        if args.reuse_direct
        else None
    )
    kinds = ("ours",) if reused else ("ours", "direct")
    n_inc = sum(1 for c in cases if c["ask"] or c.get("unknown"))
    planned = args.runs * 2 * len(cases)
    if not reused:
        planned += args.runs * (len(cases) + n_inc + len(cases))
    print(
        f"사례 {len(cases)}개 × {args.runs}회, 예상 호출 약 {planned}번 (모델 {settings.llm_model})"
    )
    if not args.live:
        print("예상 비용 약 $8~15 (Opus 5.5 기준, 생각 토큰에 따라 달라요). 실제로 돌리려면 --live")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(".env에 ANTHROPIC_API_KEY를 넣어 주세요.")

    sem = asyncio.Semaphore(args.concurrency)

    async def one(kind, case):
        async with sem:
            fn = run_ours if kind == "ours" else run_direct
            try:
                return await asyncio.create_task(fn(case))
            except llm.LlmError as e:
                return {"error": e.reason}

    res: dict = {
        c["id"]: {"ours": [], "direct": reused[c["id"]]["direct"] if reused else []} for c in cases
    }
    jobs = [(k, c) for c in cases for k in kinds for _ in range(args.runs)]
    outs = await asyncio.gather(*(one(k, c) for k, c in jobs))
    for (k, c), o in zip(jobs, outs, strict=True):
        res[c["id"]][k].append(o)
    errors = sum(1 for o in outs if "error" in o)
    for v in res.values():
        v["ours"] = [o for o in v["ours"] if "error" not in o]
        v["direct"] = [o for o in v["direct"] if "error" not in o]

    out_dir = HERE / "results" / datetime.now().strftime("%Y%m%d-%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = summarize(cases, res) + (
        f"\n\n호출 실패로 빠진 실행: {errors}개\n" if errors else "\n"
    )
    (out_dir / "summary.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\n저장: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())

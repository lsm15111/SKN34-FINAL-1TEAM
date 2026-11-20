"""v2 · v3 답 파이프라인에 같은 질문 · 같은 집을 넣어 답을 JSONL로 받아요(공급자에 묶이지 않음).

    cd backend && uv run python ../evaluation/v4/run_compare.py --dry-run --tag dry1
    cd backend && LLM_LIVE=true uv run python ../evaluation/v4/run_compare.py --live --kb db --tag c1 --max-usd 6   # 리드 허락 뒤

- 같은 질문: sets/compare.jsonl(107). 같은 집: home.HOMES(H32) → v2 V2QuoteIn + 화면 글 · v3 ProjectFacts(home.py에 맞춘 방법)
- v2: app.v2.ask.start → 화면 도구는 실행한 셈 치고 {"ok": true}로 이어 가요(evaluation/answer/run.py와 같음)
- v3: app.agent.v3.turn.run_turn → chat.service._public. chat.service.ai_turn에서 DB · Redis 저장만 뺀 길이에요
  (core_run · composer_eval과 같음). v4에 chat.service.answer_only가 생기면 같은 자리에서 바꿔 끼워요
- --dry-run(기본): LLM_LIVE=false 스텁. 키 환경변수를 이 프로세스에서 지우고, DB · Redis 대신 저장소 지식 색인 · 메모리를 써요.
  유료 호출 0회(v2는 스텁 글, v3는 운영 무료 모드 답)
- --live: LLM_LIVE=true와 --max-usd가 있어야 돌아요. 시작 전 어림(budget.py)이 상한을 넘으면 시작하지 않아요
- 공급자: app.agent.llm 함수만 거쳐요(SDK를 여기서 부르지 않음). 사용량은 llm._sink(있으면, Claude 전환 뒤) 또는
  llm.USAGE_HOOK + chat_tools 결과로 받아요. 모델 값을 모르면 비용을 비워 두고 '값 모름'으로 세요
- 판정용 글(text): 화면에 보이는 것(묶음 · 계산 상자 · 카드 · 되묻기 · 모름 · 출처 이름)을 평문으로. 인용 번호 · 꾸밈은 지워요
- 저장(runs/<tag>/): answers.jsonl(질문 × 시스템 한 줄, 끝날 때마다 씀) · errors.jsonl · cost.csv(유료일 때) · meta.json.
  같은 --tag면 이미 받은 (질문, 시스템)은 건너뛰어요
"""

import argparse
import asyncio
import inspect
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import budget as bud
import home as homes
import prices
from kit import ROOT, RUNS, SETS, CostLog, append_jsonl, jsonl, utf8_stdout

KEY_ENVS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
NO_FACTS = "(없음)"
TODAY = date(2026, 11, 19)  # 집 없이 물을 때 오늘
CITE = re.compile(r"\s?\[K\d{1,5}\]")
MARK = re.compile(r"\*\*|__|^#{1,6}\s*", re.MULTILINE)


# ---- 판정용 평문 ----
def clean(text: str) -> str:
    text = MARK.sub("", CITE.sub("", text or ""))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def calc_line(c: dict) -> str:
    parts = [f"[믿집 계산] {c.get('label', '')}"]
    if c.get("amount") is not None:
        parts.append(f"{c['amount']:,}원")
    if c.get("qty") is not None:
        parts.append(f"{c['qty']:g}{c.get('unit') or ''}")
    if c.get("unit_price") is not None:
        parts.append(f"단가 {c['unit_price']:,}원")
    if c.get("in_total") is False:
        parts.append("합계에 안 들어감")
    if c.get("note"):
        parts.append(c["note"])
    return " · ".join(parts)


def card_lines(c: dict) -> list[str]:
    head = " ".join(x for x in (c.get("title"), c.get("text")) if x)
    out = [f"[카드] {head}"] if head else []
    out += [calc_line(x) for x in c.get("calc") or []]
    out += [
        f"· {v.get('name')}: " + " · ".join(v.get("reasons") or []) for v in c.get("vendors") or []
    ]
    t = c.get("table")
    if t:
        out.append(" | ".join(t.get("cols") or []))
        out += [" | ".join(r.get("cells") or []) for r in t.get("rows") or []]
    d = c.get("draft")
    if d:
        out.append(f"요청 초안: 희망 {d.get('wish_start')}~{d.get('wish_end')} · 업체 "
                   f"{', '.join(d.get('vendors') or [])} · {d.get('formula') or ''}")  # fmt: skip
    choices = [x.get("text") for x in c.get("choices") or [] if x.get("text")]
    if choices:
        out.append("단추: " + " / ".join(choices))
    return out


def render_v3(pub: dict) -> str:
    """v3 공개 답(AiAnswer) → 평문. 짧은 답(brief)은 묶음 문장에서 고른 것이라 빼고, 이어 묻기 칩도 빼요."""
    lines: list[str] = []
    for s in pub.get("sections") or []:
        if s.get("title"):
            lines.append(s["title"])
        lines += [x for x in s.get("sentences") or [] if x]
        lines += ["· " + " — ".join(c for c in row if c) for row in s.get("table") or []]
        if s.get("caution"):
            lines.append("주의: " + s["caution"])
        if s.get("tip"):
            lines.append("도움말: " + s["tip"])
    lines += [calc_line(c) for c in pub.get("calc") or []]
    for c in pub.get("cards") or []:
        lines += card_lines(c)
    ask = pub.get("ask")
    if ask:
        lines.append(f"[되묻기] {ask.get('question')} ({' / '.join(ask.get('options') or [])})")
    lines += pub.get("unknown") or []
    refs = [r.get("title") for r in pub.get("refs") or [] if r.get("title")]
    if refs:
        lines.append("출처: " + " · ".join(dict.fromkeys(refs)))
    return clean("\n".join(lines))


def render_v2(out: dict) -> str:
    text = clean(out.get("text") or "")
    refs = [s.get("title") for s in out.get("sources") or [] if s.get("title")]
    if refs:
        text += "\n출처: " + " · ".join(dict.fromkeys(refs))
    return text


# ---- 사용량 받기(공급자 무관) ----
class UsageTap:
    """한 답이 끝날 때 take()로 그 사이 LLM 사용량을 가져가요(한 번에 한 답만 돌려서 섞이지 않아요)."""

    def __init__(self, llm, settings):
        self.rows: list[dict] = []
        if hasattr(llm, "_sink"):  # Claude 전환 뒤(계약서: _sink → usage.record)
            real = llm._sink
            if inspect.iscoroutinefunction(real):

                async def sink(*args, **kw):
                    self._grab(args, kw)
                    return await real(*args, **kw)
            else:

                def sink(*args, **kw):
                    self._grab(args, kw)
                    return real(*args, **kw)

            llm._sink = sink
            self.source = "llm._sink"
            return
        if hasattr(
            llm, "USAGE_HOOK"
        ):  # 지금(OpenAI): 구조화 호출마다 {role, model, input, cached, output}
            llm.USAGE_HOOK = lambda u: self.rows.append(
                {"model": u.get("model"), "usage": prices.usage_of(u)}
            )
        real_chat = llm.chat_tools

        async def chat_tools(system, messages, tools):
            r = await real_chat(system, messages, tools)
            u = r.get("usage") or {}
            if any(u.values()):  # 스텁은 0이라 남기지 않아요
                model = (
                    r.get("model")
                    or u.get("model")
                    or getattr(settings, "openai_agent_model", None)
                )
                self.rows.append({"model": model, "usage": prices.usage_of(u)})
            return r

        llm.chat_tools = chat_tools
        self.source = "llm.USAGE_HOOK + chat_tools"

    def _grab(self, args, kw) -> None:
        for x in (*args, *kw.values()):
            d = x if isinstance(x, dict) else getattr(x, "__dict__", None)
            if (
                isinstance(d, dict)
                and "model" in d
                and any(k in d for k in ("input_tokens", "input"))
            ):
                self.rows.append({"model": d.get("model"), "usage": prices.usage_of(d)})
                return

    def take(self) -> list[dict]:
        rows, self.rows = self.rows, []
        return rows


# ---- DB · Redis 대신(--kb repo · 늘) ----
def patch_v2_store() -> None:
    """v2 턴 보관(Redis)과 요청 제한을 메모리로. 평가는 자기 상한(--max-usd)을 따로 지켜요."""
    from app.shared import ratelimit
    from app.shared.errors import AppError
    from app.v2 import ask

    turns: dict[str, dict] = {}

    async def _save(turn_id: str, turn: dict) -> None:
        turns[turn_id] = json.loads(json.dumps(turn, ensure_ascii=False))

    async def take(turn_id: str, user_id: str, ids: list[str]) -> dict:
        t = turns.pop(turn_id, None)
        if not t or t.get("user") != user_id or set(ids) != set(t["pending"]):
            raise AppError(404, "not_found", ask.GONE)
        return t

    async def _drop(turn_id: str) -> None:
        turns.pop(turn_id, None)

    async def hit(*_a, **_k) -> None:
        return None

    ask._save, ask.take, ask._drop = _save, take, _drop
    ratelimit.hit = hit


def patch_v2_repo_kb() -> None:
    """v2 근거 검색 · 인용 검사를 저장소 지식 색인(tests/v3_kb, DB 없음)으로. 이어 묻기 추천은 빼요(판정하지 않음)."""
    from v3_kb import repo_index

    from app.knowledge import bm25
    from app.knowledge import service as knowledge
    from app.v2 import ask

    async def _search(q: str, *, queries: list[str] | None = None, trade: str | None = None):
        return bm25.search(repo_index(), q, queries=queries or [], trade=trade, k=6)

    async def verify_cites(_s, text: str) -> tuple[str, int]:
        return bm25.verify_cites(repo_index(), text)

    async def _suggest(_turn, _sources) -> list:
        return []

    ask._search, ask._suggest = _search, _suggest
    knowledge.verify_cites = verify_cites


# ---- 답 파이프라인 ----
class V2:
    name = "v2"

    def __init__(self):
        self.digests: dict[str, str] = {}

    async def answer(self, row: dict, home) -> dict:
        from app.v2 import ask
        from app.v2 import schemas as v2

        quote, profile = homes.v2_inputs(home) if home else (None, v2.V2AskProfile())
        today = home.today if home else TODAY
        if home and home.id not in self.digests:
            self.digests[home.id] = homes.v2_digest(home)
        uid, history, out = f"eval-{row['id']}", [], None
        for t in row["turns"]:
            out = await ask.start(
                uid, v2.V2AskIn(message=t, quote=quote, profile=profile), today, history=history
            )
            for _ in range(6):  # 화면 도구(담기 제안 · 단계 카드)는 실행한 셈 쳐요
                if out.done or not out.turn:
                    break
                res = v2.V2AskResumeIn(
                    results=[{"id": c.id, "content": '{"ok": true}'} for c in out.tool_calls]
                )
                out = await ask.resume(uid, out.turn, res)
            history += [{"role": "user", "content": t}, {"role": "assistant", "content": out.text}]
        o = out.model_dump(mode="json")
        return {
            "text": render_v2(o), "raw": o, "failed": o.get("failed", False),
            "route": o.get("trade") or (o.get("intent") or {}).get("label") or o.get("gate"),
            "facts_given": self.digests.get(home.id, NO_FACTS) if home else NO_FACTS,
        }  # fmt: skip


class V3:
    name = "v3"

    def __init__(self, kb_mode: str, mode: str, same_only: bool):
        self.kb_mode, self.mode, self.same_only = kb_mode, mode, same_only
        self.ix = None

    async def kb_for(self, text: str, mode: str):
        from app.agent import llm
        from app.agent.v3 import check
        from app.agent.v3.answer import KB
        from app.config import settings
        from app.knowledge import cards

        if self.kb_mode == "repo":
            if self.ix is None:
                from v3_kb import repo_index

                self.ix = repo_index()
            return KB(ix=self.ix, cards=cards.default())
        from app.db import SessionLocal
        from app.knowledge import service as knowledge

        key = getattr(settings, "openai_api_key", None)
        use_emb = mode == "llm" or (settings.ai_embed_free and bool(key and key.get_secret_value()))
        emb = (
            await llm.embed_query(check.mask(text)[:300]) if use_emb else None
        )  # 운영 ai_turn과 같게
        async with SessionLocal() as s:
            return KB(
                ix=await knowledge.index(s),
                cards=cards.default(),
                dense=await knowledge.nearest(s, emb),
            )

    async def answer(self, row: dict, home) -> dict:
        from app.agent.v3 import check, context
        from app.agent.v3.schemas import TurnContext
        from app.agent.v3.turn import run_turn
        from app.chat import tools
        from app.chat.service import _public
        from app.chat.service import mode as chat_mode

        facts = homes.v3_facts(home, with_plan=not self.same_only) if home else None
        today = home.today if home else TODAY
        mode = chat_mode() if self.mode == "auto" else self.mode
        ctx = TurnContext(
            user_id=uuid.UUID(int=0), project_id=uuid.UUID(int=1) if facts else None,
            mode=mode, today=today,  # type: ignore[arg-type]
        )  # fmt: skip
        state = waiting = res = general = None
        for t in row[
            "turns"
        ]:  # ai_turn과 같은 순서: 질문 계산 값 → (공사 없으면 앞 턴 평수) → 이 집 크기
            general = tools.general_facts(check.mask(t), today)
            if facts is None:
                said = context.load(state)
                general = tools.with_said(
                    general, said.area if said else None, said.start if said else None, today
                )
            general.here = tools.house_size(facts)
            kb = await self.kb_for(t, mode)
            res = await run_turn(
                t, ctx, kb=kb, facts=facts, waiting=waiting, general=general, state=state
            )
            state, waiting = res.state, res.waiting
        pub = _public(res.answer).model_dump(mode="json")
        tr = res.answer.trace
        return {
            "text": render_v3(pub), "raw": pub, "failed": res.answer.failed, "route": tr.route,
            "facts_given": homes.v3_digest(facts, general),
            "trace": {"mode": tr.mode, "prompts": tr.prompts, "dropped": tr.dropped, "trades": tr.trades},
        }  # fmt: skip


# ---- 실행 ----
def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", check=False).stdout.strip()  # fmt: skip
    except OSError:
        return ""


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="v2 · v3 답 받기(같은 질문 · 같은 집)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="스텁(기본). 유료 호출 0회")
    g.add_argument("--live", action="store_true", help="실제 LLM(LLM_LIVE=true). 리드 허락 뒤에만")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--set", type=Path, default=SETS / "compare.jsonl")
    ap.add_argument("--systems", default="v2,v3")
    ap.add_argument(
        "--kb", choices=["repo", "db"], default="repo", help="repo = 저장소 지식 색인(DB 없음)"
    )
    ap.add_argument(
        "--context", choices=["project", "none"], default="project", help="집 사실을 넣을지"
    )
    ap.add_argument(
        "--same-only",
        action="store_true",
        help="v3에서도 공사 시작일 · 공정표를 빼요(v2와 똑같은 칸만)",
    )
    ap.add_argument(
        "--v3-mode",
        choices=["auto", "free", "llm"],
        default="auto",
        help="auto = 운영 chat.service.mode()",
    )
    ap.add_argument("--max-usd", type=float, help="--live에는 꼭 줘요")
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--price-model", default="claude-sonnet-5-5", help="시작 전 어림에만 써요")
    ap.add_argument("--timeout", type=float, default=120.0, help="답 하나 시간 상한(초)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help="쉼표로 질문 id")
    ap.add_argument("--source", help="core32,set30,multi45")
    ap.add_argument("--split", help="dev,heldout")
    a = ap.parse_args(argv)
    if a.live and a.max_usd is None:
        ap.error("--live에는 --max-usd가 필요해요")
    a.dry_run = not a.live
    return a


def pick_rows(a) -> list[dict]:
    rows = jsonl(a.set)
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["id"] in keep]
    if a.source:
        rows = [r for r in rows if r["source"] in a.source.split(",")]
    if a.split:
        rows = [r for r in rows if r["split"] in a.split.split(",")]
    return rows[: a.limit] if a.limit else rows


async def run(a) -> int:
    for p in (ROOT / "backend", ROOT / "backend" / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    if a.dry_run:  # 키 · 실호출 스위치를 이 프로세스에서만 꺼요(설정을 읽기 전에)
        for k in KEY_ENVS:
            os.environ.pop(k, None)
        os.environ["LLM_LIVE"] = "false"
    from app.agent import llm
    from app.config import settings

    if a.dry_run and settings.llm_live:
        sys.exit("--dry-run인데 LLM_LIVE가 켜져 있어요. 유료 호출을 막으려고 멈춰요")
    if a.live and not settings.llm_live:
        sys.exit("--live에는 LLM_LIVE=true가 필요해요")
    systems = [s for s in a.systems.split(",") if s]
    rows = pick_rows(a)
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "tag": a.tag, "mode": "dry-run" if a.dry_run else "live", "kb": a.kb, "context": a.context,
        "same_only": a.same_only, "v3_mode": a.v3_mode, "systems": systems, "set": str(a.set), "rows": len(rows),
        "homes": {k: h.text() for k, h in homes.HOMES.items()}, "head": _git("rev-parse", "HEAD"),
        "dirty": len(_git("status", "--short").splitlines()),
    }  # fmt: skip
    old = (
        json.loads((out / "meta.json").read_text("utf-8")) if (out / "meta.json").exists() else None
    )
    if old and any(old.get(k) != meta[k] for k in ("mode", "kb", "context", "same_only")):
        sys.exit(f"{out}는 다른 설정으로 돈 결과예요. 새 --tag를 써요")
    log = CostLog(out / "cost.csv", "answer")
    if a.live:
        est = bud.answer_estimate(len(rows), systems, a.price_model)["usd"]
        print(
            f"어림 ${est:.2f}(가정 budget.ASSUME · {a.price_model}) · 지금까지 ${log.spent:.4f} · 상한 ${a.max_usd}"
        )
        if log.spent + est > a.max_usd and not a.allow_partial:
            print("어림이 상한을 넘어 시작하지 않아요")
            return 2
    from app.chat.service import mode as chat_mode

    meta["v3_mode_resolved"] = chat_mode() if a.v3_mode == "auto" else a.v3_mode
    if a.live and "v3" in systems and meta["v3_mode_resolved"] != "llm":
        print(
            "주의: v3가 무료 모드로 돌아요(chat.service.mode가 llm이 아님). 필요하면 --v3-mode llm"
        )
    patch_v2_store()
    if a.kb == "repo":
        patch_v2_repo_kb()
    tap = UsageTap(llm, settings)
    meta["usage_source"] = tap.source
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    runners = {"v2": V2(), "v3": V3(a.kb, a.v3_mode, a.same_only)}
    done = {(r["id"], r["system"]) for r in jsonl(out / "answers.jsonl")}
    per = {s: bud.answer_estimate(1, [s], a.price_model)["usd"] for s in systems}
    n_ok = n_err = calls = 0
    stopped = None
    for row in rows:
        home = homes.HOMES[row["home"]] if a.context == "project" else None
        for name in systems:
            if (row["id"], name) in done:
                continue
            if a.live and log.spent + per[name] > a.max_usd:
                stopped = f"상한 ${a.max_usd}에 닿아 멈췄어요"
                break
            t0 = time.perf_counter()
            try:
                res = await asyncio.wait_for(runners[name].answer(row, home), timeout=a.timeout)
                err = None
            except Exception as e:  # noqa: BLE001 — 한 질문의 실패로 전체를 멈추지 않아요
                res, err = None, e
            ms = round((time.perf_counter() - t0) * 1000, 1)
            used = tap.take()
            calls += len(used)
            costs = [
                log.add(row["id"], name, u["model"], u["usage"], estimated=False) for u in used
            ]
            cost = None if any(c is None for c in costs) else round(sum(costs), 6)
            # 판정기에는 두 시스템이 같이 받은 집 조건만 보여요(공사 시작일 · 공정표는 v3 계산 값 쪽에 있어요)
            base = {"id": row["id"], "system": name, "mode": meta["mode"], "kb": a.kb, "turns": row["turns"],
                    "question": row["turns"][-1], "home": home.id if home else None,
                    "home_text": home.text(with_start=False) if home else homes.NO_HOME,
                    "ms": ms, "llm_calls": len(used), "cost_usd": cost}  # fmt: skip
            if err is not None:
                n_err += 1
                append_jsonl(out / "errors.jsonl", {**base, "class": type(err).__name__,
                                                    "error": str(err)[:300], "tb": traceback.format_exc(limit=4)})  # fmt: skip
                print(f"{row['id']} {name} 오류 {type(err).__name__}: {str(err)[:120]}")
                continue
            n_ok += 1
            append_jsonl(out / "answers.jsonl", {**base, **res})
            print(f"{row['id']} {name} {res['route']} {ms}ms · LLM {len(used)}번"
                  + (f" · ${cost:.4f}" if cost else ""))  # fmt: skip
        if stopped:
            break
    total = len(jsonl(out / "answers.jsonl"))
    print(f"이번 {n_ok}개 · 오류 {n_err} · 모두 {total}개 · LLM 호출 {calls}번 · 비용 ${log.real:.4f}"
          + (" · 유료 호출 0회(스텁)" if a.dry_run and calls == 0 else "")
          + (f" · 값 모름 {log.unknown}번" if log.unknown else ""))  # fmt: skip
    if stopped:
        print(stopped)
    print(f"저장: {out}")
    return 3 if stopped else (1 if n_err and not n_ok else 0)


def main(argv=None) -> int:
    utf8_stdout()
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

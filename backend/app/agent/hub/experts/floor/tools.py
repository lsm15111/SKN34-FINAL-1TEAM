"""바닥 전문가의 일: 자재 비교 · 조건 맞춤 · 체크리스트 · 업체에 물을 말 · 조건 기억.

무료 모드(offline.py)와 LLM 도구가 같은 함수를 쓴다. 화면 조각은 여기서 바로 답에 담고,
LLM에는 짧은 요약만 돌려준다(검증된 문장을 LLM이 다시 옮겨 쓰지 않게).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.hub.core import Tool, ToolOut
from app.agent.hub.experts.base import (
    Cited,
    ExpertRun,
    add_cited,
    ask_condition,
    match_option,
    search_tool,
    sources_of,
)
from app.agent.v3.schemas import CompareTable, TableRow, UiCard

# 맞춤에 쓰는 조건 순서(앞에서부터 하나씩 되묻는다). 지금 바닥은 철거 · 덧방 이야기에만 쓴다
FIT_ORDER = ("floor.family", "floor.priority")
WHO = {"직접": "직접", "업체": "업체에 확인", "같이": "업체와 같이"}


# ---- 같이 쓰는 일 ----
def material_keys(r: ExpertRun, text: str) -> list[str]:
    """질문에 나온 자재(나온 순서). '강마루' · '강화마루'처럼 겹치는 말은 긴 말이 먼저 잡혀요."""
    hits: list[tuple[int, str]] = []
    for m in r.x.pack.materials:
        pos = [text.find(w) for w in m.words if w in text]
        if pos:
            hits.append((min(pos), m.key))
    return [k for _, k in sorted(hits)]


def compare_card(r: ExpertRun, keys: list[str] | None = None) -> UiCard | None:
    if any(c.kind == "compare" for c in r.reply.cards):
        return None  # 비교표는 한 번만
    pack = r.x.pack
    mats = [pack.material(k) for k in keys] if keys else list(pack.materials)
    if len(mats) < 2:
        return None
    rows, refs = [], []
    for m in mats:
        cites = list(dict.fromkeys(c for x in (*m.good, *m.watch) for c in x.cites))
        refs.extend(cites)
        rows.append(TableRow(cells=[m.name, m.short_good, m.short_watch], cites=cites))
    r.shown.update(refs)
    r.reply.used_chunks.extend(refs)
    titles = list(dict.fromkeys(s["title"] for s in sources_of(r, refs)))
    card = UiCard(
        kind="compare",
        title="바닥재 비교",
        table=CompareTable(cols=["바닥재", "좋은 점", "살필 점"], rows=rows, sources=titles[:3]),
    )
    r.reply.cards.append(card)
    return card


def material_lines(r: ExpertRun, keys: list[str]) -> list[Cited]:
    out: list[Cited] = []
    for k in keys[:2]:
        m = r.x.pack.material(k)
        out.extend([*m.good[:1], *m.watch[:1]])
    return out


def fit(r: ExpertRun) -> tuple[list[str], list[Cited], list[str]]:
    """(잘 맞는 자재 key, 이유 문장, 아직 모르는 조건 key). 아는 조건으로만 점수를 매긴다."""
    known = r.known()
    pack = r.x.pack
    score = {m.key: 0 for m in pack.materials}
    matched = [x for x in pack.rules if all(known.get(k) == v for k, v in x.when.items())]
    for rule in matched:
        for k, v in rule.prefer.items():
            score[k] += v
    best = max(score.values()) if score else 0
    top = [k for k, v in sorted(score.items(), key=lambda p: -p[1]) if v > 0 and v >= best - 1][:2]
    why: list[Cited] = []
    for rule in matched:
        if not rule.prefer or any(rule.prefer.get(k, 0) > 0 for k in top):
            why.extend(x for x in rule.why if x not in why)
    missing = [k for k in FIT_ORDER if k not in known]
    return top, why[:4], missing


def add_fit(r: ExpertRun) -> bool:
    """조건 맞춤 묶음. 맞는 자재를 하나도 못 고르면 False."""
    top, why, _ = fit(r)
    if not top:
        return False
    pack = r.x.pack
    known = r.known()
    said = " · ".join(
        known[c.key] for c in pack.conditions if c.key in known and known[c.key] != "해당 없음"
    )
    names = " · ".join(pack.material(k).name for k in top)
    lead = Cited(
        text=f"말씀하신 조건({said or '알려 주신 것'})으로 보면 {names} 쪽이 잘 맞는 편이에요."
    )
    caution = pack.notes.get("recommend_caution", [])
    add_cited(r, [lead, *why, *caution], title="[바닥] 우리 집에 맞는 바닥재")
    return True


def add_checklist(r: ExpertRun, phase: str) -> bool:
    cl = r.x.pack.checklists.get(phase)
    if cl is None or any(s.title == f"[바닥] {cl.title}" for s in r.reply.sections):
        return False
    lines = [Cited(text=f"{WHO.get(i.who, i.who)} · {i.text}", cites=i.cites) for i in cl.items]
    add_cited(r, lines, title=f"[바닥] {cl.title}")
    return True


def add_vendor(r: ExpertRun, topics: list[str], limit: int = 3) -> list[str]:
    """업체에 보낼 말(고객이 복사해 보냄). 주제가 맞는 것부터, 지금 바닥이 붙인 마루면 철거 질문을 앞에."""
    want = set(topics)
    if r.known().get("floor.now") in ("강마루", "원목마루"):
        want.add("demolish")
    picked = [q for q in r.x.pack.vendor_questions if want & set(q.topics)]
    if "demolish" in want:
        picked.sort(key=lambda q: "demolish" not in q.topics)
    lines = [q.text for q in picked[:limit]]
    refs = [c for q in picked[:limit] for c in q.cites]
    r.shown.update(refs)
    r.reply.used_chunks.extend(refs)
    r.reply.vendor = list(dict.fromkeys([*r.reply.vendor, *lines]))[:limit]
    return lines


def remember(r: ExpertRun, key: str, value: str) -> str | None:
    cond = r.x.pack.condition(key)
    if cond is None:
        return None
    got = match_option(cond, value)
    if got:
        r.reply.memory[key] = got
    return got


# ---- LLM 도구 ----
class CompareArgs(BaseModel):
    materials: list[str] = Field(
        default=[], max_length=5, description="견줄 자재 key. 비우면 바닥재 다섯 가지 전부"
    )


def _compare(r: ExpertRun, a: CompareArgs) -> ToolOut:
    keys = [k for k in a.materials if any(m.key == k for m in r.x.pack.materials)]
    card = compare_card(r, keys if len(keys) >= 2 else None)
    mats = [r.x.pack.material(k) for k in keys] if len(keys) >= 2 else list(r.x.pack.materials)
    lines = [
        f"{m.name}: 좋은 점 {' / '.join(f'{x.text} {x.cites}' for x in m.good)} · "
        f"살필 점 {' / '.join(f'{x.text} {x.cites}' for x in m.watch)}"
        for m in mats
    ]
    refs = tuple(c for m in mats for x in (*m.good, *m.watch) for c in x.cites)
    note = "비교표를 화면에 붙였어요." if card else "비교표는 이미 붙였어요."
    return ToolOut(text="\n".join([note, *lines]), refs=refs)


class NoArgs(BaseModel):
    pass


def _fit(r: ExpertRun, _: NoArgs) -> ToolOut:
    top, why, missing = fit(r)
    pack = r.x.pack
    lines = []
    if top:
        lines.append("잘 맞는 편: " + " · ".join(pack.material(k).name for k in top))
        lines += [f"이유: {x.text} {x.cites}" for x in why]
    else:
        lines.append("아는 조건만으로는 고르기 어려워요.")
    if missing:
        lines.append("아직 모르는 조건(하나만 되물어요): " + ", ".join(missing))
    refs = tuple(c for x in why for c in x.cites)
    return ToolOut(text="\n".join(lines), refs=refs)


class ChecklistArgs(BaseModel):
    phase: Literal["before", "after"] = Field(
        description="before=공사 전 할 일, after=공사 끝나고 확인"
    )


def _checklist(r: ExpertRun, a: ChecklistArgs) -> ToolOut:
    added = add_checklist(r, a.phase)
    cl = r.x.pack.checklists[a.phase]
    refs = tuple(c for i in cl.items for c in i.cites)
    head = (
        "체크리스트를 화면에 붙였어요(답 글에서 항목을 되풀이하지 마세요)."
        if added
        else "이미 붙였어요."
    )
    return ToolOut(text=f"{head} {cl.title}: 항목 {len(cl.items)}개", refs=refs)


class VendorArgs(BaseModel):
    topics: list[
        Literal["quote", "visit", "before", "after", "demolish", "product", "overlay", "method"]
    ] = Field(min_length=1, max_length=3, description="물을 주제")


def _vendor(r: ExpertRun, a: VendorArgs) -> ToolOut:
    lines = add_vendor(r, list(a.topics))
    if not lines:
        return ToolOut(text="맞는 질문이 없어요.")
    return ToolOut(
        text="업체에 보낼 말을 화면에 붙였어요(고객이 복사해 보내요): " + " / ".join(lines)
    )


class RememberArgs(BaseModel):
    key: str = Field(description="브리프 칸 key(예: floor.family)")
    value: str = Field(max_length=40, description="고객이 말한 값(선택지 글 그대로)")


def _remember(r: ExpertRun, a: RememberArgs) -> ToolOut:
    got = remember(r, a.key, a.value)
    if got is None:
        return ToolOut(text="칸 key나 값이 선택지에 없어요. 고객이 분명히 말한 것만 담아요.")
    return ToolOut(text=f"기억했어요: {a.key}={got}")


class AskArgs(BaseModel):
    key: str = Field(description="되물을 브리프 칸 key")


def _ask(r: ExpertRun, a: AskArgs) -> ToolOut:
    ok = ask_condition(r, a.key)
    return ToolOut(text="되묻기 버튼을 붙였어요." if ok else "이미 알거나 없는 칸이에요.")


def tools() -> tuple[Tool, ...]:
    return (
        search_tool("floor"),
        Tool(
            "compare_materials",
            "바닥재(장판 · 강마루 · 강화마루 · 원목마루 · 데코타일)의 좋은 점 · 살필 점을 근거와 함께 받고, "
            "화면에 비교표를 붙인다. 자재를 견주거나 고르는 질문에 쓴다.",
            CompareArgs,
            _compare,
        ),
        Tool(
            "fit_materials",
            "지금까지 알게 된 조건(가족 · 중요한 것 · 지금 바닥)으로 잘 맞는 바닥재와 이유를 받는다. "
            "조건이 모자라면 무엇을 물을지 알려 준다.",
            NoArgs,
            _fit,
        ),
        Tool(
            "add_checklist",
            "반셀프 고객이 할 일 체크리스트를 화면에 붙인다(공사 전 할 일 · 공사 끝나고 확인).",
            ChecklistArgs,
            _checklist,
        ),
        Tool(
            "draft_vendor_questions",
            "고객이 바닥 업체에 복사해 보낼 질문(견적 · 실측 · 시공 뒤)을 만들어 화면에 붙인다.",
            VendorArgs,
            _vendor,
        ),
        Tool(
            "remember_condition",
            "고객이 자기 집 조건을 분명히 말했을 때(예: '강아지 키워요') 브리프 칸에 담는다. 짐작은 담지 않는다.",
            RememberArgs,
            _remember,
        ),
        Tool(
            "ask_condition",
            "맞춤 답에 꼭 필요한 조건 하나를 버튼으로 되묻는다. 한 턴에 하나만.",
            AskArgs,
            _ask,
        ),
    )

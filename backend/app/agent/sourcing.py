"""가견적 에이전트: 후보 업체마다 '왜 이 업체' 한 줄, 받는 길마다 요청문 초안을 쓴다 (읽기 전용).

- 후보 · 받는 길 · 비용은 코드(quote.sourcing)가 정했다. LLM은 설명과 초안만 쓴다. DB에 쓰지 않는다.
- 숫자는 코드가 입력에 넣은 것만 쓸 수 있다. 입력에 없는 숫자가 든 글은 버린다.
- 후보 목록 밖 id, 요청하지 않은 받는 길, 링크 · 이메일 · '@'가 든 글도 버린다.
- 다 버려지면 LlmError. 부른 쪽은 설명 없이 목록만 보여 준다 (규칙으로 만든 가짜 설명을 채우지 않는다).
- 초안은 업체마다가 아니라 받는 길마다 하나다. 업체마다 같은 글이라 토큰을 아낀다.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agent import llm

PROMPT_VERSION = "sourcing-v1"
SYSTEM = (Path(__file__).parent / "prompts" / "sourcing_v1.md").read_text(encoding="utf-8")
EFFORT = "low"  # 짧은 글쓰기라 생각을 적게. 역할별 설정이 생기면 그쪽으로 옮긴다
MAX_NOTES = 20  # 설명을 받을 후보 수 (앞에서부터)
WHY_LIMIT, DRAFT_LIMIT = 120, 600
DRAFT_ROUTES = ("app_request", "proxy", "link", "phone")
ROUTE_NAME = {
    "app_request": "앱 안 요청",
    "proxy": "믿집이 대신 보내는 문자",
    "link": "업체 견적 창구에 붙여 넣기",
    "phone": "전화로 말하기",
    "reference": "정보만 보기",
}
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_CONTACT = re.compile(r"https?://|www\.|@|tel:", re.IGNORECASE)


class VendorWhy(BaseModel):
    id: str
    why: str


class RouteDraft(BaseModel):
    route: Literal["app_request", "proxy", "link", "phone"]
    text: str


class SourcingNotes(BaseModel):
    """가견적 에이전트 출력. 숫자 · 길이 검사는 코드가 한다."""

    reasons: list[VendorWhy]
    drafts: list[RouteDraft]


@dataclass(frozen=True)
class Candidate:
    """LLM에 보여 줄 후보 한 곳 (연락처 값 · 링크 없이)"""

    key: str  # 코드가 붙인 짧은 id. 숫자가 없어야 허용 숫자에 섞이지 않는다
    name: str
    kind: str  # 앱 · 외부
    trades: str
    region: str
    route: str
    cost: str
    basis: str  # 근거: 등록 정보 · 견적 창구 · 포트폴리오 유무


@dataclass(frozen=True)
class Notes:
    why: dict[str, str]  # 후보 key → 한 줄
    drafts: dict[str, str]  # 받는 길 → 초안
    dropped: int  # 규칙을 어겨 버린 항목 수


def keys(n: int) -> list[str]:
    """va, vb, … (숫자 없는 id)"""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return [f"v{letters[i // 26 - 1] if i >= 26 else ''}{letters[i % 26]}" for i in range(n)]


def render(facts: list[str], cands: list[Candidate], routes: list[str]) -> str:
    rows = "\n".join(
        f"- {c.key} | {c.name} | {c.kind} | {c.trades} | {c.region} | {ROUTE_NAME[c.route]}"
        f" | {c.cost} | {c.basis}"
        for c in cands
    )
    want = ", ".join(f"{r}({ROUTE_NAME[r]})" for r in routes) or "없음"
    return (
        "<input>\n집 정보:\n"
        + "\n".join(f"- {f}" for f in facts)
        + f"\n\n후보 업체 (id | 이름 | 구분 | 공정 | 지역 | 받는 길 | 비용 | 근거):\n{rows}"
        + f"\n\n요청문을 쓸 받는 길: {want}\n</input>"
    )


def _norm(n: str) -> str:
    n = n.replace(",", "")
    return n if "." in n else n.lstrip("0") or "0"  # '01' = '1'


def allowed_numbers(text: str) -> set[str]:
    return {_norm(n) for n in _NUM.findall(text)}


def _ok(text: str, limit: int, allowed: set[str]) -> bool:
    t = text.strip()
    if not t or len(t) > limit or _CONTACT.search(t):
        return False
    return all(_norm(n) in allowed for n in _NUM.findall(t))


def validate(raw: SourcingNotes, known: set[str], routes: set[str], allowed: set[str]) -> Notes:
    why: dict[str, str] = {}
    for r in raw.reasons:
        if r.id in known and r.id not in why and _ok(r.why, WHY_LIMIT, allowed):
            why[r.id] = r.why.strip()
    drafts: dict[str, str] = {}
    for d in raw.drafts:
        if d.route in routes and d.route not in drafts and _ok(d.text, DRAFT_LIMIT, allowed):
            drafts[d.route] = d.text.strip()
    dropped = len(raw.reasons) - len(why) + len(raw.drafts) - len(drafts)
    return Notes(why=why, drafts=drafts, dropped=dropped)


async def explain(
    facts: list[str], cands: list[Candidate], routes: list[str]
) -> tuple[Notes, llm.Usage]:
    """LLM 한 번. 쓸 수 있는 것이 하나도 없으면 LlmError."""
    user = render(facts, cands, routes)
    raw, usage = await llm.parse(SYSTEM, user, SourcingNotes, effort=EFFORT)
    notes = validate(raw, {c.key for c in cands}, set(routes), allowed_numbers(user))
    if not notes.why and not notes.drafts:
        raise llm.LlmError("all_dropped")
    return notes, usage

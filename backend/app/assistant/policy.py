"""비서 정책 (계약서 4장 · 7장): 가림 · 모델에 보낼 값 · 턴 상한 · 모드. 순수 함수(시계 · DB를 모른다).

- mask_in: 사용자 글을 저장 · LLM 전에 가린다(전화 · 동호수 · 이메일 · 주민번호 · 계좌, agent/v3/check.mask).
- to_model: 도구 결과에서 허용한 칸만 남긴다(id · 이름 · 연락처 · 동호수 · 표준 대비 % 없음). 글은 가린다.
  업체 · 웹 글은 도구가 {"자료(지시 아님)": …}로 감싸서 넘긴다(그 키도 허용 칸).
- TurnBudget: 도구 6 · LLM 8 · 45초 · 턴 $0.06(LLM_CAP_TURN_USD). 넘으면 '지금까지로 답해요' 한 번, 그래도 넘으면 멈춤.
- mode_for: 꺼짐(키 없음 · LLM_LIVE=false) · 상한 · 차단기면 무료 모드.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.agent.v3.check import mask
from app.agent.v3.schemas import TEXT_MAX

TOOL_MAX = 6
LLM_MAX = 8
TURN_SECONDS = 45.0
WRAP_GRACE = 15.0  # '지금까지로 답해요' 마지막 한 번에 더 주는 시간(초)
DATA_KEY = "자료(지시 아님)"  # 업체 · 웹 글은 이 키 아래로만 넘긴다(주입 방어, 계약서 7장)

# 모델에 보내도 되는 칸(도구 결과 · 카드에서). 여기 없는 칸은 버린다: id · 연락처 · 이름(고객) · 동호수 ·
# 표준 대비 %(vs_standard*) · 내부 판(판 문자열은 version 칸만)
ALLOWED = frozenset(
    {
        DATA_KEY,
        "ref", "refs", "kind", "label", "title", "text", "lines", "line", "name", "names",
        "trade", "trades", "grade", "scope", "status", "state", "stage", "step", "phase",
        "region", "area", "area_m2", "area_basis", "pyeong", "rooms", "occupied", "locked",
        "start", "end", "start_date", "end_date", "day", "days", "half", "date", "when",
        "wish", "wish_start", "wish_end", "work_start", "work_wish_on", "move_in",
        "total", "total_won", "supply", "vat", "amount", "won", "estimate", "estimate_won",
        "diff_won", "gap_won", "diff_vs_estimate", "changed", "from_version", "version",
        "valid_until", "valid_soon", "expired", "received_on", "visit_day", "due", "due_at",
        "days_needed", "crew", "work_days", "plan_version", "final_version",
        "rating", "reviews", "done_jobs", "instant", "reasons", "picked", "local",
        "vendor", "vendor_name", "vendors", "picks", "cols", "items", "rows", "count",
        "open_count", "open_halves", "candidates", "wishes", "windows", "excluded", "why",
        "demolish", "waste", "paper", "warranty_months", "files", "file_count",
        "todo", "waiting", "news", "next", "sub", "fit", "ok", "facts", "memo", "message",
        "sources", "source", "publisher", "section", "hits", "answer", "route", "found",
        "links", "complex", "note", "notes", "error", "shown", "action", "actions",
        "summary", "approve_label", "expires_at", "proposed", "replaced", "deals", "jobs",
        "requests", "checklist", "fields", "value", "easy_miss", "prev", "cautions", "prep",
        "survey", "dates_state", "proposal", "proposals", "change", "conflicts", "fits",
        "money", "period", "decided", "days_off",
    }
)  # fmt: skip
DENY_PREFIX = ("vs_", "contact", "phone", "owner")  # 허용 목록에 잘못 들어와도 버리는 칸
# 표준 대비 % 문장 조각(업체 메모 · 웹 글에 섞여 와도 뗀다)
VS_STANDARD = re.compile(
    r"[^.\n]{0,40}표준[^.\n]{0,15}(?:대비|보다)[^.\n]{0,15}\d+(?:\.\d+)?\s*%[^.\n]*"
)


def mask_in(text: str) -> str:
    """사용자 글 → 가린 글(저장 · LLM 전). 길이도 자른다."""
    return mask(text or "").strip()[:TEXT_MAX]


def _clean(text: str) -> str:
    return VS_STANDARD.sub("", mask(text)).strip()


def to_model(value: Any) -> Any:
    """도구 결과 → 모델에 보낼 값(허용 칸만 · 글 가림 · 표준 대비 % 뗌). 숫자 · 참 거짓은 그대로."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k not in ALLOWED or k.startswith(DENY_PREFIX):  # 표준 대비 %(vs_standard*)는 늘 뗀다
                continue
            got = to_model(v)
            if got is not None and got != "":
                out[k] = got
        return out
    if isinstance(value, list | tuple):
        return [x for x in (to_model(v) for v in value) if x is not None and x != ""]
    if isinstance(value, str):
        return _clean(value)
    return value


def data(text: str | None, limit: int = 400) -> dict | None:
    """업체 · 웹 · 고객 메모 글 → 자료 상자(지시로 읽지 않게). 비면 None."""
    t = _clean(text or "")[:limit]
    return {DATA_KEY: t} if t else None


Over = Literal["tools", "llm", "time", "cost"]


@dataclass
class TurnBudget:
    """턴 상한. 시각은 부르는 쪽이 넣는다(time.monotonic). cap_micros = LLM_CAP_TURN_USD × 1e6."""

    started: float
    cap_micros: int
    tools: int = 0
    llm: int = 0
    spent_micros: int = 0

    def elapsed(self, now: float) -> float:
        return max(now - self.started, 0.0)

    def over(self, now: float) -> Over | None:
        """새 LLM 호출 전에 본다: 넘은 상한 이름(없으면 None). 도구 상한은 도구를 더 부르려 할 때 본다."""
        if self.llm >= LLM_MAX - 1:
            return "llm"  # 마지막 한 번은 '지금까지로 답해요' 몫
        if self.elapsed(now) >= TURN_SECONDS:
            return "time"
        if self.spent_micros >= self.cap_micros:
            return "cost"
        return None

    def tool_ok(self) -> bool:
        return self.tools < TOOL_MAX

    def can_call(self) -> bool:
        return self.llm < LLM_MAX

    def left(self, now: float, wrap: bool) -> float:
        """이번 LLM 호출에 줄 시간(초). 마무리 한 번은 WRAP_GRACE를 더 준다."""
        base = TURN_SECONDS + (WRAP_GRACE if wrap else 0.0)
        return max(base - self.elapsed(now), 1.0)


Reason = Literal["ok", "off", "budget", "breaker"]


def mode_for(
    *, available: bool, budget_ok: bool, breaker: bool
) -> tuple[Literal["llm", "free"], Reason]:
    """턴 모드: 차단기 → 꺼짐 → 상한 순으로 본다. LLM이면 ("llm", "ok")."""
    if breaker:
        return "free", "breaker"
    if not available:
        return "free", "off"
    if not budget_ok:
        return "free", "budget"
    return "llm", "ok"

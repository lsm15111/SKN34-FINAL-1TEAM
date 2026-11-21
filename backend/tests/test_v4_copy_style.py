"""v4 비서 글 모양 시험(docs/v4/06-answer-audit.md): 코드에 박힌 틀과 무료 모드 글을 모아 R3('요' 끝) ·
R4(영어 상태값 · 도구 이름 · 이름표 · 코드 키) · R11(마크다운 · 한자 · 이모지 · 영어 낱말) · R14(표준 대비 % · VAT) ·
길이(R2)를 본다. LLM 없음(유료 호출 0회), 검사 함수는 evaluation/v4/style_lint.py.

- 틀: 소스(app/assistant)에서 AST로 모은다(파일:줄). 도구 오류 · 409 · 실행 결과 · 승인 카드 요약 · 카드 위 한 줄 ·
  도구 상태 줄 · 정해 둔 답 글. 먼저 말 걸기 틀(proactive.TRIGGERS)과 업체 브리핑 틀은 실제 함수로 채워 본다.
- 무료 모드 글: evaluation/v4/sets(compare · redteam)의 질문과 시뮬레이터 대본(sets/scenarios)의 말을 무료 모드 턴으로
  돌려 답 · 카드 · 승인 카드 · 실행 결과 · 다음에 물을 말 · 칩 · 상태 줄을 모은다.
- 지금 통과하는 (길, 규칙)만 켠다. 걸리는 조합은 OFF에 보고서 '고칠 목록' 번호와 함께 두고, 고치면 지운다.
- 질문 묶음은 기본으로 고정 표본만 돌린다. COPY_STYLE_FULL=1이면 전부, COPY_STYLE_DUMP=<파일>이면 모은 글을
  JSON 줄로 덧붙여 쓴다(보고서 숫자용).
"""

import ast
import importlib.util
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import days, propose
from tests.test_dates import ready as dates_ready
from tests.test_deal import setup as deal_setup
from tests.test_v3_visit_kit import customer, offered, requested, vendor
from tests.test_v4_assistant_turns import ask, events
from tests.test_visit_inbox import login

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
SETS = ROOT / "evaluation" / "v4" / "sets"


def _lint():
    """evaluation/v4/style_lint.py(표준 라이브러리만)를 이름이 겹치지 않게 불러온다."""
    name = "v4_style_lint"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "evaluation/v4/style_lint.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sl = _lint()

# 켜는 규칙: R2(kind로 answer 3문장 · line 60자 한 줄 · note 2문장) · R3 · R4 · R11 · R13 · R14.
# 지금 걸리는 (길, 규칙)만 OFF에 두고 보고서 '고칠 목록' 번호를 적는다. 고치면 OFF에서 지운다
ALL = frozenset({"R2", "R3", "R4", "R11", "R13", "R14"})
OFF: dict[str, dict[str, str]] = {
    # 4문장 넘음 · '[도배]' 묶음 이름표 · 따옴표 인용
    "무료 · 답 글(지식 답 answer_only)": {"R2": "#5", "R3": "#5", "R11": "#5"},
}  # fmt: skip


def on(group: str) -> frozenset[str]:
    return ALL - set(OFF.get(group, {}))


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def free_mode(monkeypatch):
    from app.assistant import service

    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    monkeypatch.setattr(service, "TURNS_PER_HOUR", 100_000)  # 질문 묶음을 한 사람이 다 돌린다
    yield
    llm.clear_stubs()


# ---- 모은 글 ----


class Bag:
    """모은 글: (길, kind, 글, 어디서). 같은 (길, 글)은 한 번만."""

    def __init__(self, test: str) -> None:
        self.test = test
        self.rows: list[dict] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, group: str, kind: str, text, where: str = "", q: str = "") -> None:
        if not isinstance(text, str) or not text.strip() or (group, text) in self._seen:
            return
        self._seen.add((group, text))
        self.rows.append({"group": group, "kind": kind, "text": text, "where": where, "q": q})

    def dump(self) -> None:
        path = os.environ.get("COPY_STYLE_DUMP")
        if not path:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(
                json.dumps({"test": self.test, **r}, ensure_ascii=False) + "\n" for r in self.rows
            )

    def failures(self) -> dict[str, list[str]]:
        """켠 (길, 규칙)에 걸린 글. {길 · 규칙: ['글 ← 어디서 · 까닭']}"""
        out: dict[str, list[str]] = {}
        for r in self.rows:
            rules = on(r["group"])
            for h in sl.check(r["text"], r["kind"]):
                if h.rule in rules and not (h.rule == "R11" and h.why == "영어 약어"):
                    key = f"{r['group']} · {h.rule}"
                    out.setdefault(key, []).append(f"{r['text'][:60]} ← {r['where']} · {h.why}")
        return out

    def assert_style(self) -> None:
        self.dump()
        bad = self.failures()
        assert not bad, json.dumps(bad, ensure_ascii=False, indent=1)


# ---- 틀: 소스에서 모으기(AST) ----

# 렌더할 때 f-string 자리에 넣는 값: 이름표 · 도구 이름이 들어가는 자리는 실제 꼴로(R4를 보려고), 나머지는 기호
SLOT = {"ref": "v1", "other": "propose_delay_accept"}


def _render(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            else:
                src = ast.unparse(v.value)
                out.append(next((x for k, x in SLOT.items() if src == k or src.endswith(k)), "○"))
        return "".join(out)
    return None


def _strings(node: ast.AST) -> list[tuple[int, str]]:
    """식 하나에서 글(상수 · f-string · 조건식 두 갈래)을 꺼낸다."""
    if isinstance(node, ast.IfExp):
        return _strings(node.body) + _strings(node.orelse)
    got = _render(node)
    return [(node.lineno, got)] if got is not None else []


def _name(f: ast.AST) -> str:
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


# (부르는 이름, 인자 자리 또는 키워드) → (길, kind)
CALLS = {
    ("ToolError", 1): ("틀 · 도구 오류 문장", "note"),
    ("AppError", 2): ("틀 · 409 · 오류 문장", "note"),
    ("_stale", 0): ("틀 · 409 · 오류 문장", "note"),
    ("ActionSummary", "title"): ("틀 · 승인 카드 제목 · 단추", "label"),
    ("ActionSummary", "approve_label"): ("틀 · 승인 카드 제목 · 단추", "label"),
    ("ActionSummary", "version"): ("틀 · 승인 카드 제목 · 단추", "label"),
    ("ActionSummary", "note"): ("틀 · 승인 카드 안내 줄", "note"),
    ("SummaryRow", "label"): ("틀 · 승인 카드 칸", "label"),
    ("SummaryRow", "value"): ("틀 · 승인 카드 칸", "label"),
    ("SummaryRow", "sub"): ("틀 · 승인 카드 칸", "label"),
    ("CardOut", "say"): ("틀 · 카드 위 한 줄", "line"),
    ("tool", "status"): ("틀 · 도구 상태 줄", "note"),
    ("TodayRow", "title"): ("틀 · 카드 칸 이름", "label"),
    ("TodayRow", "sub"): ("틀 · 카드 칸 이름", "label"),
    ("LinkOut", "label"): ("틀 · 카드 칸 이름", "label"),
    ("RowAction", "label"): ("틀 · 카드 칸 이름", "label"),
    ("FitRow", "label"): ("틀 · 카드 칸 이름", "label"),
    ("FitRow", "text"): ("틀 · 카드 칸 이름", "label"),
    ("FieldValue", "label"): ("틀 · 카드 칸 이름", "label"),
    ("KnowledgeData", "title"): ("틀 · 카드 칸 이름", "label"),
    ("BriefEstimate", "basis"): ("틀 · 카드 칸 이름", "label"),
    ("ChecklistRow", "hint"): ("틀 · 카드 안내 줄", "note"),
    ("TaskOut", "title"): ("틀 · 카드 칸 이름", "label"),
}
# 모듈 상수(이름) → (길, kind). 모델에만 가는 글(WRAP · 지시문 · 턴 사실 · 도구 설명)과 숨기는 글(CARDS_ONLY)은 넣지 않는다
FREE_NAMES = (
    "NO_PICKS", "PICKS", "WISHES", "NO_WISHES", "HALVES", "VISITS", "QUOTES", "NO_QUOTES",
    "NO_DATES", "DATES", "PLAN", "STANDARD", "STANDARD_NO_TOTAL", "TODAY", "TODAY_NONE", "HOME",
    "OTHER_TRADE", "MEMORY_GUIDE", "NO_VISIT", "DECLINED", "WINDOW", "NO_WINDOW", "ANSWERED",
    "CHECKLIST", "VENDOR_TODAY",
    "VISITS_WAIT", "VISITS_BOOKED", "VISITS_DONE", "CONFIRMED", "DATES_OPEN", "CHANGE_NONE",
    "CHANGE_HOW", "CHANGE_HOW_EARLY", "CHANGE_MADE", "CHANGE_SAME", "CHANGE_REJECTED",
    "STANDARD_DAYS", "MEMORY_SAY", "SMALL_TALK_HI", "SMALL_TALK", "LEGAL", "PREFS",
    "DECLINE_REJECTED", "WINDOW_REJECTED", "BRIEF", "ACCEPT_RULE",
    # QA 1차 무료 모드(거르는 말 · 지금 할 일 · 돈 질문 · 칩 · 다른 공정 · 업체 추천)
    "SECRET_SAID", "CONTACT_SAID", "VENDOR_CONTACT", "OFF_SAID", "ENGLISH_SAID", "ANGRY_SAID",
    "NOW_NONE", "VENDOR_NOW", "NOW", "NOW_VISIT",
    "EXTRA_HOW", "WASTE_BEFORE",
    "INCL_ASK", "INCL_NO", "DEMO_DIFF", "DELEGATE_SAID", "ESTIMATE_SAID", "VISIT_WHAT_SAID",
    "SLOTS_MORE", "SLOTS_DAY", "SLOTS_NO_DAY", "EVE_SAID", "ORDER_SAID", "PET_SAID", "ACCESS_SAID",
    "ACCESS_CARD", "PICKS_MORE", "PICKS_ASKED", "PICKS_CHOSEN",
    "OTHER_LINK", "OTHER_MONEY", "FREE_ASK",
)  # fmt: skip
CONSTS = {
    "free.py": {n: ("틀 · 무료 모드 정해 둔 답", "answer") for n in FREE_NAMES},
    "choices.py": {
        "MADE": ("틀 · 무료 모드 정해 둔 답", "answer"),
        "RELOADED": ("틀 · 무료 모드 정해 둔 답", "answer"),
        "GONE": ("틀 · 무료 모드 정해 둔 답", "answer"),
        "LABEL": ("틀 · 카드 칸 이름", "label"),
    },
    "runtime.py": {
        "FAIL_TEXT": ("틀 · 실패 · 상한 글", "answer"),
        "TOOL_FAIL": ("틀 · 실패 · 상한 글", "answer"),
        "CHIPS": ("틀 · 빠른 답 칩", "user"),
    },
    "service.py": {
        "RUNNING": ("틀 · 409 · 오류 문장", "note"),
        "TOO_MANY": ("틀 · 409 · 오류 문장", "note"),
        "FAILED": ("틀 · 실패 · 상한 글", "answer"),
        "NUDGE_GONE": ("틀 · 409 · 오류 문장", "note"),
    },
    "policy.py": {"DOBAE_ONLY": ("틀 · 무료 모드 정해 둔 답", "answer")},
    "actions.py": {
        "NOT_FOUND": ("틀 · 409 · 오류 문장", "note"),
        "CLOSED": ("틀 · 409 · 오류 문장", "note"),
    },
    "tools/floorplan.py": {"NOTE": ("틀 · 카드 안내 줄", "note")},
    "tools/cards.py": {
        "PICK_BASIS": ("틀 · 카드 안내 줄", "note"),
        "WHY": ("틀 · 카드 안내 줄", "note"),
        "NEXT_TEXT": ("틀 · 카드 칸 이름", "label"),
        "ENDED_TEXT": ("틀 · 카드 칸 이름", "label"),
    },
    "tools/propose.py": {
        "DECLINE": ("틀 · 승인 카드 칸", "label"),
        "FIELD_LABEL": ("틀 · 승인 카드 칸", "label"),
    },
    "tools/vendor.py": {"VAT": ("틀 · 카드 칸 이름", "label")},
    "memory.py": {"LABEL": ("틀 · 카드 칸 이름", "label")},
}
# 실행 결과 글(승인 뒤 카드에 남는 말): actions.py의 {"text": …} · text = … 꼴
RESULT = ("틀 · 실행 결과", "note")
# 정해 둔 답 글 자리 채우기(값은 보기)
FILL = {"area": "마포구", "n": 2, "won": "3,241,268", "vendor": "마루와벽", "version": 2, "who": "도배 공사가", "days": "2.5",
        "names": "결도배 · 마루와벽", "home": "철거 안 함이라", "day": "주말", "order": "목공 → 도배 → 바닥재"}  # fmt: skip


def _consts(tree: ast.Module, names: dict, rel: str, bag: Bag) -> None:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name not in names:
            continue
        group, kind = names[name]
        for x in _leaves(node.value):
            for line, text in _strings(x):
                try:
                    text = text.format(**FILL)
                except (KeyError, IndexError, ValueError):
                    pass
                bag.add(group, kind, text, f"app/assistant/{rel}:{line}")


def _leaves(v: ast.AST) -> list[ast.AST]:
    """상수 식 → 글이 들어 있을 잎(사전 값 · 묶음 안쪽까지 펼침). 칩 묶음의 조건('!visits')은 글이 아니라 뺀다."""
    if isinstance(v, ast.Dict):
        return [x for it in v.values for x in _leaves(it)]
    if isinstance(v, ast.List | ast.Tuple):
        return [x for it in v.elts for x in _leaves(it)]
    if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.lstrip("!").isascii():
        return []
    return [v]


def _calls(tree: ast.Module, rel: str, bag: Bag) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _name(node.func)
            for i, a in enumerate(node.args):
                if (fn, i) in CALLS:
                    for line, text in _strings(a):
                        bag.add(*CALLS[(fn, i)], text, f"app/assistant/{rel}:{line}")
            for kw in node.keywords:
                if (fn, kw.arg) in CALLS:
                    for line, text in _strings(kw.value):
                        bag.add(*CALLS[(fn, kw.arg)], text, f"app/assistant/{rel}:{line}")
        if rel != "actions.py":
            continue
        if isinstance(node, ast.Dict):  # mark({"text": …}) · result={"text": …}
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "text":
                    for line, text in _strings(v):
                        bag.add(*RESULT, text, f"app/assistant/{rel}:{line}")
        if isinstance(node, ast.Assign) and _name(node.targets[0]) == "text":
            for line, text in _strings(node.value):
                bag.add(*RESULT, text, f"app/assistant/{rel}:{line}")
        if isinstance(node, ast.Assign) and _name(node.targets[0]) == "say":
            for line, text in _strings(node.value):
                bag.add("틀 · 카드 위 한 줄", "line", text, f"app/assistant/{rel}:{line}")


def static_bag() -> Bag:
    from app.assistant import actions, proactive, service
    from app.assistant.tools import vendor as vendor_tools
    from app.calc import vendor_pick
    from app.v2 import ask as v2_ask

    bag = Bag("static")
    for path in sorted((APP / "assistant").rglob("*.py")):
        rel = path.relative_to(APP / "assistant").as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _consts(tree, CONSTS.get(rel, {}), rel, bag)
        _calls(tree, rel, bag)
        if rel.startswith("tools/"):  # card.say = … (propose.py)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "say"
                ):
                    for line, text in _strings(node.value):
                        bag.add("틀 · 카드 위 한 줄", "line", text, f"app/assistant/{rel}:{line}")
    # 범위 밖 안내(answer_question v2+v3가 넘기는 v2 글)
    bag.add("틀 · 무료 모드 정해 둔 답", "answer", v2_ask.OUT_TEXT, "app/v2/ask.py:53")
    # 먼저 말 걸기 틀: 받침 있는 · 없는 업체 이름, 고객 · 업체 지역 꼴로 채운다(proactive.template)
    for t in proactive.TRIGGERS.values():
        area = "노원구 상계동 도배" if t.surface == "vendor" else "노원구"
        for vendor_name in ("마루와벽", "믿집시험도배"):
            for channel in ("feed", "notify"):
                if not (t.notify if channel == "notify" else t.feed):
                    continue
                f = proactive.Facts(
                    trigger=t.name,
                    channel=channel,
                    surface=t.surface,
                    names={"vendor": vendor_name, "trade": "도배", "area": area},
                )
                bag.add(
                    "틀 · 먼저 말 걸기 문장",
                    "line",
                    proactive.template(f),
                    f"proactive.TRIGGERS[{t.name}].{channel}",
                )
        bag.add("틀 · 먼저 말 걸기 까닭", "note", t.why, f"proactive.TRIGGERS[{t.name}].why")
        bag.add("틀 · 다음에 물을 말(고객 · 업체 목소리)", "user", t.say, f"proactive.TRIGGERS[{t.name}].say")  # fmt: skip
    for key, (text, why, say) in {**service.STEP_IDEAS, **service.VENDOR_IDEAS}.items():
        bag.add("틀 · 다음에 물을 말", "line", text, f"service.STEP_IDEAS[{key}]")
        bag.add("틀 · 먼저 말 걸기 까닭", "note", why, f"service.STEP_IDEAS[{key}]")
        bag.add(
            "틀 · 다음에 물을 말(고객 · 업체 목소리)", "user", say, f"service.STEP_IDEAS[{key}]"
        )
    # 업체 브리핑 한 줄 틀(vendor.brief_template): 고객이 고른 반나절 · 맞지 않는 칸 · 확인 필요 칸마다 · 답하기 좋은
    # 기간 · 다 맞음
    for key, label in (
        ("trade", "공정"),
        ("area", "지역"),
        ("schedule", "일정"),
        ("paper", "벽지"),
    ):
        for state in ("no", "check"):
            fit = [SimpleNamespace(key=key, label=label, ok=False, state=state)]
            got = vendor_tools.brief_template(SimpleNamespace(fit=fit, suggest=None, picked=None))
            bag.add("틀 · 업체 브리핑 한 줄", "line", got, "tools/vendor.py:brief_template")
    good = SimpleNamespace(start=date(2026, 11, 24), end=date(2026, 11, 30), open_count=14)
    for suggest in (good, None):
        fit = [SimpleNamespace(key="trade", label="공정", ok=True, state="ok")]
        s = SimpleNamespace(fit=fit, suggest=suggest, picked=None)
        bag.add("틀 · 업체 브리핑 한 줄", "line", vendor_tools.brief_template(s), "tools/vendor.py:brief_template")  # fmt: skip
    for half in ("am", "pm"):
        picked = SimpleNamespace(day=date(2026, 11, 24), half=half)
        s = SimpleNamespace(fit=[], suggest=None, picked=picked)
        bag.add("틀 · 업체 브리핑 한 줄", "line", vendor_tools.brief_template(s), "tools/vendor.py:brief_template")  # fmt: skip
    # 확정 승인 카드 요약(actions.confirm_summary)과 업체 추천 사유(calc.vendor_pick.reasons)
    cs = actions.confirm_summary("마루와벽", 2, 3_388_000, 3, date(2026, 12, 5))
    for text, kind in ((cs.title, "label"), (cs.version, "label"), (cs.note, "note"), (cs.approve_label, "label")):  # fmt: skip
        bag.add("틀 · 승인 카드 제목 · 단추", kind, text, "actions.confirm_summary")
    c = vendor_pick.Candidate(
        vendor_id="x",
        name="결도배",
        local=False,
        estimate_total=3_000_000,
        vs_standard_pct=3,
        rating=4.7,
        review_count=3,
        done_count=3,
        instant=True,
    )
    for r in vendor_pick.reasons(vendor_pick.pick([c])[0]):
        bag.add("틀 · 카드 칸 이름", "label", r, "calc/vendor_pick.py:reasons")
    return bag


def test_style_lint_rules():
    """검사 함수 자체: 걸려야 할 글은 걸리고 맞는 글은 지나간다(LLM 기록에서 본 꼴)."""

    def rules(text: str, kind: str = "answer", **kw) -> set[str]:
        return {h.rule for h in sl.check(text, kind, **kw) if h.why != "영어 약어"}

    assert rules("집 정보예요. 고칠 칸이 있으면 말해 주세요.") == set()
    assert rules("네. 몰딩은 도배 전에 해요(목공 먼저).") == {"R1?"}
    assert "R2" in rules("하나예요. 둘이에요. 셋이에요. 넷이에요.")
    assert rules(
        "새 실측 요청이 왔어요 · 노원구 상계동 도배. 답할 기간을 골라 뒀어요.", "line"
    ) == {"R3"}
    assert "R2" in rules("가" * 61 + "요.", "line")
    assert "R3" in rules("골라 주시면 됩니다.")
    assert "R3" in rules("마루와벽로 확정", "label")
    assert rules("앞으로 결도배로 해요.") == set()
    assert "R4" in rules("이 날짜는 propose_delay_accept로 제안해 주세요.", "note")
    assert "R4" in rules("지금은 m1 요청에 카드가 있어요.")
    assert "R11" in rules("- **합계**: 3,388,000원이에요.")
    assert "R11" in rules("| 업체 | 가견적 |", "label")
    assert "R13" in rules("010-1234-5678로 연락 주세요.")
    assert "R14" in rules("표준 대비 12% 비싸요.") and "R14" in rules("VAT 별도예요.")
    assert "R6" in rules("실측 요청을 보냈어요.") and "R6" not in rules("업체가 견적서를 보냈어요.")
    assert "R6" in rules("승인 카드를 만들었어요.", cards=[], actions=[])
    assert "R6" not in rules("기억해 둘 수 없어요.")


def test_static_templates_follow_style():
    bag = static_bag()
    assert len(bag.rows) > 150  # 소스가 바뀌어 모으기가 비면 알아챈다
    bag.assert_style()


# ---- 무료 모드 턴 ----


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# 질문 묶음 전부는 고객 약 200턴(9분)이라 기본은 고정 표본(앞에서부터 n번째마다)만 돌린다.
# COPY_STYLE_FULL=1이면 전부(보고서 숫자는 전부 돌린 것)
FULL = os.environ.get("COPY_STYLE_FULL") == "1"
EVERY = {"customer": 8, "vendor": 2}


def questions(surface: str) -> list[tuple[str, str]]:
    """질문 묶음(compare · redteam)과 시뮬레이터 대본의 말(처음 말 · 말 · 누름의 다시 묻기). 같은 말은 한 번.
    FULL이 아니면 고정 표본만."""
    out: list[tuple[str, str]] = []
    if surface == "customer":
        for r in _jsonl(SETS / "compare.jsonl"):
            out += [(f"compare:{r['id']}", t) for t in r["turns"]]
    for r in _jsonl(SETS / "redteam.jsonl"):
        if r["surface"] == surface:
            out += [(f"redteam:{r['id']}", t) for t in r["turns"] if isinstance(t, str)]
    for f in sorted((SETS / "scenarios").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("surface") != surface:
            continue
        says = [d.get("opening")] + [
            t.get("say") or (t.get("press") or {}).get("ask") for t in d["script"]["turns"]
        ]
        out += [(f"sim:{d['id']}", s) for s in says if s]
    seen: set[str] = set()
    got = [(src, q) for src, q in out if not (q in seen or seen.add(q))]
    return got if FULL else got[:: EVERY[surface]]


FREE = "무료 · "


def _answer_group(text: str) -> str:
    """정해 둔 길의 답(free · choices 틀로 시작)인지, 지식 답(answer_only)인지."""
    from app.assistant import choices, free, policy, runtime

    heads = [
        getattr(free, n).split("{")[0][:12]
        for n in CONSTS["free.py"]
        if isinstance(getattr(free, n), str)
    ] + [choices.MADE[:12], choices.RELOADED[:12], choices.GONE[:12], policy.DOBAE_ONLY[:12]]
    if text.startswith(runtime.FAIL_TEXT[:12]):
        return FREE + "실패 글"
    if any(h and text.startswith(h) for h in heads) or "곳을 믿집 점수로 골랐어요" in text:
        return FREE + "답 글(정해 둔 길)"
    return FREE + "답 글(지식 답 answer_only)"


def collect(bag: Bag, ev: list, q: str) -> list[dict]:
    """턴 이벤트 → 보이는 글. 돌려주는 값: 이번 턴의 열린 승인 카드(ActionOut)."""
    opened = []
    for name, d, _ in ev:
        if name == "card":
            card(bag, d, q)
        elif name == "action":
            summary(bag, d, q)
            if d["status"] == "proposed":
                opened.append(d)
        elif name == "status":
            t = d.get("task") or {}
            if not t:  # 작업 카드가 오면 text는 작업 카드 제목이다(이름표)
                bag.add(FREE + "도구 상태 줄", "note", d.get("text"), "SSE status", q)
            bag.add(FREE + "작업 카드", "label", t.get("title"), "SSE status.task", q)
            for r in t.get("rows") or []:
                bag.add(FREE + "작업 카드", "label", r.get("text"), "SSE status.task", q)
                bag.add(FREE + "작업 카드", "label", r.get("note"), "SSE status.task", q)
            bag.add(FREE + "작업 카드", "label", (t.get("link") or {}).get("label"), "SSE status.task", q)  # fmt: skip
        elif name == "done":
            for c in d.get("chips") or []:
                bag.add(FREE + "빠른 답 칩", "user", c, "SSE done.chips", q)
            for s in d.get("suggest") or []:
                bag.add(FREE + "다음에 물을 말", "line", s.get("text"), "SSE done.suggest", q)
                bag.add(FREE + "다음에 물을 말 까닭", "note", s.get("why"), "SSE done.suggest", q)
                bag.add(FREE + "빠른 답 칩", "user", s.get("say"), "SSE done.suggest", q)
        elif name == "error":
            bag.add(FREE + "409 · 오류 문장", "note", d.get("message"), "SSE error", q)
    return opened


def card(bag: Bag, c: dict, q: str = "") -> None:
    """카드 하나에서 화면 글(업체 · 고객이 쓴 글 · 웹 제목은 빼요)."""
    k, d = c["kind"], c.get("data") or {}
    where = f"card:{k}"
    bag.add(FREE + "카드 위 한 줄", "line", c.get("say"), where, q)
    lab = FREE + "카드 칸 이름"
    if k == "answer":
        group = FREE + "카드 단추 답(choices)" if q.startswith("press") else _answer_group(d.get("text") or "")  # fmt: skip
        bag.add(group, "answer", d.get("text"), where, q)
    elif k == "knowledge":
        bag.add(lab, "label", d.get("title"), where, q)
        bag.add(lab, "label", d.get("source"), where, q)
        for x in d.get("lines") or []:
            bag.add(FREE + "카드 · 지식 발췌 줄", "note", x, where, q)
        for x in d.get("checklist") or []:
            bag.add(lab, "label", x.get("label"), where, q)
    elif k == "vendor_picks":
        for x in d.get("basis") or []:
            bag.add(FREE + "카드 안내 줄", "note", x, where, q)
        for p in d.get("picks") or []:
            for r in p.get("reasons") or []:
                bag.add(lab, "label", r, where, q)
            bag.add(lab, "label", p.get("badge"), where, q)
    elif k == "visit_slots":
        for x in d.get("candidates") or []:
            for w in x.get("why") or []:
                bag.add(FREE + "카드 안내 줄", "note", w, where, q)
    elif k == "quote_compare":
        for col in d.get("cols") or []:
            bag.add(lab, "label", col.get("wait_note"), where, q)
            bag.add(lab, "label", (col.get("file") or {}).get("label"), where, q)
        for x in d.get("ask_chips") or []:
            bag.add(FREE + "빠른 답 칩", "user", x, where, q)
    elif k == "schedule":
        for x in d.get("conflicts") or []:
            bag.add(lab, "label", x, where, q)
        for x in d.get("days") or []:
            bag.add(lab, "label", x.get("am"), where, q)
    elif k == "today":
        for part in ("todo", "waiting", "news", "know"):
            for r in d.get(part) or []:
                bag.add(lab if part != "news" else FREE + "카드 · 새 소식 줄", "label" if part != "news" else "note", r.get("title"), where, q)  # fmt: skip
                bag.add(lab, "label", r.get("sub"), where, q)
                bag.add(lab, "label", (r.get("action") or {}).get("label"), where, q)
    elif k == "home_info":
        for x in d.get("facts") or []:
            bag.add(lab, "label", x, where, q)
        for x in d.get("changes") or []:
            bag.add(lab, "label", x.get("label"), where, q)
            bag.add(lab, "label", x.get("before"), where, q)
            bag.add(lab, "label", x.get("after"), where, q)
    elif k == "standard_quote":
        bag.add(lab, "label", d.get("label"), where, q)
        for x in d.get("lines") or []:
            bag.add(lab, "label", x.get("name"), where, q)
    elif k == "vendor_brief":
        bag.add(lab, "label", d.get("title"), where, q)
        for x in d.get("facts") or []:
            bag.add(lab, "label", x, where, q)
        for x in d.get("fit") or []:
            bag.add(lab, "label", x.get("label"), where, q)
            bag.add(lab, "label", x.get("text"), where, q)
        bag.add(lab, "label", (d.get("estimate") or {}).get("basis"), where, q)
        bag.add(FREE + "업체 브리핑 한 줄", "line", d.get("sentence"), where, q)
    elif k == "quote_checklist":
        for x in d.get("items") or []:
            bag.add(lab, "label", x.get("label"), where, q)
            bag.add(FREE + "카드 안내 줄", "note", x.get("hint"), where, q)
        for x in d.get("fields") or []:
            bag.add(lab, "label", x.get("label"), where, q)
        for x in d.get("easy_miss") or []:
            bag.add(lab, "label", x, where, q)
    elif k == "floorplan_links":
        bag.add(FREE + "카드 안내 줄", "note", d.get("note"), where, q)


def summary(bag: Bag, a: dict, q: str = "") -> None:
    s = a.get("summary") or {}
    lab = FREE + "승인 카드 제목 · 칸"
    for key in ("title", "version", "approve_label"):
        bag.add(lab, "label", s.get(key), f"action:{a['kind']}", q)
    bag.add(FREE + "승인 카드 안내 줄", "note", s.get("note"), f"action:{a['kind']}", q)
    for r in s.get("rows") or []:
        for key in ("label", "value", "sub"):
            bag.add(lab, "label", r.get(key), f"action:{a['kind']}", q)
    bag.add(lab, "label", (s.get("diff") or {}).get("label"), f"action:{a['kind']}", q)
    bag.add(lab, "label", (s.get("file") or {}).get("label"), f"action:{a['kind']}", q)


def run_all(api, bag: Bag, send, surface: str, extra: list[str] = ()) -> None:
    for src, q in [*questions(surface), *[("extra", x) for x in extra]]:
        r = send(q)
        if r.status_code != 200:
            bag.add(FREE + "409 · 오류 문장", "note", r.json()["error"]["message"], f"HTTP {r.status_code}", q)  # fmt: skip
            continue
        collect(bag, events(r.text), f"{src} {q[:40]}")


def press(api, bag: Bag, send, choice: str, card_id: str | None = None, prefix: str = "/assistant"):
    """카드 단추를 누르고(choice) 만든 승인 카드를 승인한다. 실행 결과 글 · 두 번째 승인 409 글도 모은다."""
    r = send("이걸로 할게요", context={"card_id": card_id, "choice": choice})
    assert r.status_code == 200, r.text
    opened = collect(bag, events(r.text), f"press {choice}")
    for a in opened:
        got = api.post(f"{prefix}/actions/{a['action_id']}/approve", json={})
        body, where = got.json(), f"approve:{a['kind']}"
        if got.status_code != 200:
            bag.add(FREE + "409 · 오류 문장", "note", body["error"]["message"], where)
            continue
        result = body.get("result") or {}
        bag.add(FREE + "실행 결과", "note", result.get("text"), where)
        bag.add(FREE + "실행 결과", "label", result.get("label"), where)
    return opened


def refs_of(ev_text: str, kind: str, field: str) -> list[str]:
    for name, d, _ in events(ev_text):
        if name == "card" and d["kind"] == kind:
            return [x["ref"] for x in d["data"].get(field) or []]
    return []


def test_free_customer_questions(api):
    """업체 고르기 전(도배 업체 2곳): 고객 질문 묶음 전부 + 업체 추천 단추 → 실측 요청 승인 + 철거 범위 단추."""
    vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    bag = Bag("free_customer")

    def send(text, **body):
        return ask(api, pid, text, **body)

    run_all(api, bag, send, "customer")
    r = send("업체 추천해 주세요")
    picks = refs_of(r.text, "vendor_picks", "picks")
    assert picks
    press(api, bag, send, "demolition:full", "home")
    press(api, bag, send, "visit_request:" + ",".join(picks), "picks-dobae")
    r = send("오늘 뭐 하면 돼요?")  # 요청 뒤: 작업 카드 · 오늘 할 일
    collect(bag, events(r.text), "after request")
    bag.assert_style()


STAGE_QUESTIONS = (
    "실측은 언제 할 수 있어요?",
    "오늘 뭐 하면 돼요?",
    "견적서 비교해 줘",
    "공사 날짜 보여 줘",
    "표준견적서 얼마예요?",
    "다음엔 뭐 해요?",
)


def test_free_customer_offered(api):
    """업체가 기간을 답함: 반나절 후보 · 고르기 승인 카드 · 실행 결과."""
    f = offered(api)
    bag = Bag("free_offered")

    def send(text, **body):
        return ask(api, f["pid"], text, **body)

    for q in STAGE_QUESTIONS:
        collect(bag, events(send(q).text), q)
    slots = refs_of(send("실측은 언제 할 수 있어요?").text, "visit_slots", "candidates")
    assert slots
    press(api, bag, send, f"visit_slot:{slots[0]}", f"slots-{f['visit']}")
    collect(bag, events(send("오늘 뭐 하면 돼요?").text), "after slot")
    bag.assert_style()


def test_free_customer_quotes(api):
    """견적서 2곳 받음: 견적 비교 · 확정 승인 카드 · 거절 뒤 승인 409 · 실행 결과."""
    customer_token, pid, _va, _vb, _ = deal_setup(api)
    use(api, customer_token)
    bag = Bag("free_quotes")

    def send(text, **body):
        return ask(api, pid, text, **body)

    for q in STAGE_QUESTIONS:
        collect(bag, events(send(q).text), q)
    cols = refs_of(send("견적서 비교해 줘").text, "quote_compare", "cols")
    assert cols
    r = send(
        "이걸로 할게요", context={"card_id": "compare-dobae", "choice": f"vendor_confirm:{cols[0]}"}
    )
    (first,) = [a for a in collect(bag, events(r.text), "confirm") if a["kind"] == "vendor_confirm"]
    api.post(f"/assistant/actions/{first['action_id']}/reject", json={})
    got = api.post(f"/assistant/actions/{first['action_id']}/approve", json={})
    assert got.status_code == 409
    bag.add(FREE + "409 · 오류 문장", "note", got.json()["error"]["message"], "approve rejected")
    press(api, bag, send, f"vendor_confirm:{cols[0]}", "compare-dobae")
    collect(bag, events(send("다음엔 뭐 해요?").text), "after confirm")
    bag.assert_style()


def test_free_customer_dates(api):
    """업체가 공사 날짜를 올림: 공사 날짜 카드 · 수락 승인 카드 · 실행 결과 · 확정 공정표."""
    customer_token, pid, did, _ = dates_ready(api)
    start, end = days(10)
    assert propose(api, did, start, end).status_code == 200
    use(api, customer_token)
    bag = Bag("free_dates")

    def send(text, **body):
        return ask(api, pid, text, **body)

    for q in STAGE_QUESTIONS:
        collect(bag, events(send(q).text), q)
    r = send("공사 날짜 보여 줘")
    sched = next(d for n, d, _ in events(r.text) if n == "card" and d["kind"] == "schedule")
    ref = sched["data"]["proposal_ref"]
    press(api, bag, send, f"{sched['data']['proposal_kind']}:{ref}", sched["card_id"])
    collect(bag, events(send("공정표 보여 줘").text), "after accept")
    assert query("select status from deals")[0]["status"] == "scheduled"
    bag.assert_style()


def test_free_vendor(api):
    """업체: 새 요청(브리핑 · 기간 답하기 · 못 받아요) · 업체 질문 묶음 · 브리핑 · 체크리스트 · 오늘(REST)."""
    f = requested(api)
    login(api, f["email"])
    bag = Bag("free_vendor")
    visit = f["visit"]

    def send(text, **body):
        return api.post(
            "/vendor/assistant/turns",
            json={"visit_id": visit, "client_key": uuid.uuid4().hex, "text": text, **body},
        )

    b = api.get(f"/vendor/assistant/briefs/{visit}")
    assert b.status_code == 200, b.text
    card(bag, {"kind": "vendor_brief", "card_id": "rest", "data": b.json()}, "REST brief")
    for path in (f"/vendor/assistant/checklists/{visit}", "/vendor/assistant/today"):
        got = api.get(path)
        assert got.status_code == 200, got.text
        kind = "quote_checklist" if "checklists" in path else "today"
        card(bag, {"kind": kind, "card_id": "rest", "data": {**got.json(), "todo": got.json().get("rows")}}, path)  # fmt: skip
    run_all(api, bag, send, "vendor", extra=["오늘 할 일 알려 줘", "견적서 체크리스트 보여 줘"])
    wins = [w["ref"] for w in b.json()["windows"]]
    assert wins
    press(api, bag, send, f"window_answer:{wins[0]}", f"brief-{visit}", "/vendor/assistant")
    press(api, bag, send, "decline:out_of_area", f"brief-{visit}", "/vendor/assistant")
    bag.assert_style()

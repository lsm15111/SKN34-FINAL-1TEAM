"""v4 비서 지시문 새 판(customer_v4 · vendor_v4 · nudge_write_v3)의 좋은 예시가 고정 선(docs/v4/08-rules.md)을 어기지
않는지 본다. LLM 없음(유료 호출 0회). 판 고르기(prompts.VERSION)와 상관없이 파일을 바로 읽는다.

- 대화 예시: 비서 글마다 글 모양(style_lint R3 · R4 · R6 · R11 · R13 · R14), 숫자(예시의 사람 말 · 사실 · 도구 값에서
  나온 값, 08 숫자 절의 어림 · 차액 · 합계), 한 일처럼 말함 · 쓰면 안 되는 표현 · 표준 대비 %, 카드 말과 만든 카드
  (policy.card_claim · claim_ok), 길이(runtime 길이 상한 안, 제목에 '길어도 돼요'가 있는 소개 · 비교 예시만 넘어도 돼요).
- 먼저 말 걸기 예시: 코드 검사(tools.vendor.sentence_ok)와 글 모양(line).
- 코드가 아직 따라오지 않은 예시는 PENDING에 까닭과 함께 둔다. 코드가 고쳐지면 시험이 알려 주니 그때 지운다.
"""

import importlib.util
import re
import sys
from pathlib import Path

from app.agent.v3 import check
from app.assistant import policy, runtime
from app.assistant.tools.vendor import sentence_ok
from app.v2 import guard

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "backend" / "app" / "assistant" / "prompts"


def _lint():
    """evaluation/v4/style_lint.py(표준 라이브러리만)를 이름이 겹치지 않게 불러온다(test_v4_copy_style과 같은 이름)."""
    name = "v4_style_lint"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "evaluation/v4/style_lint.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sl = _lint()

STYLE = frozenset({"R3", "R4", "R6", "R11", "R13", "R14"})
HEAD = re.compile(r"^### (\d+)\. (.+)$")
LINE = re.compile(r"^- (고객|업체|사실|도구|비서)(?:\(([^)]+)\))?: (.*)$")
TOOL = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
# 화면 카드를 보이는 읽기 도구 → 카드 kind(그 카드 단추가 만드는 행동은 policy.BUTTONS)
READ_CARD = {
    "recommend_vendors": "vendor_picks",
    "vendor_free_slots": "visit_slots",
    "compare_quotes": "quote_compare",
    "get_schedule": "schedule",
    "request_brief": "vendor_brief",
    "compare_grades": "grade_compare",
}
# 요청함이면 기간 답하기 승인 카드도 만드는 읽기 도구(계약서 3장)
MADE_BY_READ = {"request_brief": "window_answer"}
# 코드가 아직 따라오지 않은 예시: (판, 예시) → 까닭. 9(이미 보냈을 때)의 취소 카드 말은 KIND_WORDS에 visit_cancel이
# 들어가 맞게 읽혀 지웠어요(갈래 T)
PENDING: dict[tuple[str, str], str] = {}


def _part(lines: list[tuple[str, str, str]], kind: str, tag: str) -> str:
    """같은 갈래(괄호 tag)의 줄, 없으면 갈래 없는 줄."""
    got = [v for k, t, v in lines if k == kind and t == tag]
    return " ".join(got or [v for k, t, v in lines if k == kind and not t])


def answers(name: str) -> list[dict]:
    """좋은 예시의 비서 글마다 같은 갈래(괄호)의 사실 · 도구 줄, 예시의 사람 말."""
    body = (PROMPTS / f"{name}.md").read_text(encoding="utf-8").split("## 좋은 예시", 1)[1]
    blocks: list[dict] = []
    for ln in body.splitlines():
        if h := HEAD.match(ln):
            blocks.append({"no": h.group(1), "title": h.group(2), "lines": []})
        elif (m := LINE.match(ln)) and blocks:
            blocks[-1]["lines"].append((m.group(1), m.group(2) or "", m.group(3)))
    out = []
    for b in blocks:
        said = " ".join(v for k, _, v in b["lines"] if k in ("고객", "업체"))
        for k, tag, text in b["lines"]:
            if k != "비서":
                continue
            facts, tool = _part(b["lines"], "사실", tag), _part(b["lines"], "도구", tag)
            names = TOOL.findall(tool)
            made = {n.removeprefix("propose_") for n in names if n.startswith("propose_")}
            made |= {MADE_BY_READ[n] for n in names if n in MADE_BY_READ and "승인 카드" in tool}
            buttons = {x for n in names if n in READ_CARD for x in policy.BUTTONS[READ_CARD[n]]}
            waiting = (
                facts.split("승인 기다리는 카드:", 1)[1] if "승인 기다리는 카드:" in facts else ""
            )
            opened = {kind for kind, rx in policy.KIND_WORDS if waiting and rx.search(waiting)}
            out.append(
                {
                    "key": (name, b["no"] + (f"({tag})" if tag else "")),
                    "long": "길어도" in b["title"],
                    "text": text,
                    "source": f"{said}\n{facts}\n{tool}",
                    "made": made,
                    "opened": opened,
                    "buttons": buttons,
                }
            )
    return out


def number_ok(v: float, unit: str | None, rest: str, allowed: set[float]) -> bool:
    """08 숫자 절: 근거 값 그대로 · 만 원 어림(지금 검사) · 작은 센 수, 근거 금액과 3% 안의 더 둥근 수, 두 근거 금액의
    차액 · 합계(만 원 어림 포함)만 돼요."""
    if round(v, 4) in allowed or guard._small_count(v, unit, rest):
        return True
    money = [a for a in allowed if a >= 100_000]
    if any(abs(v - a) <= a * 0.03 and v % 10_000 == 0 for a in money):
        return True
    return any(
        abs(v - abs(a - b)) < 10_000 or abs(v - (a + b)) < 10_000 for a in money for b in money
    )


def problems(a: dict) -> list[str]:
    """비서 글 하나가 고정 선 · 글 모양 · 길이를 어긴 곳."""
    out: list[str] = []
    text = a["text"]
    for h in sl.check(text, "answer"):
        if h.rule in STYLE and h.why != "영어 약어":
            out.append(f"{h.rule} {h.why}: {h.piece}")
    allowed = guard.numbers(a["source"])
    sents = sl.sentences(text)
    for s in sents:
        for m in guard.NUM.finditer(s):
            v = guard._val(m.group(1), m.group(2))
            if v is not None and not number_ok(v, m.group(2), s[m.end() :], allowed):
                out.append(f"근거 없는 숫자: {m.group(0).strip()}")
        for rx, why in (
            (guard.HANGUL_MONEY, "한글 금액"),
            (guard.BANNED, "쓰면 안 되는 표현"),
            (check.AI_ACTS, "AI가 한 일처럼 말함"),
            (check.URL, "주소"),
            (policy.VS_STANDARD, "표준 대비 %"),
        ):
            if rx.search(s):
                out.append(f"{why}: {s[:30]}")
        if runtime.claims_done(s):
            out.append(f"승인 없이 한 일처럼 말함: {s[:30]}")
    n = len(sents)
    if not a["long"] and not (
        n <= policy.TALK_LEAD or (n == policy.TALK_LEAD + 1 and policy.next_step(sents[-1]))
    ):
        out.append(f"길이 상한을 넘음({n}문장)")
    return out


def claim_misses(a: dict) -> list[str]:
    """카드를 만들었다 · 만들어 드린다 · 눌러 달라는 말이 그 예시에서 만든 · 열린 · 보인 카드와 맞지 않는 문장."""
    miss = []
    for s in sl.sentences(a["text"]):
        c = policy.card_claim(s)
        if c is not None and not policy.claim_ok(c, a["made"], a["opened"], a["buttons"]):
            miss.append(s[:30])
    return miss


def test_chat_examples_keep_fixed_lines():
    got = answers("customer_v4") + answers("vendor_v4")
    customer = {a["key"][1].split("(")[0] for a in got if a["key"][0] == "customer_v4"}
    vendor = {a["key"][1].split("(")[0] for a in got if a["key"][0] == "vendor_v4"}
    # 좋은 예시 6~10개(지시서), 읽기가 비면 알아챈다
    assert 6 <= len(customer) <= 10 and len(vendor) >= 4
    bad = {f"{a['key'][0]} {a['key'][1]}": p for a in got if (p := problems(a))}
    assert not bad, bad
    missed = {a["key"]: m for a in got if (m := claim_misses(a))}
    assert set(missed) == set(PENDING), (
        "카드 말이 맞지 않는 예시가 PENDING과 달라요(고쳐졌으면 PENDING에서 지워요)",
        missed,
    )


def test_nudge_examples_pass_code_check():
    body = (PROMPTS / "nudge_write_v3.md").read_text(encoding="utf-8").split("## 좋은 예시", 1)[1]
    rows = [
        ln.removeprefix("- 사실: ").split(" → ", 1)
        for ln in body.splitlines()
        if ln.startswith("- 사실: ")
    ]
    assert len(rows) >= 4
    for facts, text in rows:
        # 코드 검사: 60자 · 한 줄 · '요' 끝 · 숫자는 사실에만 · 한 일처럼 말하지 않음
        assert sentence_ok(text, facts), text
        hits = [h for h in sl.check(text, "line") if h.why != "영어 약어"]
        assert not [h for h in hits if h.rule in STYLE | {"R2"}], (text, hits)

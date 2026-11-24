"""출력 검사 (두 모드 공통, agents.md 12절 · security LM-04 · 05 · 06 · 07). v2 guard를 다시 쓴다.

- 숫자: 묶음마다 허용 글(카드 · 조각 원문 · 계산 결과 · 정해 둔 글 · 고객 글)에 없는 숫자가 든 문장은 뺀다.
  기간(일 · 주 · 개월)은 계산 엔진 결과(calc_text)에 있는 숫자만 (guard._why 그대로).
- 한글 금액 · 면적, 쓰면 안 되는 표현(guard.BANNED) + v3: AI가 보내기 · 확정 · 예약을 한 것처럼 말함.
- 인용: 이번 턴에 보인 조각 · 카드 번호만 남긴다(문장은 두고 번호만 뗀다).
- 가림: shared/pii.mask(여기 mask로 다시 내보냄, v2 guard와 같은 규칙 하나). 답 · 로그 · LLM 입력이 같이 쓴다.
- 지시문 누출(LLM 모드): 지시문과 연속 30자가 같은 문장은 버린다.
- 링크: 답 글에 주소를 쓰지 않는다(화면은 글로만 그림).
- 알아 두기(믿집이 계산하지 않는 공종): 금액 · 기간은 계산 엔진 값 · 고객 글에 있어야 하고, LLM이 쓴 글(작성기 ·
  일반 설명)은 모든 숫자가 그래야 해요. 자료에 있는 다른 공정 금액이라도 계산 값이 아니라 빼요(평가 dev 욕실 2쌍).
"""

import re

from app.agent.v3.schemas import AgentAnswer, CalcBox, Section, Sentence
from app.agent.v3.trades import trades_in
from app.shared.pii import mask
from app.v2 import guard

URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# AI가 한 일처럼 말함(보내기 · 확정 · 예약 …). 취소 · 수락은 v4 승인 행동(visit_cancel · dates_accept)이라 한 일 꼴
# ('취소해 드렸' · '수락해 놨')만 더해요('제가 취소 방법을 …'은 아니에요, R1a B1)
AI_ACTS = re.compile(
    r"(?:제가|저희가|AI가)[^.?!\n]{0,12}?(?:예약|보내|보냈|확정|신청|접수|결제|저장|연락|취소|수락)"
    r"(?:했|해\s*드렸|해\s*드릴게|해\s*놨|해\s*뒀|드렸|드릴게)"
    r"|(?:제가|저희가|AI가|믿집\s*AI가)\s*(?:대신\s*)?(?:예약|보내|보냈|확정|신청|접수|결제|저장|연락)"
    r"|(?:예약|확정|신청|접수|결제|취소|수락)(?:해|했)\s*(?:드렸|드릴게|놨|두었)"
)
LEAK_N = 30
CITE = re.compile(r"^(?:K\d{1,5}|doc:[a-z0-9_.\-]+|rule:[a-z0-9_.\-]+|card:[a-z0-9_.\-]+@\d+)$")
# 믿집이 견적 · 공정표를 만드는 공종(answer.OWN_TRADES와 같음). 그 밖은 '알아 두기'예요
OWN = frozenset({"dobae", "mokgong", "common"})
WRITTEN = frozenset({"llm", "general"})  # LLM이 쓴 묶음(작성기 · 일반 설명)
MONEY_UNITS = frozenset({"만원", "천원", "억원", "억", "만", "원"})


def _leak(text: str, prompt: str | None) -> bool:
    if not prompt or len(text) < LEAK_N:
        return False
    flat = re.sub(r"\s+", " ", prompt)
    t = re.sub(r"\s+", " ", text)
    return any(t[i : i + LEAK_N] in flat for i in range(0, len(t) - LEAK_N + 1, 5))


def _why(
    text: str, allowed: set[float], periods: set[float] | None, prompt: str | None
) -> str | None:
    why = guard._why(text, allowed, periods)
    if why:
        return why
    if AI_ACTS.search(text):
        return "AI가 한 일처럼 말함"
    if URL.search(text):
        return "주소"
    if _leak(text, prompt):
        return "지시문 누출"
    return None


def sentence_ok(
    sent: Sentence,
    allowed: set[float],
    periods: set[float] | None,
    shown: set[str] | None,
    prompt: str | None,
) -> tuple[Sentence | None, str | None]:
    text = mask(sent.text).strip()
    if not text:
        return None, "빈 문장"
    why = _why(text, allowed, periods, prompt)
    if why:
        return None, why
    cites = [c for c in sent.cites if CITE.match(c) and (shown is None or c in shown)]
    return Sentence(text=text, cites=list(dict.fromkeys(cites))), None


def section(
    sec: Section,
    allowed_text: str,
    *,
    calc_text: str | None = None,
    shown: set[str] | None = None,
    prompt: str | None = None,
) -> tuple[Section | None, list[str]]:
    """묶음 하나를 검사한다. 남은 문장이 없으면 None(그 몫 실패)."""
    allowed = guard.numbers(allowed_text)
    periods = None if calc_text is None else guard.numbers(calc_text)
    dropped: list[str] = []
    kept: list[Sentence] = []
    for x in sec.sentences:
        ok, why = sentence_ok(x, allowed, periods, shown, prompt)
        if ok:
            kept.append(ok)
        elif why:
            dropped.append(why)
    extra = {}
    for name in ("caution", "tip"):
        v = getattr(sec, name)
        if v is not None:
            ok, why = sentence_ok(v, allowed, periods, shown, prompt)
            extra[name] = ok
            if why:
                dropped.append(why)
    table = []
    for row in sec.table:  # 표 칸도 문장과 같은 숫자 · 금지 표현 검사를 지나야 해요
        whys = [_why(mask(c), allowed, periods, prompt) for c in row]
        if any(whys):
            dropped.extend(w for w in whys if w)
        else:
            table.append([mask(c) for c in row])
    if not kept and not table:
        return None, dropped
    return sec.model_copy(update={"sentences": kept, "table": table, **extra}), dropped


def turn_out(trades: list[str] | tuple[str, ...]) -> bool:
    """턴 공종(관문이 고른 것)이 있고 모두 믿집이 계산하지 않는 공종인지."""
    tr = [t for t in trades if t != "common"]
    return bool(tr) and all(t not in OWN for t in tr)


def know_of(sec: Section, text: str, out: bool) -> bool:
    """알아 두기(믿집이 계산하지 않는 공종) 글인지. 카드 · 발췌 · 정해 둔 글은 묶음 공종으로 봐요.
    LLM이 쓴 묶음은 글의 공종 낱말로(범위 밖 공종이 하나라도 나오면), 낱말이 없으면 묶음 공종 · 턴 공종(out)으로 봐요."""
    sec_out = sec.trade is not None and sec.trade not in OWN
    if sec.source not in WRITTEN:
        return sec_out
    tr = [t for t in trades_in(text) if t != "common"]
    if tr:
        return any(t not in OWN for t in tr)
    return sec_out or (sec.trade is None and out)


def know_why(text: str, allowed: set[float], strict: bool) -> str | None:
    """알아 두기 글의 숫자: 금액 · 기간은 계산 엔진 값 · 고객 글(allowed)에 있어야 해요.
    strict(LLM이 쓴 글)면 모든 숫자가 그래야 해요. 카드 · 발췌의 치수 · 비율은 strict가 아니면 둬요."""
    if strict:
        bad = guard._bad_number(text, allowed, allowed)
        return f"알아 두기 숫자({bad})" if bad else None
    for m in guard.NUM.finditer(text):
        money = (m.group(2) or "").replace(" ", "") in MONEY_UNITS
        if not (money or guard._is_period(text, m)):
            continue
        v = guard._val(m.group(1), m.group(2))
        if v is not None and round(v, 4) not in allowed:
            return "알아 두기 금액" if money else "알아 두기 기간"
    return None


def know(sec: Section, allowed: set[float], out: bool) -> tuple[Section | None, list[str]]:
    """묶음 하나의 알아 두기 숫자 검사(문장 · 주의 · 팁 · 표 줄, 문장 단위). 남은 글이 없으면 None.
    allowed: 계산 엔진 값 · 고객 글의 숫자. out: 턴 공종이 모두 범위 밖인지(turn_out)."""
    strict = sec.source in WRITTEN

    def bad(text: str) -> str | None:
        return know_why(text, allowed, strict) if know_of(sec, text, out) else None

    dropped: list[str] = []
    kept: list[Sentence] = []
    for x in sec.sentences:
        why = bad(x.text)
        if why:
            dropped.append(why)
        else:
            kept.append(x)
    extra: dict = {}
    for name in ("caution", "tip"):
        v = getattr(sec, name)
        why = bad(v.text) if v is not None else None
        if why:
            dropped.append(why)
            extra[name] = None
    table = []
    for row in sec.table:
        why = bad(" ".join(row))
        if why:
            dropped.append(why)
        else:
            table.append(row)
    if not dropped:
        return sec, []
    if not kept and not table:
        return None, dropped
    return sec.model_copy(update={"sentences": kept, "table": table, **extra}), dropped


def calc_numbers(boxes: list[CalcBox], *texts: str) -> set[float]:
    """알아 두기 검사의 허용 숫자: 계산 상자 값 · 계산 묶음 글 · 고객 글."""
    vals = [
        f"{b.qty if b.qty is not None else ''} {b.unit_price or ''} {b.amount or ''} {b.note}"
        for b in boxes
    ]
    return guard.numbers("\n".join([*vals, *texts]))


def final(
    ans: AgentAnswer,
    prompt: str | None = None,
    *,
    question: str = "",
    calc: str = "",
    trades: list[str] | tuple[str, ...] = (),
) -> AgentAnswer:
    """합친 답 전체를 한 번 더: 가림 · AI 행동 · 누출 · 모양 · 알아 두기 숫자. 그 밖 숫자는 묶음 검사에서 이미 봤다.
    question · calc · trades: 고객 글 · 계산 묶음 글 · 턴 공종(알아 두기 숫자 검사에 써요)."""
    dropped = list(ans.trace.dropped)
    allowed = calc_numbers(ans.calc, calc, question)
    out = turn_out(trades)
    sections: list[Section] = []
    for whole in ans.sections:
        sec, why = know(whole, allowed, out)
        dropped.extend(why)
        if sec is None:
            continue
        kept = []
        for x in sec.sentences:
            t = mask(x.text)
            why = (
                "AI가 한 일처럼 말함"
                if AI_ACTS.search(t)
                else ("지시문 누출" if _leak(t, prompt) else None)
            )
            if why:
                dropped.append(why)
                continue
            kept.append(x.model_copy(update={"text": t}))
        table = [
            [mask(c) for c in r] for r in sec.table
        ]  # 비교 표 칸도 가림(숫자는 묶음 검사에서 봤어요)
        if kept or table:
            sections.append(sec.model_copy(update={"sentences": kept, "table": table}))
    unknown = [mask(u) for u in ans.unknown]
    failed = ans.failed or not (sections or ans.cards or ans.calc or unknown)
    trace = ans.trace.model_copy(update={"dropped": dropped})
    return ans.model_copy(
        update={"sections": sections, "unknown": unknown, "failed": failed, "trace": trace}
    )

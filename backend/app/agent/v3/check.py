"""출력 검사 (두 모드 공통, agents.md 12절 · security LM-04 · 05 · 06 · 07). v2 guard를 다시 쓴다.

- 숫자: 묶음마다 허용 글(카드 · 조각 원문 · 계산 결과 · 정해 둔 글 · 고객 글)에 없는 숫자가 든 문장은 뺀다.
  기간(일 · 주 · 개월)은 계산 엔진 결과(calc_text)에 있는 숫자만 (guard._why 그대로).
- 한글 금액 · 면적, 쓰면 안 되는 표현(guard.BANNED) + v3: AI가 보내기 · 확정 · 예약을 한 것처럼 말함.
- 인용: 이번 턴에 보인 조각 · 카드 번호만 남긴다(문장은 두고 번호만 뗀다).
- 가림: 전화 · 동호수 · 이메일 · 주민등록번호 꼴 · 계좌 꼴. 답 · 로그 · LLM 입력이 같이 쓴다.
- 지시문 누출(LLM 모드): 지시문과 연속 30자가 같은 문장은 버린다.
- 링크: 답 글에 주소를 쓰지 않는다(화면은 글로만 그림).
"""

import re

from app.agent import intent as intent_model
from app.agent.v3.schemas import AgentAnswer, Section, Sentence
from app.v2 import guard

# 동 · 호: '105동 1203호' · '1503호'. 법 · 고시 번호('대통령령 제36437호' · '제2026-360호')와 '3호선'은 빼요
DONGHO = re.compile(r"(?<![제\d-])(?:\d{1,4}\s?동\s?)?\d{3,4}\s?호(?!선)")
# 앞 글자가 같은 묶음이면 시작하지 않고 길이에 상한을 둬서 긴 입력에도 한 번만 훑어요(CodeQL ReDoS)
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5}")
RRN = re.compile(r"\d{6}\s?-\s?[1-4]\d{6}")
# 계좌: 은행 이름 바로 뒤의 숫자 묶음(숫자 10~14자리). 날짜(2026-11-18)를 계좌로 가리지 않게 은행 이름을 요구한다
ACCOUNT = re.compile(
    r"((?:국민|신한|우리|하나|농협|기업|카카오|토스|케이|새마을|우체국|수협|씨티|SC|산업|부산|대구|경남|광주|전북|제주)"
    r"(?:은행|뱅크)?\s*(?:[:：]\s*)?)(\d[\d\s-]{8,20}\d)"
)
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
AI_ACTS = re.compile(
    r"(?:제가|저희가|AI가)[^.?!\n]{0,12}?(?:예약|보내|보냈|확정|신청|접수|결제|저장|연락)"
    r"(?:했|해\s*드렸|해\s*드릴게|해\s*놨|해\s*뒀|드렸|드릴게)"
    r"|(?:제가|저희가|AI가|믿집\s*AI가)\s*(?:대신\s*)?(?:예약|보내|보냈|확정|신청|접수|결제|저장|연락)"
    r"|(?:예약|확정|신청|접수|결제)(?:해|했)\s*(?:드렸|드릴게|놨|두었)"
)
LEAK_N = 30
CITE = re.compile(r"^(?:K\d{1,5}|doc:[a-z0-9_.\-]+|rule:[a-z0-9_.\-]+|card:[a-z0-9_.\-]+@\d+)$")


def mask(text: str) -> str:
    """가림 모듈 하나(security 8.5). 화면 채팅 본문은 가리지 않는다(이 함수는 AI 입출력용)."""
    t = guard.mask(text or "")
    t = intent_model.PHONE.sub("(번호 가림)", t)
    t = DONGHO.sub("(동호수 가림)", t)
    t = EMAIL.sub("(이메일 가림)", t)
    t = RRN.sub("(주민번호 가림)", t)

    def acc(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(2))
        return m.group(1) + "(계좌 가림)" if 10 <= len(digits) <= 14 else m.group(0)

    return ACCOUNT.sub(acc, t)


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
    if not kept:
        return None, dropped
    return sec.model_copy(update={"sentences": kept, **extra}), dropped


def final(ans: AgentAnswer, prompt: str | None = None) -> AgentAnswer:
    """합친 답 전체를 한 번 더: 가림 · AI 행동 · 누출 · 모양. 숫자는 묶음 검사에서 이미 봤다."""
    dropped = list(ans.trace.dropped)
    sections: list[Section] = []
    for sec in ans.sections:
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
        if kept:
            sections.append(sec.model_copy(update={"sentences": kept}))
    unknown = [mask(u) for u in ans.unknown]
    failed = ans.failed or not (sections or ans.cards or ans.calc or unknown)
    trace = ans.trace.model_copy(update={"dropped": dropped})
    return ans.model_copy(
        update={"sections": sections, "unknown": unknown, "failed": failed, "trace": trace}
    )

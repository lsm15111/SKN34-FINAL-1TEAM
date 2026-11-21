"""출력 검사 (두 모드 공통, agents.md 12절 · security LM-04 · 05 · 06 · 07). v2 guard를 다시 쓴다.

- 숫자: 묶음마다 허용 글(카드 · 조각 원문 · 계산 결과 · 정해 둔 글 · 고객 글)에 없는 숫자가 든 문장은 뺀다.
  기간(일 · 주 · 개월)은 계산 엔진 결과(calc_text)에 있는 숫자만 (guard._why 그대로).
- 한글 금액 · 면적, 쓰면 안 되는 표현(guard.BANNED) + v3: AI가 보내기 · 확정 · 예약을 한 것처럼 말함.
- 인용: 이번 턴에 보인 조각 · 카드 번호만 남긴다(문장은 두고 번호만 뗀다).
- 가림: 전화(국제 · 빗금 · 띄움 · 한글 숫자) · 동호수(층 호 · 주소 가까이의 101-1203) · 도로명 · 지번 번호 ·
  이메일(가린 꼴 포함) · 메신저 아이디 · 주민등록번호 꼴 · 계좌 꼴. 답 · 로그 · LLM 입력이 같이 쓴다.
- 지시문 누출(LLM 모드): 지시문과 연속 30자가 같은 문장은 버린다.
- 링크: 답 글에 주소를 쓰지 않는다(화면은 글로만 그림).
- 알아 두기(믿집이 계산하지 않는 공종): 금액 · 기간은 계산 엔진 값 · 고객 글에 있어야 하고, LLM이 쓴 글(작성기 ·
  일반 설명)은 모든 숫자가 그래야 해요. 자료에 있는 다른 공정 금액이라도 계산 값이 아니라 빼요(평가 dev 욕실 2쌍).
"""

import re

from app.agent import intent as intent_model
from app.agent.v3.schemas import AgentAnswer, CalcBox, Section, Sentence
from app.agent.v3.trades import trades_in
from app.shared.regions import EMD, SGG
from app.v2 import guard

# 동 · 호: '105동 1203호' · '1503호'. 법 · 고시 번호('대통령령 제36437호' · '제2026-360호')와 '3호선'은 빼요
DONGHO = re.compile(r"(?<![제\d-])(?:\d{1,4}\s?동\s?)?\d{3,4}\s?호(?!선)")
# '3층 2호'처럼 층 뒤 1~2자리 호(보안 QA M1)
FLOOR_HO = re.compile(r"(?<![\d-])\d{1,3}\s?층\s?\d{1,4}\s?호(?!선)")
# 숫자 뒤 단위 · 세는 말 · 범위(~): 이 말이 붙은 숫자는 주소 번호로 보지 않는다(금액 · 면적 · 날짜 · 개수)
_UNIT_AFTER = (
    r"(?!\s?(?:만|천|억|원|평|㎡|m|일|개|시|분|초|층|년|월|주|달|롤|%|번|장|명|곳|군데|가지|차|회|박|배"
    r"|살|세|등|위|점|퍼센트|문장|kg|cm|mm|[~∼〜]))"
)
# 주소 낱말 가까이(앞 ADDR_NEAR · 뒤 ADDR_AFTER 글자)의 '101-1203'(동-호 줄임). 날짜 · 금액 · 범위('100-200만 원')
# · 법 · 고시 번호('제2018-775호') · 대표번호('1661-2642')는 뺀다
DASH_UNIT = re.compile(
    r"(?<![\d.,\-/제])(?!1[5-9]\d{2}\s?-\s?\d{4}(?!\d))\d{2,4}\s?-\s?\d{3,4}(?:\s?호(?!선))?"
    r"(?![\d\-/]|[.,]\d)" + _UNIT_AFTER
)
# 도로명 주소의 건물 번호('동일로 1234' · '월계로45길 11'). 주소 낱말이 가까이 있을 때만이고, '…으로'(기준으로 3곳)
# · 단위가 붙은 숫자(실크로 34평) · 소수 · 천 단위 쉼표(3,300,000) · 흔한 낱말(도로 · 통로 …, ROAD_WORDS)은 둔다
ROAD_NO = re.compile(
    r"(?<![가-힣\d])([가-힣\d]{1,10}(?:대로|(?<!으)로|길))(?:\s?\d{1,4}\s?번?길)?\s?\d{1,4}(?:-\d{1,4})?"
    r"(?!\d|[.,]\d|\s?(?:번?길))" + _UNIT_AFTER
)
ROAD_WORDS = frozenset(
    {
        "도로", "통로", "경로", "차로", "진로", "선로", "철로", "수로", "활로", "항로", "대로", "산책로",
        "진입로", "출입로", "보행로", "고속도로", "골목길", "오솔길", "산길", "지름길", "갈림길", "비탈길",
        "오르막길", "내리막길", "둘레길", "큰길", "뒷길", "옆길",
    }
)  # fmt: skip
LOT_NO = re.compile(r"(?<![\d-])\d{1,5}(?:-\d{1,5})?\s?번지")  # 지번 '123-45번지'
# 주소 낱말: 주소 · 아파트 같은 말과 실제 시 · 군 · 구 · 법정동 이름(shared.regions). '고시' · '가구'처럼 시 · 구로
# 끝나는 낱말은 주소 낱말로 보지 않는다
_PLACES = sorted(
    {n for v in SGG.values() for n in v} | {n for v in EMD.values() for _, n in v},
    key=len,
    reverse=True,
)
ADDR_CUE = re.compile(
    r"주소|도로명|번지|아파트|단지|주공|빌라|맨션|오피스텔|동호수|(?<![가-힣])(?:"
    + "|".join(map(re.escape, _PLACES))
    + ")"
)
ADDR_NEAR, ADDR_AFTER = 40, 20
# 앞 글자가 같은 묶음이면 시작하지 않고 길이에 상한을 둬서 긴 입력에도 한 번만 훑어요(CodeQL ReDoS)
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5}")
# 가린 꼴 이메일: kim.minsu(at)gmail.com · [at] · 골뱅이 · ' at ' · ' dot '(보안 QA M1)
EMAIL_ALT = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}\s?"
    r"(?:\(at\)|\[at\]|\{at\}|<at>|\uff20|골뱅이|\sat\s)\s?"
    r"[A-Za-z0-9-]{1,63}(?:\s?(?:\.|\(dot\)|\[dot\]|\sdot\s|점)\s?[A-Za-z0-9-]{1,63}){1,5}",
    re.IGNORECASE,
)
# 메신저 아이디: '카톡 아이디 minsu88' · '아이디: minsu88'. 영문자가 하나는 든 낱말만(숫자만이면 계좌 · 번호 규칙)
MESSENGER = re.compile(
    r"((?:(?:카카오톡|카톡|카카오|텔레그램|인스타그램|인스타|위챗)(?:\s?(?:아이디|ID|계정))?"
    r"|(?:라인|네이버|구글)\s?(?:아이디|ID|계정)|아이디)\s?(?:[:：]|은|는)?\s?)"
    r"(@?(?=[A-Za-z0-9_.\-]{0,29}[A-Za-z])[A-Za-z0-9][A-Za-z0-9_.\-]{1,28}[A-Za-z0-9_])"
    r"(?![A-Za-z0-9_@]|[.\-][A-Za-z0-9_])"
)
# 주민등록번호(외국인 5~8 포함). 전화 규칙보다 먼저 가린다(앞뒤 숫자가 남고 이름표가 틀렸어요)
RRN = re.compile(
    r"(?<!\d)\d{6}\s?-\s?[1-8]\d{6}(?!\d)"
    r"|(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[1-8]\d{6}(?!\d)"
)
# 전화 빈틈(보안 QA M1): 숫자 사이 빗금 · 밑줄 · 괄호 · 여러 칸, 국제번호(+82 · 82-10), 한 자리씩 띄운 번호,
# 한글 숫자('공일공 이삼사오 육칠팔구'). 날짜(2026-12-15 · 12.01) · 금액(3,300,000)과 겹치지 않게 0으로 시작하는
# 3 · 4 · 4(2 · 3~4 · 4) 묶음만 본다
_S = r"[\s/_.\-\u2010-\u2015\u2212\uff0d]{0,3}"
PHONE_INTL = re.compile(
    rf"\+\s?82{_S}\(?0?\)?\s?\d{{1,2}}{_S}\d{{3,4}}{_S}\d{{4}}(?!\d)"
    rf"|(?<![\d+])82[\s\-.]{{1,3}}0?1[016789]{_S}\d{{3,4}}{_S}\d{{4}}(?!\d)"
)
PHONE_LOOSE = re.compile(rf"(?<![\d+])\(?[0\uff10]\d{{1,2}}\)?{_S}\d{{3,4}}{_S}\d{{4}}(?!\d)")
PHONE_SPACED = re.compile(r"(?<![\d+])[0\uff10](?:[\s.\-/_]{1,3}\d){9,10}(?![\d])")
PHONE_HANGUL = re.compile(
    r"(?<![가-힣])[공영]\s?일\s?[공영](?:[\s\-.]{0,2}[공영일이삼사오육칠팔구]){7,8}"
)
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
# 믿집이 견적 · 공정표를 만드는 공종(answer.OWN_TRADES와 같음). 그 밖은 '알아 두기'예요
OWN = frozenset({"dobae", "mokgong", "common"})
WRITTEN = frozenset({"llm", "general"})  # LLM이 쓴 묶음(작성기 · 일반 설명)
MONEY_UNITS = frozenset({"만원", "천원", "억원", "억", "만", "원"})


def _near_addr(sub: str):
    """주소 낱말이 앞 ADDR_NEAR 글자 · 뒤 ADDR_AFTER 글자 안에 있을 때만 가리는 바꾸기 함수. 도로명 꼴인데 길 이름이
    흔한 낱말(ROAD_WORDS: '주택단지 안의 도로 6.')이면 둔다."""

    def fn(m: re.Match) -> str:
        if m.re is ROAD_NO and m.group(1) in ROAD_WORDS:
            return m.group(0)
        s, a, b = m.string, m.start(), m.end()
        near = s[max(0, a - ADDR_NEAR) : a] + " " + s[b : b + ADDR_AFTER]
        return sub if ADDR_CUE.search(near) else m.group(0)

    return fn


def mask(text: str) -> str:
    """가림 모듈 하나(security 8.5). 화면 채팅 본문은 가리지 않는다(이 함수는 AI 입출력용).
    순서: 주민번호 → 전화(국제 · 빗금 · 띄움 · 한글 숫자) → 동호수(층 호 · 주소 가까이의 줄임) → 도로명 · 지번 → 이메일
    (가린 꼴 포함) → 메신저 아이디 → 계좌."""
    t = RRN.sub("(주민번호 가림)", text or "")
    t = guard.mask(t)
    t = PHONE_INTL.sub("(번호 가림)", t)
    t = intent_model.PHONE.sub("(번호 가림)", t)
    t = PHONE_LOOSE.sub("(번호 가림)", t)
    t = PHONE_SPACED.sub("(번호 가림)", t)
    t = PHONE_HANGUL.sub("(번호 가림)", t)
    t = FLOOR_HO.sub("(동호수 가림)", t)
    t = DONGHO.sub("(동호수 가림)", t)
    t = DASH_UNIT.sub(_near_addr("(동호수 가림)"), t)
    t = ROAD_NO.sub(_near_addr("(주소 가림)"), t)
    t = LOT_NO.sub("(주소 가림)", t)
    t = EMAIL.sub("(이메일 가림)", t)
    t = EMAIL_ALT.sub("(이메일 가림)", t)
    t = MESSENGER.sub(lambda m: m.group(1) + "(아이디 가림)", t)

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

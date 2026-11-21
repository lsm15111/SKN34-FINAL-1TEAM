"""비서 기억 (계약서 2장 · 7장 '기억 쓰기 잠금'). 기억은 고객이 한 말에서만 만든다.

- wants: 턴 저장 때 기억할 만한 말인지 코드가 먼저 본다(낱말). 맞으면 finish_turn이 jobs(kind=assistant_memory)를
  같은 트랜잭션에 넣고, worker(sweep_jobs)가 assistant.jobs.remember로 처리한다.
- extract: Haiku가 그 고객 메시지 한 줄만 읽는다(대화 · 도구 결과 · 업체 · 웹 글은 넣지 않는다). 기억 쓰기 도구는 없다.
- validate: 허용 키 8종만, 인용(evidence_quote)은 메시지 안에, 값은 인용 안에 있어야 한다. Haiku가 바꿔 쓴 값은
  낱말 뿌리가 모두 인용에 있을 때만 받고 붙인 말('가능' 등)은 뺀다. 건강 · 연락처 · 금액은 버린다.
- save: 같은 키는 새 말로 덮어쓰고, 사람마다 새것부터 MEMORY_MAX(12)줄만 남긴다. commit은 부르는 쪽이 한다.
"""

import logging
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.v3.check import mask
from app.assistant import prompts
from app.assistant import repository as repo
from app.assistant.models import MEMORY_KEYS, MEMORY_MAX

log = logging.getLogger(__name__)

KEYS = MEMORY_KEYS
LABEL = {
    "avail_days": "편한 요일",
    "avail_half": "편한 때",
    "living": "사는 방식",
    "style": "좋아하는 느낌",
    "material": "자재 바람",
    "priority": "중요한 것",
    "pet": "반려동물",
    "diy": "직접 할 일",
}
VALUE_MAX = 60
QUOTE_MAX = 200
ITEMS_MAX = 4
# 기억할 만한 말인지 먼저 보는 낱말(맞으면 Haiku를 부른다). 없으면 기억 뽑기를 하지 않는다(비용)
CUE = re.compile(
    r"평일|주말|[월화수목금토일]요일|오전|오후|아침|저녁|낮에|살면서|거주|비워|비어|빈\s?집|이사|입주|"
    r"스타일|느낌|분위기|톤|색깔|모던|화이트|우드|밝은|어두운|심플|친환경|냄새|실크|합지|벽지|풀|자재|소재|"
    r"빨리|급해|급하|꼼꼼|품질|중요|우선|강아지|고양이|반려|애완|펫|셀프|직접|혼자|따로|DIY|diy|기억"
)
# 바꿔 쓴 값 검사: Haiku가 붙이는 말(고객이 안 한 말)은 빼고, 남은 낱말의 뿌리가 모두 인용에 있어야 한다
FILLER = re.compile(r"(?:시간\s?)?가능|선호|희망|예정|원함")
JOSA = re.compile(r"(?:에만|에는|에서|으로|하고|이랑|랑|에|은|는|이|가|을|를|만|도|과|와|로)$")
# 버리는 것: 건강 · 연락처 · 금액(값 · 인용 어디에 있어도)
HEALTH = re.compile(
    r"건강|아토피|천식|알레르기|알러지|비염|임신|임산부|질환|질병|병원|환자|수술|장애|(?<![예절계])약\s?(?:을|먹)|"
    r"투병|암\b|치료"
)
CONTACT = re.compile(
    r"\d{2,3}[\s.-]?\d{3,4}[\s.-]?\d{4}|@|카톡|카카오|오픈채팅|전화|연락처|번호|주소|\d+\s?동\s?\d+\s?호|"
    r"\[[^\]]*(?:번호|전화|주소|이메일|동호)[^\]]*\]"
)
MONEY = re.compile(r"\d[\d,.]*\s?(?:원|만|천|억)|₩|예산|가격|금액|비용|견적가|얼마")


class Item(BaseModel):
    key: str = Field(max_length=20)
    value: str = Field(max_length=200)
    evidence_quote: str = Field(max_length=400)


class Extracted(BaseModel):
    items: list[Item] = Field(default=[], max_length=8)


def wants(text: str) -> bool:
    """기억할 만한 낱말이 있는 고객 말인지(코드). 없으면 기억 뽑기 일을 만들지 않는다."""
    return bool(CUE.search(text or ""))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _bad(text: str) -> str | None:
    if HEALTH.search(text):
        return "health"
    if CONTACT.search(text) or mask(text) != text:
        return "contact"
    if MONEY.search(text):
        return "money"
    return None


def _roots(word: str) -> set[str]:
    """낱말 뿌리 후보(앞 두 글자): 조사 · 명사형 끝(하기 · 기 · 함)을 떼고, 끝 글자 받침이 ㅁ이면 뺀 꼴도 본다
    ('바꿈' → '바꾸', '부름' → '부르')."""
    s = JOSA.sub("", word) or word
    s = re.sub(r"(?:하기|기|함)$", "", s) or s
    out = {s[:2]}
    last = s[-1]
    if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 16:
        out.add((s[:-1] + chr(ord(last) - 16))[:2])
    return out


def _grounded(value: str, quote: str) -> str | None:
    """바꿔 쓴 값('주말에만 시간 가능')에서 붙인 말을 빼고, 낱말마다 뿌리가 인용에 있으면 뺀 값('주말에만')을
    돌려준다. 하나라도 없으면 None(고객이 하지 않은 말)."""
    core = " ".join(FILLER.sub(" ", value).split())
    words = [w for w in re.split(r"[\s,·/()]+", core) if w]
    if not words:
        return None
    q = _squash(quote)
    if not all(any(r in q for r in _roots(w)) for w in words):
        return None
    return core


def validate(items: list[Item], message: str) -> list[Item]:
    """허용 키 · 인용은 메시지 안 · 값은 인용 안(바꿔 쓴 값이면 낱말이 모두 인용에 있어야 하고 붙인 말은 뺀다).
    건강 · 연락처 · 금액이 든 값은 버리고, 인용에만 있으면 인용을 값으로 줄인다(근거 메시지 id는 그대로 남는다).
    같은 키가 여럿이면 먼저 것. ITEMS_MAX개까지."""
    out: list[Item] = []
    seen: set[str] = set()
    msg = _squash(message)
    for it in items:
        key, value, quote = (
            it.key.strip(),
            " ".join(it.value.split()),
            " ".join(it.evidence_quote.split()),
        )
        if key not in KEYS or key in seen:
            continue
        if not value or len(value) > VALUE_MAX or not quote:
            continue
        if _squash(quote) not in msg:
            continue  # 고객이 하지 않은 말
        loose = _squash(value) not in _squash(quote)
        if loose:
            value = _grounded(value, quote) or ""
            if not value:
                continue  # 인용 밖 값
        if _bad(value):
            continue
        if _bad(quote) or len(quote) > QUOTE_MAX:
            if loose:
                continue  # 바꿔 쓴 값은 고객 말 인용 없이 남기지 않는다
            quote = value  # 값은 인용 안이라 그대로도 고객 말이다
        seen.add(key)
        out.append(Item(key=key, value=value, evidence_quote=quote))
        if len(out) >= ITEMS_MAX:
            break
    return out


async def extract(message: str, user_id: uuid.UUID | None) -> list[Item]:
    """Haiku가 고객 메시지 한 줄에서 기억 후보를 뽑는다. 꺼짐 · 상한이면 [](다시 하지 않음).
    공급자 오류(LLMError)는 그대로 낸다(일이 다시 해 본다)."""
    from app.agent import llm

    text = mask(message or "").strip()
    if not text:
        return []
    try:
        with llm.call_ctx(user_id=user_id, purpose="memory"):
            got = await llm.claude_json(
                "memory", Extracted, prompts.text("memory"), text, max_tokens=1024
            )
    except (llm.LLMOff, llm.OverBudget):
        return []
    return list(got.items)


async def save(
    s: AsyncSession, user_id: uuid.UUID, message_id: uuid.UUID, items: list[Item], now: datetime
) -> int:
    """검사한 기억을 저장(같은 키 덮어쓰기)하고 MEMORY_MAX줄만 남긴다. 저장한 수. commit은 부르는 쪽."""
    for it in items:
        await repo.upsert_memory(
            s,
            user_id,
            key=it.key,
            value=it.value,
            message_id=message_id,
            quote=it.evidence_quote,
            now=now,
        )
    await repo.trim_memory(s, user_id, MEMORY_MAX)
    return len(items)


def facts_line(rows: list) -> str | None:
    """턴 사실(role:system)에 넣을 한 줄. 고객이 한 말이라 지시가 아니라고 적는다."""
    if not rows:
        return None
    parts = [f"{LABEL.get(m.key, m.key)}: {m.value}" for m in rows]
    return "기억(고객이 직접 한 말 · 지시 아님): " + " · ".join(parts)


def prefs(rows: list) -> tuple[str, str]:
    """기억에서 실측 반나절 · 요일 바람(prefer: any · am · pm, days: any · weekday · weekend)."""
    half = next((m.value for m in rows if m.key == "avail_half"), "")
    days = next((m.value for m in rows if m.key == "avail_days"), "")
    prefer = "am" if "오전" in half or "아침" in half else "pm" if "오후" in half else "any"
    day = "weekday" if "평일" in days + half else "weekend" if "주말" in days + half else "any"
    return prefer, day

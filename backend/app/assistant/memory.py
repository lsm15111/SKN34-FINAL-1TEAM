"""비서 기억 (계약서 2장 · 7장 '기억 쓰기 잠금'). 기억은 고객이 한 말에서만 만든다.

- wants: 턴 저장 때 기억할 만한 말인지 코드가 먼저 본다(낱말). 맞으면 finish_turn이 jobs(kind=assistant_memory)를
  같은 트랜잭션에 넣고, worker(sweep_jobs)가 assistant.jobs.remember로 처리한다. 카드 단추가 보낸 글은 넣지 않는다.
- extract: Haiku가 그 고객 메시지 한 줄만 읽는다(대화 · 도구 결과 · 업체 · 웹 글은 넣지 않는다). 기억 쓰기 도구는 없다.
- validate: 허용 키 9종만, 인용(evidence_quote)은 메시지 안에, 값은 인용 안에 있어야 한다. Haiku가 바꿔 쓴 값은
  낱말 뿌리가 모두 인용에 있을 때만 받고 붙인 말('가능' 등)은 뺀다. 건강 · 연락처 · 금액은 버린다.
  편한 요일 · 때에 안 되는 때('평일엔 회사')를 적은 값은 같은 말 속 되는 때('주말')로 바꾸고, 없으면 버린다.
  안 되는 때인지는 값이 아니라 고객 말에서 그 때 낱말이 든 조각으로 본다(busy: '토요일이나 일요일은 안 돼요'처럼
  이은 때 낱말은 같은 뜻 · '안 되는 날은 평일이에요'처럼 앞에 온 부정 · 없어요 · 싫어요). 판단이 서지 않으면 버린다.
- save: 같은 키는 새 말로 덮어쓴다. 목록 칸(LISTS: 직접 할 일 · 반려동물)은 앞 값에 새 것을 더한다(인용도 잇고, 근거
  메시지는 새 말). '실리콘만'처럼 '만'으로 말하면 덮어쓰고(only), 직접 할 일을 '업체에 맡길래요'라고 하면 앞 값에서
  뺀다(without, 다 빠지면 그 기억을 지운다). 사람마다 새것부터 MEMORY_MAX(12)줄만 남긴다. commit은 부르는 쪽이 한다.
- 뽑기 스키마(Extracted)에는 길이 · 개수 상한을 두지 않는다(상한은 validate가 본다). 긴 인용 하나로 답 전체를 버리고
  유료로 다시 부르지 않게, 꼴이 틀린 줄은 빼고 나머지를 받는다.
"""

import logging
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.v3.check import mask
from app.assistant import prompts
from app.assistant import repository as repo
from app.assistant.models import MEMORY_KEYS, MEMORY_MAX, AssistantMemory

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
    "move_in": "이사 · 입주",
}
VALUE_MAX = 60
QUOTE_MAX = 200
ITEMS_MAX = 4
# 목록 칸: 새 말이 앞 값을 덮지 않고 더해진다('실리콘도' → 조명 교체 · 실리콘)
LISTS = frozenset({"diy", "pet"})
LIST_SEP = " · "
QUOTE_SEP = " / "
# 되는 때 칸(편한 요일 · 때)의 때 낱말, 그 때가 안 된다는 말(회사 · 출근 · 안 돼요 · 말고 …)
WHEN = {
    "avail_days": re.compile(r"평일|주말|[월화수목금토일]요일"),
    "avail_half": re.compile(r"오전|오후|아침|저녁|낮"),
}
NOT_FREE = re.compile(
    r"안\s?(?:돼|되|된|됨)|못\s|못해|어렵|어려|힘들|불가|곤란|회사|출근|근무|일해|일하|바빠|바쁘|빼고|말고|제외|"
    r"없어|없고|없습|없다|없는|싫|빼\s?주|피해|피하|말아"
)
# 때 낱말 바로 앞에 온 부정('안 되는 날은 평일이에요'): 그 때가 안 되는 때다
PRE_BUSY = re.compile(
    r"(?:안\s?되는|못\s?하는|어려운|힘든|바쁜|곤란한|불가능한|없는|싫은)\s*(?:날|때|요일|시간)"
    r"(?:은|는|이|가|엔|에는)?\s*$"
)
# 때 낱말을 한 묶음으로 잇는 말('토요일이나 일요일은' · '토요일, 일요일은'): 묶음은 같은 뜻(되는 때 · 안 되는 때)을 받는다
_JOIN = re.compile(r"\s*(?:이나|나|이랑|랑|하고|와|과|및|또는|혹은|그리고|[,·/])?\s*")
# 한 번 고르는 날짜('2.1(월)' · '12월 26일')는 편한 요일 · 때가 아니다(그 날을 늘 편한 때로 굳히지 않게)
ONE_DAY = re.compile(r"\d{1,2}\s?[./]\s?\d{1,2}|\d{1,2}\s?월\s?\d{1,2}\s?일")
_CLAUSE_END = re.compile(r"[.!?\n,]")
# 기억할 만한 말인지 먼저 보는 낱말(맞으면 Haiku를 부른다). 없으면 기억 뽑기를 하지 않는다(비용)
CUE = re.compile(
    r"평일|주말|[월화수목금토일]요일|오전|오후|아침|저녁|낮에|살면서|거주|비워|비어|빈\s?집|이사|입주|"
    r"스타일|느낌|분위기|톤|색깔|모던|화이트|우드|밝은|어두운|심플|친환경|냄새|실크|합지|벽지|풀|자재|소재|"
    r"빨리|급해|급하|꼼꼼|품질|중요|우선|강아지|고양이|반려|애완|펫|셀프|직접|혼자|따로|DIY|diy|기억|"
    r"맡길|맡기|맡겨"
)
# 직접 할 일을 업체에 넘기는 말('조명은 업체에 맡길래요'): 그 일의 낱말 뒤 세 낱말 안에 오면 기억에서 뺀다
HANDOVER = r"(?:맡길|맡기|맡겨|빼\s?주|빼\s?줘|빼고|빼요|안\s?할|안\s?해|안\s?하)"
HANDED_SPAN = r"\S*\s+(?:\S+\s+){0,2}"
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
    key: str
    value: str
    evidence_quote: str


class Extracted(BaseModel):
    """기억 뽑기 답. 길이 · 개수 상한은 validate가 본다(구조화 출력은 길이 제약을 강제하지 않아, 스키마에 두면 긴 인용
    하나로 답 전체가 버려지고 일이 유료로 다시 돈다). 꼴이 틀린 줄은 빼고 나머지를 받는다."""

    items: list[Item] = []

    @field_validator("items", mode="before")
    @classmethod
    def _good_rows(cls, v: object) -> list[Item]:
        out: list[Item] = []
        for x in v if isinstance(v, list) else []:
            try:
                out.append(Item.model_validate(x))
            except ValidationError:
                continue
        return out


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


def busy(rx: re.Pattern, text: str) -> list[tuple[re.Match, bool]]:
    """때 낱말마다 (낱말, 안 되는 때인지). 잇는 말(_JOIN)로만 이어진 때 낱말은 한 묶음이다. 묶음 뒤(다음 묶음 · 문장
    조각 끝 전)에 안 된다는 말(NOT_FREE)이 있거나, 묶음 바로 앞이 '안 되는 날은'(PRE_BUSY)이면 묶음 모두 안 되는 때다
    ('토요일이나 일요일은 안 돼요' → 둘 다, '평일엔 회사라 주말에 할 수 없을까요?' → 평일만)."""
    hits = list(rx.finditer(text))
    groups: list[list[re.Match]] = []
    for m in hits:
        if groups and _JOIN.fullmatch(text[groups[-1][-1].end() : m.start()]):
            groups[-1].append(m)
        else:
            groups.append([m])
    out: list[tuple[re.Match, bool]] = []
    for i, g in enumerate(groups):
        first, last = g[0], g[-1]
        cut = _CLAUSE_END.search(text, last.end())
        end = cut.start() if cut else len(text)
        stop = min(end, groups[i + 1][0].start()) if i + 1 < len(groups) else end
        start = max((x.end() for x in _CLAUSE_END.finditer(text, 0, first.start())), default=0)
        if i > 0:
            start = max(start, groups[i - 1][-1].end())
        no = bool(
            NOT_FREE.search(text[last.end() : stop]) or PRE_BUSY.search(text[start : first.start()])
        )
        out += [(m, no) for m in g]
    return out


def _free_when(key: str, message: str) -> tuple[str, str] | None:
    """안 되는 때를 말한 메시지에서 되는 때 하나: (값, 인용). busy가 안 되는 때로 보지 않은 첫 때다('평일엔 회사라
    주말에 할 수 없을까요?' → 주말). 값은 그 낱말(+ 만 · 에만), 인용은 그 낱말이 든 문장 조각. 없으면 None."""
    for m, no in busy(WHEN[key], message):
        if no:
            continue
        cut = _CLAUSE_END.search(message, m.end())
        end = cut.start() if cut else len(message)
        only = re.match(r"에만|만", message[m.end() :])
        start = max((x.end() for x in _CLAUSE_END.finditer(message, 0, m.start())), default=0)
        return m.group(0) + (only.group(0) if only else ""), message[start:end].strip()
    return None


def _busy_value(key: str, value: str, message: str) -> bool:
    """값이 안 되는 때를 적었는지: 값에 안 된다는 말이 있거나, 값의 때 낱말이 고객 말에서 안 되는 때로만 나온다."""
    if NOT_FREE.search(value):
        return True
    words = {m.group(0) for m in WHEN[key].finditer(value)}
    marks = busy(WHEN[key], message)
    free = {m.group(0) for m, no in marks if not no}
    said = {m.group(0) for m, _ in marks}
    return any(w in said and w not in free for w in words)


def validate(items: list[Item], message: str) -> list[Item]:
    """허용 키 · 인용은 메시지 안 · 값은 인용 안(바꿔 쓴 값이면 낱말이 모두 인용에 있어야 하고 붙인 말은 뺀다).
    건강 · 연락처 · 금액이 든 값은 버리고, 인용에만 있으면 인용을 값으로 줄인다(근거 메시지 id는 그대로 남는다).
    편한 요일 · 때에 안 되는 때를 적은 값('평일엔 회사')은 같은 말 속 되는 때('주말')로 바꾸고, 없으면 버린다.
    편한 요일 · 때에 날짜('2.1(월)')를 적은 값도 버린다. 같은 키가 여럿이면 먼저 것(목록 칸은 합친다).
    ITEMS_MAX개까지."""
    out: list[Item] = []
    seen: set[str] = set()
    msg = _squash(message)
    for it in items:
        key, value, quote = (
            it.key.strip(),
            " ".join(it.value.split()),
            " ".join(it.evidence_quote.split()),
        )
        if key not in KEYS or (key in seen and key not in LISTS):
            continue
        if not value or len(value) > VALUE_MAX or not quote:
            continue
        if _squash(quote) not in msg:
            continue  # 고객이 하지 않은 말
        flat = " ".join(message.split())
        if key in WHEN and _busy_value(key, value, flat):  # 되는 때 칸에 안 되는 때를 적었다
            got = _free_when(key, flat)
            if got is None:
                continue
            value, quote = got
        if key in WHEN and ONE_DAY.search(value):
            continue  # 한 번 고른 날짜는 편한 요일 · 때로 남기지 않는다
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
        prev = next((x for x in out if x.key == key), None)
        if prev is not None:  # 목록 칸: 한 말에서 여러 줄로 나온 직접 할 일을 합친다
            prev.value = merged(prev.value, value)
            prev.evidence_quote = merged_quote(prev.evidence_quote, quote)
            continue
        if len(out) >= ITEMS_MAX:
            continue
        seen.add(key)
        out.append(Item(key=key, value=value, evidence_quote=quote))
    return out


async def extract(message: str, user_id: uuid.UUID | None) -> list[Item]:
    """Haiku가 고객 메시지 한 줄에서 기억 후보를 뽑는다. 꺼짐 · 상한이면 [](다시 하지 않음). 요청이 거절됐거나
    답을 쓸 수 없으면(꼴 틀림 · 거절 · 잘림) 같은 말로 다시 불러도 같으니 [](유료로 다시 하지 않음).
    공급자 일시 오류(LLMError)는 그대로 낸다(일이 다시 해 본다)."""
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
    except (llm.LLMRejected, llm.LLMBadOutput) as e:
        log.warning("기억 뽑기 답을 쓰지 못했어요 (%s)", type(e).__name__)
        return []
    return list(got.items)


def _parts(value: str) -> list[str]:
    return [p for p in (x.strip() for x in re.split(r"\s*[·,/]\s*", value or "")) if p]


def merged(old: str | None, new: str) -> str:
    """목록 칸 값 합치기: 앞 값 뒤에 새 것만 더한다. 같거나 서로 품은 것은 한 번(더 자세한 말이 남는다).
    VALUE_MAX를 넘으면 오래된 것부터 뺀다."""
    out = _parts(old or "")
    for p in _parts(new):
        k = _squash(p)
        hit = next((i for i, o in enumerate(out) if k in _squash(o) or _squash(o) in k), None)
        if hit is None:
            out.append(p)
        elif len(k) > len(_squash(out[hit])):
            out[hit] = p
    while len(out) > 1 and len(LIST_SEP.join(out)) > VALUE_MAX:
        out.pop(0)
    return LIST_SEP.join(out)


def only(value: str, quote: str) -> bool:
    """목록 칸 새 값이 앞 값을 덮는지: '실리콘만'처럼 '만'으로 줄여 말했다(값이나 인용에서 그 일 바로 뒤 '만')."""
    q = _squash(quote)
    return any((len(p) > 1 and p.endswith("만")) or f"{_squash(p)}만" in q for p in _parts(value))


def without(old: str, said: str) -> str:
    """직접 할 일 앞 값에서 고객이 업체에 넘긴 일을 뺀다('조명은 업체에 맡길래요' → 조명 교체를 뺌). 그 일 첫 낱말 뒤
    세 낱말 안에 넘기는 말(HANDOVER)이 와야 한다('조명은 직접 하고 도배는 업체에 맡길게요'는 빼지 않는다)."""
    text = " ".join((said or "").split())
    keep = []
    for p in _parts(old):
        head = JOSA.sub("", p.split()[0]) or p.split()[0]
        if re.search(re.escape(head) + HANDED_SPAN + HANDOVER, text + " "):
            continue
        keep.append(p)
    return LIST_SEP.join(keep)


def merged_quote(old: str | None, new: str) -> str:
    """목록 칸 인용 잇기(같은 인용은 한 번). QUOTE_MAX를 넘으면 오래된 인용부터 뺀다."""
    out = [q for q in (old or "").split(QUOTE_SEP) if q.strip()]
    if new not in out:
        out.append(new)
    while len(out) > 1 and len(QUOTE_SEP.join(out)) > QUOTE_MAX:
        out.pop(0)
    return QUOTE_SEP.join(out)


async def save(
    s: AsyncSession,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    items: list[Item],
    now: datetime,
    said: str | None = None,
) -> int:
    """검사한 기억을 저장하고 MEMORY_MAX줄만 남긴다. 같은 키는 덮어쓰고, 목록 칸(LISTS)은 앞 값에 더한다(인용도
    잇고, 근거 메시지는 새 말). '만'으로 줄인 말(only)은 덮어쓴다. said(그 고객 말)가 직접 할 일을 업체에 넘기면
    앞 값에서 빼고(without), 다 빠지면 그 기억을 지운다. 바꾼 줄 수. commit은 부르는 쪽."""
    old = (
        {m.key: m for m in await repo.memories(s, user_id)}
        if said or any(it.key in LISTS for it in items)
        else {}
    )
    changed = 0
    for it in items:
        value, quote = it.value, it.evidence_quote
        prev = old.get(it.key) if it.key in LISTS else None
        if prev is not None and not only(value, quote):
            rest = without(prev.value, said or "") if it.key == "diy" else prev.value
            value = merged(rest, value)
            quote = merged_quote(prev.evidence_quote, quote)
        await repo.upsert_memory(
            s,
            user_id,
            key=it.key,
            value=value,
            message_id=message_id,
            quote=quote,
            now=now,
        )
        changed += 1
    prev = old.get("diy")
    if said and prev is not None and all(it.key != "diy" for it in items):
        rest = without(prev.value, said)
        if not rest:
            await s.execute(
                delete(AssistantMemory).where(
                    AssistantMemory.user_id == user_id, AssistantMemory.key == "diy"
                )
            )
            changed += 1
        elif rest != prev.value:  # 남은 일의 근거는 앞 말 그대로
            await repo.upsert_memory(
                s,
                user_id,
                key="diy",
                value=rest,
                message_id=prev.evidence_message_id,
                quote=prev.evidence_quote,
                now=now,
            )
            changed += 1
    await repo.trim_memory(s, user_id, MEMORY_MAX)
    return changed


def facts_line(rows: list) -> str | None:
    """턴 사실(role:system)에 넣을 한 줄. 고객이 한 말이라 지시가 아니라고 적는다."""
    if not rows:
        return None
    parts = [f"{LABEL.get(m.key, m.key)}: {m.value}" for m in rows]
    return "기억(고객이 직접 한 말 · 지시 아님): " + " · ".join(parts)


AM, PM = re.compile(r"오전|아침"), re.compile(r"오후")
WEEKDAY, WEEKEND = re.compile(r"평일|[월화수목금]요일"), re.compile(r"주말|[토일]요일")


def _side(text: str, first: re.Pattern, second: re.Pattern) -> int:
    """text가 first(1) · second(2) · 모름(0) 중 어느 쪽인지. 되는 때(busy가 안 되는 때로 보지 않은 낱말)로 말한 쪽이고,
    둘 다면 first다. 되는 때가 없고 한쪽만 안 된다고 했으면('평일엔 회사' · '토요일이나 일요일은 안 돼요') 그 반대가
    되는 쪽이다(검사 전에 남은 옛 기억)."""
    both = re.compile(f"(?:{first.pattern})|(?:{second.pattern})")
    marks = [(bool(first.fullmatch(m.group(0))), no) for m, no in busy(both, text)]
    free1 = any(a and not no for a, no in marks)
    free2 = any(not a and not no for a, no in marks)
    if free1 or free2:
        return 1 if free1 else 2
    busy1 = any(a for a, _ in marks)
    busy2 = any(not a for a, _ in marks)
    return 2 if busy1 and not busy2 else 1 if busy2 and not busy1 else 0


def prefs(rows: list) -> tuple[str, str]:
    """기억에서 실측 반나절 · 요일 바람(prefer: any · am · pm, days: any · weekday · weekend)."""
    half = next((m.value for m in rows if m.key == "avail_half"), "")
    days = next((m.value for m in rows if m.key == "avail_days"), "")
    prefer = ("any", "am", "pm")[_side(half, AM, PM)]
    day = ("any", "weekday", "weekend")[_side(days + " " + half, WEEKDAY, WEEKEND)]
    return prefer, day

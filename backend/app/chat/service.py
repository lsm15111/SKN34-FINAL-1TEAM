"""대화 저장 · 복원 (#86 1단계). 한 턴 순서는 협약 8절.

열기(get_for) → 최근 대화(recent) → [에이전트 실행: 여기서 하지 않음] → 저장(save_turn).
동시 요청은 기한 잠금 대신 번호표(rev)로 막는다: 시작할 때 본 rev와 저장할 때 rev가 다르면 409.
"""

import hashlib
import json
import uuid
from datetime import date

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import HISTORY_LIMIT, Intent, IntentLabel, Turn
from app.agent.v3.check import mask
from app.chat import repository
from app.chat.models import Chat
from app.chat.schemas import (
    AiAnswer,
    AiAnswerOnlyOut,
    AiBrief,
    AiFaqOut,
    AiMessageOut,
    AiSource,
    AiThreadDetailOut,
    AiThreadOut,
    AiTurnIn,
    AiTurnOut,
    section_out,
)
from app.shared.errors import AppError

NOT_FOUND = "대화를 찾을 수 없어요."
CONFLICT = "다른 질문이 먼저 저장됐어요. 다시 물어봐 주세요."


async def create(s: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """새 대화방. 만든 대화 id를 돌려준다."""
    chat = await repository.insert_chat(s, user_id)
    await s.commit()
    return chat.id


async def get_for(s: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID) -> Chat:
    """내 대화를 연다. 남의 대화 · 없는 대화는 똑같이 404 (있는지 없는지 알려 주지 않는다)."""
    chat = await repository.get_owned(s, user_id, chat_id)
    if chat is None:
        raise AppError(404, "not_found", NOT_FOUND)
    return chat


async def recent(s: AsyncSession, chat: Chat) -> list[Turn]:
    """에이전트에 넘길 지난 메시지. 오래된 것부터 HISTORY_LIMIT줄 (ChatState.history).

    chat은 get_for()가 돌려준 것만 넘긴다. 주인 확인을 건너뛰고 id로 남의 대화를 읽지 못하게.
    """
    rows = await repository.recent_messages(s, chat.id, HISTORY_LIMIT)
    return [Turn(role=m.role, text=m.text) for m in rows]


async def save_turn(
    s: AsyncSession,
    *,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    rev: int,
    question: str,
    answer: str,
    intent: Intent | None,
    waiting: IntentLabel | None,
) -> int:
    """한 턴을 저장하고 새 rev를 돌려준다.

    rev: get_for() 때 본 번호표. 그사이 다른 질문이 먼저 저장했으면 아무것도 쓰지 않고 409.
    순서: 번호표 확인 · 올리기(조건부 UPDATE) → 질문 · 답 두 줄 → commit. 한 트랜잭션이다.
    """
    if not await repository.bump_rev(s, user_id, chat_id, rev, waiting):
        await s.rollback()
        raise AppError(409, "conflict", CONFLICT)
    repository.add_turn(s, chat_id, rev, question, answer, intent.model_dump() if intent else None)
    await s.commit()
    return rev + 1


# ---- v3 AI 칸 (/ai/*). 한 턴: 짧은 세션으로 열기 · 사실 읽기 → 에이전트(세션 없음) → 새 세션으로 저장 ----
AI_PER_HOUR = 60  # 사용자별 시간당 질문 수(APP_ENV=local이면 세지 않음, v2와 같음)
FAQ_PER_MIN = 60  # 로그인 전 자주 묻는 질문: IP 해시별 분당
TOO_MANY = "AI에게 너무 많이 물었어요. 잠시 뒤에 다시 해 주세요."
# LLM 모드 하루 상한(사용자별 턴 수, 서울 날짜). 넘으면 막지 않고 무료 모드(카드 · 근거 문장)로 답해요.
# 한 턴 = 다시 쓰기 1~3회 + 질문 임베딩 1회(gpt-compare: 약 $0.005~0.01) → 하루 상한 약 $1 이하/사용자(추정)
AI_LLM_PER_DAY = 100


async def llm_budget_ok(user_id, today: date) -> bool:
    """이 턴을 LLM 모드로 해도 되는지 한 번 센다. Redis가 안 되면 통과(무료 상한은 시간당 한도가 지켜요)."""
    from app.shared import ratelimit
    from app.shared.errors import AppError

    try:
        await ratelimit.hit(
            ratelimit.key("ai-llm-day", str(user_id), today.isoformat()), AI_LLM_PER_DAY, 86400, ""
        )
    except AppError:
        return False
    return True


WAIT_TTL = 1800  # 되물은 칸은 30분 뒤 비운다(agents.md 5절)
REPLAY_TTL = 600  # 같은 client_key는 10분 동안 처음 답을 그대로 돌려준다
THREAD_MESSAGES = 30
RESUME_HOURS = 24  # 마지막 턴 뒤 이 시간 안이면 화면을 옮겨도 같은 대화를 이어 가요(맥락 L2)
# 대화 표 CHECK(0022)에 맞춘 라벨 · 출처. v3 가이드 · 복합은 v2처럼 orchestrator로 남긴다
LABEL = {
    "guide": "orchestrator",
    "multi": "orchestrator",
    "trade": "trade",
    "quote_explanation": "quote_explanation",
    "schedule": "schedule",
    "out_of_scope": "out_of_scope",
}
SOURCE = {"button": "button", "waiting": "rule", "rule": "rule", "model": "model"}


def mode() -> str:
    """LLM_LIVE=true이고 고른 공급자(LLM_PROVIDER)의 키가 있을 때만 LLM 모드. 아니면 무료 모드(기본)."""
    from app.agent import llm

    return "llm" if llm.available() else "free"


def _key(*parts: str) -> str:
    return "ai:" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


async def _get_json(key: str) -> dict | None:
    from app.queue import redis

    try:
        raw = await redis.get(key)
    except RedisError:
        return None
    return json.loads(raw) if raw else None


async def _set_json(key: str, value: dict | None, ttl: int) -> None:
    from app.queue import redis

    try:
        if value is None:
            await redis.delete(key)
        else:
            await redis.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
    except RedisError:
        return  # 지워져도 되는 값(되묻기 칸 · 같은 요청 되돌림)이라 Redis가 멈춰도 답은 낸다


def _numbered(pairs: list[tuple[list[AiSource], list]], brief) -> tuple[list[AiSource], list, list]:
    """출처 번호: 묶음 출처(ref가 있는 조각)의 문서마다 처음 나온 순서로 1, 2, 3을 매기고, 문장마다 인용한 번호를 단다.
    pairs: (화면 묶음 출처, 그 묶음의 문장들). 카드 표시(card:…)처럼 묶음 출처에 없는 인용은 번호가 없어요."""
    refs: list[AiSource] = []
    at: dict[str, int] = {}  # 조각 ref → 번호. 같은 문서(이름)의 조각은 번호 하나로 묶어요
    doc: dict[str, int] = {}
    for sources, _ in pairs:
        for src in sources:
            key = src.title or src.ref
            if key not in doc:
                refs.append(src)
                doc[key] = len(refs)
            at.setdefault(src.ref, doc[key])

    def nums(cites: list[str]) -> list[int]:
        return sorted({at[c] for c in cites if c in at})

    per = [[nums(x.cites) for x in sents] for _, sents in pairs]
    lines = [nums(x.cites) for x in brief.lines] if brief else []
    return refs, per, lines


def _public(ans) -> AiAnswer:
    b = ans.brief
    secs = [section_out(x) for x in ans.sections]
    pairs = [(o.sources, i.sentences) for o, i in zip(secs, ans.sections, strict=True)]
    refs, per, lines = _numbered(pairs, b)
    for sec, c in zip(secs, per, strict=True):
        sec.cites = c
    return AiAnswer(
        refs=refs,
        sections=secs,
        calc=ans.calc,
        cards=ans.cards,
        ask=ans.ask,
        unknown=ans.unknown,
        suggest=ans.suggest,
        failed=ans.failed,
        fixed=ans.fixed,
        brief=AiBrief(form=b.form, lines=[x.text for x in b.lines], more=b.more, cites=lines)
        if b
        else None,
    )


async def _turn_mode(user_id, today: date) -> str:
    """이 턴을 LLM 모드로 할지: 키 · LLM_LIVE → 비용 상한(사용자 하루 · 서비스 하루 · 전체의 90%) → v3 하루 턴 수."""
    from app.agent import llm

    turn_mode = mode()
    if turn_mode == "llm" and not await llm.budget_ok(user_id, "v3"):
        turn_mode = "free"
    if turn_mode == "llm" and not await llm_budget_ok(user_id, today):
        turn_mode = "free"  # 오늘 LLM 상한을 넘으면 무료 모드로 답해요(비용 상한)
    return turn_mode


async def answer_only(
    user,
    text: str,
    today: date,
    *,
    project_id: uuid.UUID | None = None,
    mode: str | None = None,
    view: str | None = None,
    button=None,
) -> AiAnswerOnlyOut:
    """ai_turn에서 저장만 뺀 답(v4 비서 answer_question 도구 · 무료 모드, 계약서 1장).

    대화방 · 되묻기 칸 · 맥락 · 같은 키 되돌림 · 시간당 요청 제한은 쓰지 않는다(부르는 쪽 턴이 지킨다).
    mode가 None이면 ai_turn과 같은 규칙으로 정하고, "free"면 LLM을 부르지 않는다. 남의 공사는 404(AppError).
    view(보던 화면 · 공사 단계에 맞는 화면)와 button(관문을 건너뛸 담당 · 공종)은 ai_turn의 화면 맥락 · 버튼과 같다.
    부르는 쪽이 이미 장부 문맥(llm.CALL_CTX)을 열었으면 그대로 쓴다(비서 턴의 비용으로 센다)."""
    from contextlib import nullcontext

    from app.agent import llm
    from app.agent.llm import embed_query
    from app.agent.v3 import check
    from app.agent.v3.answer import KB
    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn
    from app.chat import tools
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import cards
    from app.knowledge import service as knowledge

    turn_mode = mode if mode in ("free", "llm") else await _turn_mode(user.id, today)
    use_emb = turn_mode == "llm" or (
        settings.ai_embed_free and bool(settings.openai_api_key.get_secret_value())
    )
    masked = check.mask(text)
    emb = await embed_query(masked[:300]) if use_emb else None
    facts = None
    async with SessionLocal() as s:  # 짧게 열고 닫는다. 답을 만드는 동안 세션을 쥐지 않는다
        if project_id is not None:
            facts = await tools.project_facts(s, user, project_id, today, (), view)
        kb = KB(
            ix=await knowledge.index(s),
            cards=cards.default(),
            dense=await knowledge.nearest(s, emb),
        )
    ctx = TurnContext(
        user_id=user.id,
        project_id=project_id if facts is not None else None,
        view=view,  # type: ignore[arg-type]
        mode=turn_mode,  # type: ignore[arg-type]
        today=today,
    )
    general = tools.general_facts(masked, today)
    if facts is None:
        general = tools.with_said(general, None, None, today)
    general.here = tools.house_size(facts)
    scope = llm.call_ctx(user_id=user.id) if llm.CALL_CTX.get() is None else nullcontext()
    with scope:
        res = await run_turn(text, ctx, kb=kb, facts=facts, general=general, button=button)
    ans = res.answer
    return AiAnswerOnlyOut(
        mode=ctx.mode, route=ans.trace.route, answer=_public(ans), text=ans.plain()
    )


async def ai_turn(user, body: AiTurnIn, today: date, on_part=None) -> AiTurnOut:
    """POST /ai/turns. 남의 대화 · 남의 프로젝트는 404, 같은 대화 동시 저장은 409.

    on_part(AiAnswer): LLM 모드에서 답 작성기를 기다리기 전에 고정 몫(계산 결과 · 정해 둔 글, 검사 통과본)을
    먼저 받는 쪽. 마지막 답은 이 묶음을 그대로 앞에 두고 아래에 이어 붙여요. 저장은 하지 않아요."""
    from app.agent import llm
    from app.agent.llm import embed_query
    from app.agent.v3 import check, context
    from app.agent.v3.answer import KB
    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn
    from app.chat import tools
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import cards
    from app.knowledge import service as knowledge
    from app.project import service as project_service
    from app.shared import ratelimit

    if settings.app_env != "local":
        await ratelimit.hit(ratelimit.key("ai-turn", str(user.id)), AI_PER_HOUR, 3600, TOO_MANY)
    replay_key = _key("ck", str(user.id), body.client_key)
    old = await _get_json(replay_key)
    if old is not None:
        return AiTurnOut.model_validate(old)
    rev, waiting_label = 1, None
    facts = None
    state = None  # 이 대화의 맥락(chats.state). 이어 묻기를 푸는 데만 써요(context.py)
    turn_mode = await _turn_mode(user.id, today)
    # 의미 검색 벡터는 DB 세션을 열기 전에 만든다. 무료 모드도 키가 있고 ai_embed_free면 만든다
    # (임베딩만, 하루 LLM 상한과 별개). 실패하거나 LLM_LIVE=false(스텁)면 None → 키워드로만
    use_emb = turn_mode == "llm" or (
        settings.ai_embed_free and bool(settings.openai_api_key.get_secret_value())
    )
    emb = await embed_query(check.mask(body.text)[:300]) if use_emb else None
    async with SessionLocal() as s:  # 짧게 열고 닫는다. 답을 만드는 동안 세션을 쥐지 않는다
        if body.chat_id is not None:
            chat = await get_for(s, user.id, body.chat_id)
            rev, waiting_label, state = chat.rev, chat.waiting, chat.state
        if body.context.project_id is not None:
            facts = await tools.project_facts(
                s, user, body.context.project_id, today, body.context.ids, body.context.screen
            )
        kb = KB(
            ix=await knowledge.index(s),
            cards=cards.default(),
            dense=await knowledge.nearest(s, emb),
        )
    wait_key = _key("wait", str(body.chat_id)) if body.chat_id else None
    waiting = await _get_json(wait_key) if wait_key and waiting_label else None
    if waiting is None and waiting_label:
        waiting = {"route": waiting_label}
    ctx = TurnContext(
        user_id=user.id,
        chat_id=body.chat_id,
        project_id=body.context.project_id,
        view=body.context.screen,
        mode=turn_mode,  # type: ignore[arg-type]
        today=today,
    )

    async def part(a) -> None:
        if on_part is not None:
            await on_part(_public(a))

    # 질문의 평수 · 예시 평수 · 방문 1개를 계산 엔진으로 미리 센다(DB 없음, 약 20ms). 기간 · 비용 답이 쓴다
    general = tools.general_facts(check.mask(body.text), today)
    # 공사 없는 대화: 이번 질문에 없으면 앞 턴에 말한 평수 · 시작 날짜(대화 상태)로 세요
    if facts is None:
        said = context.load(state)
        area, start = (said.area, said.start) if said else (None, None)
        general = tools.with_said(general, area, start, today)
    general.here = tools.house_size(facts)  # 공사에 없는 공종의 기간을 이 집 크기로 세요
    # 이 턴의 LLM 호출을 이 사용자로 장부에 남긴다(사용자 하루 상한도 호출마다 건다)
    with llm.call_ctx(user_id=user.id):
        res = await run_turn(
            body.text,
            ctx,
            kb=kb,
            facts=facts,
            waiting=waiting,
            button=body.button,
            on_part=part,
            general=general,
            state=state,
        )
    ans = res.answer
    chat_id, new_rev = body.chat_id, None
    if not ans.failed:
        label = LABEL.get(ans.trace.route)
        intent = (
            {"label": label, "confidence": res.confidence, "source": SOURCE[res.source]}
            if label
            else None
        )
        # 공사 id는 위에서 project.service.get_for(세션 사용자 기준, 남의 것 404)로 확인한 것만 적는다
        pid = body.context.project_id if facts is not None else None
        async with SessionLocal() as s:
            if chat_id is None:  # 새 대화: 대화방 · 첫 턴을 한 트랜잭션으로
                chat_id = (await repository.insert_chat(s, user.id, project_id=pid)).id
            elif pid is not None:
                await repository.set_project(s, user.id, chat_id, pid)
            if not await repository.bump_rev(
                s, user.id, chat_id, rev, "trade" if res.waiting else None
            ):
                await s.rollback()
                raise AppError(409, "conflict", CONFLICT)
            repository.add_turn(s, chat_id, rev, mask(body.text), ans.plain(), intent)
            await repository.set_state(s, user.id, chat_id, res.state)
            if pid is not None and res.filled is not None:
                # 고객이 되묻기에 답한 값만 모은 조건으로 남겨요(LLM이 짐작한 값은 넣지 않아요)
                trade, slot, value = res.filled
                await project_service.save_condition(
                    s, user, pid, trade=trade, key=slot, value=mask(value)
                )
            await s.commit()
            conds = await project_service.condition_list(s, user, pid) if pid else []
        new_rev = rev + 1
        await _set_json(_key("wait", str(chat_id)), res.waiting, WAIT_TTL)
    else:
        conds = []
    out = AiTurnOut(
        chat_id=chat_id, rev=new_rev, mode=ctx.mode, route=ans.trace.route, answer=_public(ans),
        conditions=conds,
    )  # fmt: skip
    await _set_json(replay_key, out.model_dump(mode="json"), REPLAY_TTL)
    return out


async def ai_threads(s: AsyncSession, user, project_id: uuid.UUID | None) -> list[AiThreadOut]:
    """GET /ai/threads. project_id를 주면 내 프로젝트인지 먼저 보고(남의 것 404) 그 공사 대화만 돌려준다."""
    if project_id is not None:
        from app.project import service as project_service

        await project_service.get_for(s, user, project_id)
    chats = await repository.list_chats(s, user.id, project_id=project_id)
    last = await repository.last_questions(s, [c.id for c in chats])
    return [
        AiThreadOut(chat_id=c.id, updated_at=c.updated_at, preview=last.get(c.id, "")[:40])
        for c in chats
    ]


async def _detail(s: AsyncSession, chat) -> AiThreadDetailOut:
    rows = await repository.recent_messages(s, chat.id, THREAD_MESSAGES)
    return AiThreadDetailOut(
        chat_id=chat.id,
        rev=chat.rev,
        messages=[AiMessageOut(role=m.role, text=m.text, turn=m.turn) for m in rows],
    )


async def ai_thread(s: AsyncSession, user, chat_id: uuid.UUID) -> AiThreadDetailOut:
    return await _detail(s, await get_for(s, user.id, chat_id))


async def ai_latest(
    s: AsyncSession, user, project_id: uuid.UUID | None
) -> AiThreadDetailOut | None:
    """GET /ai/threads/latest(맥락 L2). 화면을 옮겨도 이어 갈 대화: 같은 공사(없으면 공사 칸이 빈 대화)에서
    마지막 턴 뒤 24시간 안의 것 하나. 없으면 None(새 대화). 남의 공사는 404."""
    if project_id is not None:
        from app.project import service as project_service

        await project_service.get_for(s, user, project_id)
    chat = await repository.latest_chat(s, user.id, project_id, RESUME_HOURS)
    return await _detail(s, chat) if chat else None


async def faq(ip: str) -> list[AiFaqOut]:
    """GET /ai/faq (로그인 없음). 검증된 카드 파일만 읽는다."""
    from app.knowledge import cards
    from app.shared import ratelimit

    await ratelimit.hit(ratelimit.key("ai-faq", ip), FAQ_PER_MIN, 60, TOO_MANY)
    out = []
    for c in cards.guest_cards(cards.default()):
        out.append(
            AiFaqOut(
                id=c.id,
                question=c.keys[0],
                sentences=[x.text for x in c.answer],
                tip=c.tip.text if c.tip else "",
                sources=[AiSource(ref=x.ref, title=x.title, kind=x.kind) for x in c.sources],
                actions=c.actions,
            )
        )
    return out

"""조사 담당(리서처, docs/v4/09-research.md): 비서가 맡긴 웹 조사를 worker가 Claude 웹 검색 · 가져오기로 돌린다.

- 시작(start): 도구 start_research가 부른다. 비용 상한(사용자 하루 · 새 계정 · 서비스) · 공사당 하루 3번 · 공사마다
  도는 조사 하나를 보고, 대기 줄 + jobs(멈춘 조사 감시) 한 트랜잭션 → commit 뒤 arq 큐에 넣는다. 같은 종류가 돌고
  있으면 새 일 대신 바꾸기 메모로 잇고, 다른 종류면 시작하지 않는다(busy). 승인 카드가 아니다(바뀌는 업무 상태 없음).
- 바꾸기 · 멈추기(change · stop_out): 메모를 붙이거나 멈춤 요청을 남긴다. worker가 API 호출 사이마다 본다.
- worker(run): queued → running → Claude 왕복(서버 도구, pause_turn 잇기, 왕복 4번 · $0.15 · 4분 상한) → 결과 저장 +
  종 알림(dedup_key로 한 번) 한 트랜잭션 → commit 뒤 화면 신호. 대화에는 feed_items가 끝난 조사 줄(한 문장 + 결과
  카드)을 끼운다. 고객이 부탁한 결과라 먼저 말 걸기의 하루 수 · 밤 미룸 규칙 밖이다.
- 링크는 서버 도구 결과 블록의 url만 코드가 뽑는다(weblinks). 막은 곳 · 실행 파일 꼴은 버리고 전화 · 이메일은
  지운다. 요약 · 메모는 SentenceGate와 같은 검사(숫자 · 주소 · 누출 · 한 일처럼 · 표준 대비 %)를 지난 문장만 쓰고,
  다 빠지면 요약 없이 둔다(지어낸 설명 없음). 허용 숫자는 가져온 글 · 검색 결과(제목 · 인용 · 거르기 코드 출력)와
  고객 목표 · 집 조건의 숫자다.
- 상태는 이 파일 한 곳에서 조건부 UPDATE로 바꾸고, 바꿀 때 steps에 기록을 더한다. 글은 로그 · 장부에 남기지 않는다.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.agent import llm
from app.agent.v3 import check
from app.agent.v3.schemas import Sentence
from app.assistant import policy, prompts, weblinks
from app.assistant.models import RESEARCH_LIVE, AssistantResearch
from app.assistant.schemas import AssistantItem, CardOut, CardPart, TextPart
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import SEOUL, now_utc
from app.shared.errors import AppError
from app.v2 import guard

log = logging.getLogger(__name__)

Kind = Literal["outside_vendors", "materials", "general"]
Status = Literal["queued", "running", "done", "failed", "stopped"]
Step = Literal["search", "read", "write"]

KIND_LABEL = {"outside_vendors": "믿집 밖 업체", "materials": "도배 자재", "general": "도배 자료"}
DAY_MAX = 3  # 공사당 하루(서울 날짜) 시작 수
CALL_MAX = 4  # API 왕복(pause_turn 잇기 · 바꾸기 포함)
COST_CAP = 150_000  # 조사 하나 비용 상한(마이크로달러, $0.15). 넘으면 그때까지 찾은 것으로 끝낸다
TIME_CAP = 240.0  # 조사 하나 시간(초, 4분)
CALL_FLOOR = 5.0  # 남은 시간이 이보다 적으면 새로 부르지 않는다
MAX_TOKENS = 6000
WATCH_AFTER = timedelta(minutes=6)  # 이때까지 대기 · 도는 중이면 멈춘 조사로 끝낸다(jobs)
RECENT = timedelta(hours=12)  # 턴 사실 '방금 끝난 조사'를 보여 주는 동안
KEEP = timedelta(days=30)  # 결과를 두는 기간(새 조사를 시작할 때 그 사람의 더 오래된 줄을 지운다)
LINK_MAX = 6
TITLE_MAX = 30
GOAL_MAX = 200
NOTE_MAX = 200
MEMO_MAX = 40
SUMMARY_MAX = 3  # 요약 문장 수
DOC_CHARS = 20_000  # 가져온 글 한 쪽에서 숫자 근거로 읽는 글자 수
FEED_MAX = 10
JOB_KIND = "assistant_research"
JOB_FN = "run_research"  # arq 일 이름(worker.WorkerSettings.functions)

# 웹 도구(claude-api 스킬 · 공식 문서 2026-11-22 확인): _20260209는 동적 거르기(코드 실행 안에서 부름, 따로 code_execution을
# 선언하지 않음). blocked_domains는 하위 도메인까지 막고, 가져오기는 대화에 나온 url만 가져온다.
NO_FETCH = (  # 가져오기만 막는 곳: 플랫폼 글(검색 결과 링크로는 보여도 됨) · robots가 AI 열람을 막은 블로그 · 카페
    "soomgo.com",
    "daangn.com",
    "ohou.se",
    "zipdoc.co.kr",
    "miso.kr",
    "blog.naver.com",
    "cafe.naver.com",
)
SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 4,
    "blocked_domains": list(weblinks.BLOCKED),
}
FETCH_TOOL = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 4,
    "max_content_tokens": 3000,
    "blocked_domains": [*weblinks.BLOCKED, *NO_FETCH],
}
TOOLS = (SEARCH_TOOL, FETCH_TOOL)
WEB_RESULTS = frozenset({"web_search_tool_result", "web_fetch_tool_result"})
# 자재: 제조사 공식 페이지를 먼저(조사 08 카탈로그에서 확인한 곳)
OFFICIAL = (
    "lxzin.com",
    "lxhausys.co.kr",
    "shinhanwall.co.kr",
    "gniwallpaper.com",
    "didwallpaper.com",
)
CHECKS = (  # 믿집 밖 업체를 직접 확인하는 곳(코드 링크)
    ("국세청 홈택스 · 사업자 상태 조회", "https://www.hometax.go.kr"),
    ("KISCON · 건설업 등록 조회", "https://www.kiscon.net"),
)
OUTSIDE_NOTE = (
    "믿집이 확인하지 않은 곳이에요. 사업자 상태 · 등록 업종은 아래에서 직접 확인해 보세요."
)
NO_SUMMARY = "요약을 만들지 못했어요."
ENDED_LINE = {
    "done": "{title} 조사를 마쳤어요.",
    "stopped": "{title} 조사를 멈췄어요.",
    "failed": "{title} 조사를 끝까지 하지 못했어요. 잠시 뒤 다시 부탁해 주세요.",
}
STOPPED_FOUND = " 그때까지 찾은 것만 정리했어요."
DONE_PARTIAL = " 찾은 만큼 정리했어요."
NOTIFY_KIND = "assistant_research"
STEERED = "돌던 조사에 바꾼 조건을 전했어요."
NO_SUCH = "그 낱말이 든 조사가 없어요. 오늘 조사 목록의 제목 낱말로 다시 읽어요."
# 걸리는 시간 말(QA r3 s3 · v1: 실제 16~56초인데 '몇 분 걸려요'). 비서가 고객에게 이 말 그대로 알려요
STARTED = "잠깐(1분 안팎) 걸려요. 끝나면 대화와 알림으로 알려 드려요."
BUSY = "다른 조사가 도는 중이에요. 끝나거나 멈춘 뒤에 새로 할 수 있어요."

# 고객 목표 · 메모에서 떼는 것: 가린 자리 · 동 · 호 · 층 · 번지 숫자 · 주소
_MASKED = re.compile(r"\((?:번호|동호수|이메일|주민번호|계좌) 가림\)")
_UNIT = re.compile(r"(?<![가-힣\d])\d+\s*(?:동|호|번지|층)(?![가-힣])")
# 전화(안심번호 0507 · 지역번호 · 대표번호 1588)도 지운다(check.mask가 못 잡는 꼴)
_PHONE = re.compile(r"(?<!\d)(?:0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}|1[5-9]\d{2}[-.\s]?\d{4})(?!\d)")
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")
_URL_IN = re.compile(r"https?://[^\s)>\]\"'`]+")
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+")
_TITLE_TAIL = re.compile(r"\s+\|{1,2}\s+")  # '이름 | 사이트 소개'의 가름
_HOST_KO = re.compile(r"[a-z0-9.\-가-힣]+")  # 한글 · 영문 소문자 · 숫자만인 도메인
_MARK = re.compile(r"\*\*|__|^#+\s*|`")
_SUMMARY_HEAD = re.compile(r"(?:^|\n)\s*(?:\*\*)?요약(?:\*\*)?\s*[:：]\s*")
SUMMARY_PEEK = 12  # 글 앞 몇 글자로 끝 정리('요약:')인지 본다
_MONEY = re.compile(r"\d[\d,.]*\s*(?:만\s*원|천\s*원|억\s*원|원)|가격|값이|비용이")
_RATING = re.compile(r"평점|별점|후기\s*\d|리뷰\s*\d|\d+\s*위\b|1위|순위|추천")
# 요약 · 메모의 안쪽 사정(QA r3 s3: '도구 사용 한도가 차서 멈췄어요' · '결과를 읽는 코드에 오류가 나서'): 도구 · 검색 횟수
# 상한, 코드 · 프로그램 오류, 도구 이름. 조사 결과는 고객에게 그대로 보여 이런 문장은 뺀다(덜 찾았으면 partial로 보인다)
_INSIDE = re.compile(
    r"(?:도구|검색|가져오기|읽기)[^.!?\n]{0,15}(?:한도|횟수|상한|다\s*(?:써|썼|쓴|쓰))|"
    r"(?:코드|프로그램|스크립트)[^.!?\n]{0,15}(?:오류|에러|실패)|오류가\s*나|에러가\s*나|"
    r"\bAPI\b|max_uses|web_(?:search|fetch)|code_execution"
)
_PYEONG = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*평(?:형)?(?![가-힣]*대)")
_PAGE_AGE = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%Y.%m.%d", "%Y년 %m월 %d일", "%d %B %Y")
_AGO = re.compile(r"^(\d{1,5}) (minute|hour|day|week)s? ago$", re.IGNORECASE)  # 실제 검색 결과 꼴
_AGO_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7}


# ---- 모양 ----


class ResearchLink(BaseModel):
    title: str
    href: str = Field(description="서버 도구 결과 블록의 주소(새 탭으로 엶)")
    source: str = Field(description="출처 도메인")
    memo: str | None = Field(default=None, description="짧은 메모(검사를 지난 글)")
    day: date | None = Field(default=None, description="글 날짜(검색 결과가 알려 줄 때만)")


class ResearchCheck(BaseModel):
    label: str
    href: str


class ResearchData(BaseModel):
    """조사 카드(kind research) · GET /assistant/research/{id}.

    phase progress는 진행 카드(화면이 started_at으로 경과 시간을 세고 몇 초마다 다시 읽음), result는 결과 카드."""

    research_id: uuid.UUID
    phase: Literal["progress", "result"] = "progress"
    kind: Kind
    title: str
    status: Status
    step: Step | None = Field(
        default=None, description="search 찾는 중 · read 자료 읽는 중 · write 정리하는 중"
    )
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    summary: str | None = Field(
        default=None, description="검사를 지난 요약. 없으면 null(요약을 만들지 못함)"
    )
    links: list[ResearchLink] = []
    checks: list[ResearchCheck] = Field(default=[], description="직접 확인하는 곳(믿집 밖 업체)")
    outside: bool = Field(
        default=False, description="믿집 밖 업체: 링크마다 '믿집이 확인하지 않은 곳이에요'"
    )
    partial: bool = Field(default=False, description="상한 · 멈춤으로 그때까지 찾은 것만")
    note: str | None = None


@dataclass
class Started:
    state: Literal["started", "steered", "busy", "limit", "budget", "failed"]
    research: AssistantResearch | None
    message: str


# ---- 글 다듬기 ----


def scrub(text: str | None) -> str:
    """웹 · 고객 글 → 보여 줄 글: 전화 꼴(0507 안심번호 · 대표번호 포함)을 먼저 지우고, 가림(동호수 · 이메일 …)
    자리도 지워 한 줄로."""
    t = _MASKED.sub(" ", check.mask(_PHONE.sub(" ", text or "")))
    return " ".join(t.split()).strip(" -·:|,")


def clean_goal(text: str | None, limit: int = GOAL_MAX) -> str:
    """조사 목표 · 바꾸기 메모 → 가린 글(구 · 동 · 평형 · 도배 조건만): 연락처 · 동호수 · 층 · 주소 · 지시문 꼴을 뗀다."""
    t = policy.mask_in(_PHONE.sub(" ", text or ""))
    t = check.URL.sub(" ", t)
    t = _UNIT.sub(" ", scrub(t))
    return " ".join(t.split())[:limit].strip()


_ITEM_SEP = re.compile(r"[,·/]")


def title_of(goal: str) -> str:
    """카드 · 턴 사실 제목: 목표 앞 30자(낱말 끝에서). 괄호 안에서 잘리면 괄호 안의 끝난 항목까지만 두고 닫는다
    (QA r3 v1 M1: '노원구 32평 아파트 도배 업체 (실크벽지, 벽지' → '… 도배 업체 (실크벽지)'). 끝난 항목이 없으면
    괄호째 뺀다."""
    g = " ".join((goal or "").split())
    if len(g) <= TITLE_MAX:
        return g
    cut = g[:TITLE_MAX]
    if g[TITLE_MAX] != " " and " " in cut:  # 낱말 가운데서 잘렸다: 앞 낱말 끝까지
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(" ,·/")
    open_ = cut.rfind("(")
    if open_ > cut.rfind(")"):  # 열린 괄호 안에서 잘렸다
        inner = cut[open_ + 1 :]
        done = [m.start() for m in _ITEM_SEP.finditer(inner)]  # 구분 기호 앞까지는 끝난 항목
        kept = inner[: done[-1]].strip(" ,·/") if done else ""
        head = cut[:open_].rstrip()
        cut = f"{head} ({kept})" if kept else head
    return cut.strip() or g[:TITLE_MAX]


def fit_pyeong(goal: str, pyeong: object | None) -> str:
    """조사 목표의 평을 집 정보의 공급 평형 그대로로(QA r3 c4b: 전용 59㎡ 집을 모델이 '21평'으로 적음, 집 정보는
    21.4평). 평형대('30평대')는 그대로 둔다. 집 평형을 모르면 그대로."""
    text = pyeong_text(pyeong)
    return _PYEONG.sub(text, goal) if text else goal


def _day_of(page_age: str | None, today: date) -> date | None:
    """검색 결과의 글 날짜. 'April 30, 2025' 같은 날짜 꼴, 또는 '569 days ago'(검색한 날 기준 날 · 주만 셈, 달 · 해는
    날이 하나로 정해지지 않아 모름). 모르면 None."""
    if not page_age:
        return None
    raw = " ".join(str(page_age).split())
    if m := _AGO.match(raw):
        return today - timedelta(days=int(m.group(1)) * _AGO_DAYS[m.group(2).lower()])
    for fmt in _PAGE_AGE:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


# ---- 카드 · 모델 값 ----


def data_of(
    r: AssistantResearch, phase: Literal["progress", "result"] = "progress"
) -> ResearchData:
    res = r.result or {}
    return ResearchData(
        research_id=r.id,
        phase=phase,
        kind=r.kind,  # type: ignore[arg-type]
        title=r.title,
        status=r.status,  # type: ignore[arg-type]
        step=r.step if r.status == "running" else None,  # type: ignore[arg-type]
        created_at=r.created_at,
        started_at=r.started_at,
        ended_at=r.ended_at,
        summary=res.get("summary"),
        links=[ResearchLink.model_validate(x) for x in res.get("links") or []],
        checks=[ResearchCheck.model_validate(x) for x in res.get("checks") or []],
        outside=bool(res.get("outside", r.kind == "outside_vendors")),
        partial=bool(res.get("partial")),
        note=res.get("note"),
    )


def card_of(r: AssistantResearch, phase: Literal["progress", "result"] = "progress") -> CardOut:
    """진행 카드(research-{id}) · 결과 카드(research-{id}-result). card_id가 달라 대화에서 따로 남는다."""
    cid = f"research-{r.id}" + ("-result" if phase == "result" else "")
    return CardOut(card_id=cid, kind="research", data=data_of(r, phase).model_dump(mode="json"))


def ended_line(r: AssistantResearch) -> str:
    """대화에 올리는 정해 둔 한 문장(멈춤은 찾은 게 있으면 그것만 정리했다고, 덜 찾고 마쳤으면 찾은 만큼이라고
    덧붙인다. 안쪽 사정(도구 상한 · 오류)은 말하지 않는다)."""
    res = r.result or {}
    line = ENDED_LINE.get(r.status, ENDED_LINE["done"]).format(title=r.title)
    if r.status == "stopped" and res.get("links"):
        line += STOPPED_FOUND
    elif r.status == "done" and res.get("partial"):
        line += DONE_PARTIAL
    return line


def _elapsed(r: AssistantResearch, now: datetime) -> str:
    """도는 조사의 지난 시간 말: 1분 안이면 '40초째', 넘으면 'n분째'(조사는 보통 1분 안팎이라 '0분째'를 쓰지 않는다)."""
    since = r.started_at or r.created_at
    sec = max(int((now - since).total_seconds()), 0) if since else 0
    return f"{sec}초째" if sec < 60 else f"{sec // 60}분째"


def model_of(r: AssistantResearch | None, now: datetime) -> dict:
    """get_research 도구 결과(policy.to_model을 지남). 웹에서 온 글(요약 · 링크 제목 · 메모)은 자료 상자로만."""
    if r is None:
        return {"state": "none", "message": "이 공사로 맡긴 조사가 없어요."}
    out: dict[str, Any] = {"state": r.status, "title": r.title, "kind": r.kind}
    if r.status in RESEARCH_LIVE:
        out.update(step=r.step, when=_elapsed(r, now))
        return out
    res = r.result or {}
    links = res.get("links") or []
    out.update(found=len(links), partial=bool(res.get("partial")), note=res.get("note"))
    out[policy.DATA_KEY] = {
        "summary": res.get("summary") or NO_SUMMARY,
        "links": [
            {"title": x.get("title"), "source": x.get("source"), "memo": x.get("memo")}
            for x in links
        ],
    }
    out["message"] = "링크 주소는 글에 쓰지 말고 결과 카드를 가리켜요."
    return out


# ---- 읽기 · 권한 ----


async def _owned(s: AsyncSession, user: User, research_id: uuid.UUID) -> AssistantResearch:
    r = await s.scalar(
        select(AssistantResearch)
        .where(AssistantResearch.id == research_id, AssistantResearch.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    if r is None:
        raise AppError(404, "not_found", "조사를 찾을 수 없어요.")
    return r


async def latest(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, kind: Kind | None = None
) -> AssistantResearch | None:
    """이 공사의 가장 최근 조사(kind를 주면 그 종류에서)."""
    q = select(AssistantResearch).where(
        AssistantResearch.user_id == user_id, AssistantResearch.project_id == project_id
    )
    if kind is not None:
        q = q.where(AssistantResearch.kind == kind)
    return await s.scalar(
        q.order_by(AssistantResearch.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


async def outside_lately(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, now: datetime
) -> bool:
    """믿집 밖 업체 조사가 도는 중이거나 오늘(서울 날짜) 이미 맡겼거나 방금(RECENT 안) 끝났다. 가장 최근 조사가 다른
    종류(자재 · 자료)여도 업체 조사만 본다(QA r4 s3: 자재 조사 뒤 '믿집 밖에서 찾아볼까요?'가 다시 나옴)."""
    r = await latest(s, user_id, project_id, "outside_vendors")
    if r is None:
        return False
    return (
        r.status in RESEARCH_LIVE
        or r.created_at >= _day_start(now)
        or (r.ended_at is not None and now - r.ended_at <= RECENT)
    )


async def of_today(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, now: datetime
) -> list[AssistantResearch]:
    """이 공사의 오늘(서울 날짜) 조사, 맡긴 순서대로. 오늘 것이 없으면 가장 최근 하나(어제 맡긴 조사도 읽게)."""
    rows = list(
        (
            await s.scalars(
                select(AssistantResearch)
                .where(
                    AssistantResearch.user_id == user_id,
                    AssistantResearch.project_id == project_id,
                    AssistantResearch.created_at >= _day_start(now),
                )
                .order_by(AssistantResearch.created_at, AssistantResearch.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if rows:
        return rows
    last = await latest(s, user_id, project_id)
    return [last] if last is not None else []


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def note_texts(r: AssistantResearch) -> list[str]:
    """조사에 붙은 바꾸기 메모 글(붙인 순)."""
    return [str(n.get("text") or "") for n in r.notes or [] if isinstance(n, dict)]


def pick(rows: list[AssistantResearch], about: str) -> AssistantResearch | None:
    """목록에서 고를 조사: about(제목 낱말, 예: '용인' · '곰팡이')이 제목 · 목표 · 바꾸기 메모에 든 가장 최근 것,
    about이 비면 가장 최근 것, 맞는 게 없으면 None(QA r4 s3: '성남시 말고 용인시로' 바꾼 조사를 '용인'으로 못 찾음)."""
    if not rows:
        return None
    word = _squash(about)
    if not word:
        return rows[-1]
    hits = [r for r in rows if any(word in _squash(x) for x in (r.title, r.goal, *note_texts(r)))]
    return hits[-1] if hits else None


def list_model(
    rows: list[AssistantResearch], picked: AssistantResearch | None, now: datetime
) -> dict:
    """get_research 도구 결과: 고른 조사 하나의 결과(model_of) + 오늘 조사 목록(제목 · 종류 · 상태, 맡긴 순서).
    예전에는 가장 최근 하나만 읽어 앞 조사를 '다시 열어 볼 수 없어요'라고 했다(QA r3 s3)."""
    out = model_of(picked, now)
    if rows and picked is None:
        out["message"] = NO_SUCH
    if len(rows) > 1 or (rows and picked is None):
        out["items"] = [
            {"title": r.title, "kind": r.kind, "state": r.status, "picked": r is picked}
            for r in rows
        ]
        out["count"] = len(rows)
    return out


async def get_out(user: User, research_id: uuid.UUID) -> ResearchData:
    """GET /assistant/research/{id}: 진행 · 결과(남의 것 · 없는 것 404)."""
    async with SessionLocal() as s:
        r = await _owned(s, user, research_id)
    return data_of(r, "progress" if r.status in RESEARCH_LIVE else "result")


async def facts_line(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, now: datetime
) -> str | None:
    """턴 사실 한 줄: '진행 중인 조사: 제목(n분째)' · '방금 끝난 조사: 제목'(12시간 안, 멈춤 · 못 끝냄은 뒤에 표시)."""
    r = await latest(s, user_id, project_id)
    if r is None:
        return None
    if r.status in RESEARCH_LIVE:
        return f"진행 중인 조사: {r.title}({_elapsed(r, now)})"
    if r.ended_at is not None and now - r.ended_at <= RECENT:
        tail = {"stopped": "(멈춤)", "failed": "(못 끝냄)"}.get(r.status, "")
        return f"방금 끝난 조사: {r.title}{tail}"
    return None


async def feed_items(
    s: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AssistantItem]:
    """대화 기록에 끼울 끝난 조사 줄(끝난 때가 [since, until) 안): 정해 둔 한 문장 + 결과 카드(찾은 게 있으면)."""
    if project_id is None:
        return []
    q = select(AssistantResearch).where(
        AssistantResearch.user_id == user_id,
        AssistantResearch.project_id == project_id,
        AssistantResearch.ended_at.is_not(None),
    )
    if since is not None:
        q = q.where(AssistantResearch.ended_at >= since)
    if until is not None:
        q = q.where(AssistantResearch.ended_at < until)
    rows = await s.scalars(q.order_by(AssistantResearch.ended_at.desc()).limit(FEED_MAX))
    out: list[AssistantItem] = []
    for r in rows.all():
        parts: list = [TextPart(text=ended_line(r), src="guide")]
        res = r.result or {}
        if r.status == "done" or res.get("links"):
            parts.append(CardPart(card=card_of(r, "result")))
        out.append(
            AssistantItem(id=f"r-{r.id}", at=r.ended_at, turn_id=None, parts=parts)  # type: ignore[arg-type]
        )
    return out


# ---- 시작 · 바꾸기 · 멈추기(도구 · API) ----


def _log(event: str, now: datetime, **extra: Any) -> Any:
    """steps에 더할 기록 한 줄(JSONB 배열 하나)."""
    return literal([{"event": event, "at": now.isoformat(), **extra}], JSONB)


def _push(col: Any, item: Any) -> Any:
    return col.op("||", return_type=JSONB)(item)


async def _live(s: AsyncSession, project_id: uuid.UUID) -> AssistantResearch | None:
    return await s.scalar(
        select(AssistantResearch)
        .where(
            AssistantResearch.project_id == project_id,
            AssistantResearch.status.in_(RESEARCH_LIVE),
        )
        .execution_options(populate_existing=True)
    )


async def _steer(s: AsyncSession, r: AssistantResearch, note: str, now: datetime) -> bool:
    """도는 조사에 바꾸기 메모를 붙인다(아직 도는 중일 때만). 메모에 지역 · 조건이 있으면 제목도 바꾼다(steered_title:
    진행 카드 · 턴 사실 · 끝 줄 · 종 알림이 바꾼 조건으로). commit은 부르는 쪽."""
    from sqlalchemy.orm.attributes import set_committed_value

    title = steered_title(r.goal, [*note_texts(r), note], r.kind)
    values: dict[str, Any] = {
        "notes": _push(
            AssistantResearch.notes, literal([{"text": note, "at": now.isoformat()}], JSONB)
        ),
        "steps": _push(AssistantResearch.steps, _log("steer", now)),
    }
    if title != r.title:
        values["title"] = title
    res = await s.execute(
        update(AssistantResearch)
        .where(AssistantResearch.id == r.id, AssistantResearch.status.in_(RESEARCH_LIVE))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    ok = res.rowcount == 1
    # 도구 결과 · 진행 카드가 읽는 값도 새 제목으로(다시 쓰지 않게 저장한 값으로 둔다)
    if ok and title != r.title:
        set_committed_value(r, "title", title)
    return ok


def _day_start(now: datetime) -> datetime:
    d = now.astimezone(SEOUL).date()
    return datetime(d.year, d.month, d.day, tzinfo=SEOUL)


async def start(
    user: User,
    project_id: uuid.UUID,
    kind: Kind,
    goal: str,
    turn_id: uuid.UUID | None,
    now: datetime,
) -> Started:
    """조사를 맡긴다. goal은 clean_goal을 지난 글이다. 돌려주는 state:
    started(새 대기 줄 · 큐) · steered(같은 종류가 돌던 중 → 바꾸기 메모) · busy(다른 종류가 도는 중) ·
    limit(공사당 하루 3번) · budget(비용 상한) · failed(큐에 넣지 못함)."""
    from app.jobs import service as jobs_service
    from app.project import service as project_service

    async with SessionLocal() as s:
        await project_service.get_for(s, user, project_id)  # 남의 공사 404
        live = await _live(s, project_id)
        if live is not None:  # 세션을 닫으면(rollback 없이) 읽은 값은 그대로 남는다
            if live.kind == kind and await _steer(s, live, goal, now):
                await s.commit()
                return Started("steered", live, STEERED)
            return Started("busy", live, BUSY)
        n = await s.scalar(
            select(func.count())
            .select_from(AssistantResearch)
            .where(
                AssistantResearch.project_id == project_id,
                AssistantResearch.created_at >= _day_start(now),
            )
        )
    if int(n or 0) >= DAY_MAX:
        return Started(
            "limit", None, f"오늘은 이 공사로 조사를 {DAY_MAX}번 했어요. 내일 다시 할 수 있어요."
        )
    if not await llm.budget_ok(user.id, "research"):
        return Started("budget", None, "오늘 쓸 수 있는 AI 몫을 다 써서 조사를 시작하지 않았어요.")
    r = AssistantResearch(
        user_id=user.id,
        project_id=project_id,
        turn_id=turn_id,
        kind=kind,
        title=title_of(goal),
        goal=goal,
        status="queued",
        steps=[{"event": "queued", "at": now.isoformat()}],
        created_at=now,
    )
    async with SessionLocal() as s:
        s.add(r)
        try:
            await s.flush()
        except IntegrityError:  # 거의 같은 때 같은 공사에서 시작했다(공사마다 도는 조사 하나)
            await s.rollback()
            live = await _live(s, project_id)
            if live is not None and live.kind == kind and await _steer(s, live, goal, now):
                await s.commit()
                return Started("steered", live, STEERED)
            return Started("busy", live, BUSY)
        await jobs_service.add(
            s,
            kind=JOB_KIND,
            ref_id=r.id,
            run_at=now + WATCH_AFTER,
            dedup_key=f"{JOB_KIND}:{r.id}",
        )
        await s.execute(  # 결과는 30일까지만 둔다(다른 고객에게 다시 쓰지 않는다)
            delete(AssistantResearch).where(
                AssistantResearch.user_id == user.id,
                AssistantResearch.created_at < now - KEEP,
                AssistantResearch.status.not_in(RESEARCH_LIVE),
            )
        )
        await s.commit()
        await s.refresh(r)
    if not await enqueue(r.id):
        async with (
            SessionLocal() as s
        ):  # 큐에 못 넣으면 시작하지 않은 것으로(하루 수 · 대화 줄에 넣지 않음)
            await s.execute(
                delete(AssistantResearch).where(
                    AssistantResearch.id == r.id, AssistantResearch.status == "queued"
                )
            )
            await s.commit()
        return Started("failed", None, "지금은 조사를 시작하지 못했어요. 잠시 뒤 다시 해 주세요.")
    return Started("started", r, STARTED)


async def enqueue(research_id: uuid.UUID) -> bool:
    """arq 큐에 조사 일을 넣는다(같은 조사는 _job_id로 한 번만). Redis가 안 되면 False."""
    from arq.connections import ArqRedis

    try:
        pool = ArqRedis(queue.redis.connection_pool)
        await pool.enqueue_job(JOB_FN, str(research_id), _job_id=f"research:{research_id}")
    except Exception as e:  # noqa: BLE001 - Redis · 큐 오류는 '시작 못 함'으로(종류 이름만 로그)
        log.warning("조사 일을 큐에 넣지 못했어요 (%s)", type(e).__name__)
        return False
    return True


async def change(
    user: User, project_id: uuid.UUID, action: Literal["steer", "stop"], note: str, now: datetime
) -> tuple[str, AssistantResearch | None]:
    """도는 조사를 바꾸거나(steer, 메모) 멈춘다(stop). 돌려주는 state: steered · stopping(다음 왕복 전에 멈춤) ·
    stopped(시작 전이라 바로 멈춤) · none(도는 조사가 없음)."""
    async with SessionLocal() as s:
        live = await _live(s, project_id)
        if live is None or live.user_id != user.id:
            return "none", None
        if action == "steer":
            ok = await _steer(s, live, note, now)
            await s.commit()
            return ("steered" if ok else "none"), live
    return await _stop(live.id, now)


async def stop_out(user: User, research_id: uuid.UUID) -> ResearchData:
    """POST /assistant/research/{id}/stop: 멈춤 요청(시작 전이면 바로 멈춤). 이미 끝났으면 지금 상태 그대로(200)."""
    async with SessionLocal() as s:
        r = await _owned(s, user, research_id)
    if r.status in RESEARCH_LIVE:
        await _stop(r.id, now_utc())
    return await get_out(user, research_id)


async def _stop(research_id: uuid.UUID, now: datetime) -> tuple[str, AssistantResearch | None]:
    """대기면 바로 stopped(끝 처리 · 알림), 도는 중이면 멈춤 요청(worker가 다음 왕복 전에 멈춘다)."""
    async with SessionLocal() as s:
        if await _end(s, research_id, ("queued",), "stopped", {"partial": True}, None, now):
            await s.commit()
            r = await s.get(AssistantResearch, research_id, populate_existing=True)
            if r is not None:
                await _signal(r)
            return "stopped", r
        res = await s.execute(
            update(AssistantResearch)
            .where(
                AssistantResearch.id == research_id,
                AssistantResearch.status == "running",
                AssistantResearch.stop_at.is_(None),
            )
            .values(stop_at=now, steps=_push(AssistantResearch.steps, _log("stop", now)))
            .execution_options(synchronize_session=False)
        )
        await s.commit()
        r = await s.get(AssistantResearch, research_id, populate_existing=True)
    if r is None or r.status not in RESEARCH_LIVE:
        return "none", r
    return ("stopping" if res.rowcount == 1 or r.stop_at is not None else "none"), r


# ---- 끝내기(한 곳) ----


async def _end(
    s: AsyncSession,
    research_id: uuid.UUID,
    from_: tuple[str, ...],
    status: Literal["done", "stopped", "failed"],
    result: dict | None,
    error: str | None,
    now: datetime,
    calls: int | None = None,
    cost: int | None = None,
    notes_used: int | None = None,
) -> bool:
    """조건부로 끝 상태로 바꾸고 같은 트랜잭션에 종 알림(dedup_key로 한 번)을 쓴다. 바꾼 줄이 없으면 False.
    commit · 화면 신호는 부르는 쪽."""
    from app.notify import service as notify_service

    values: dict[str, Any] = {
        "status": status,
        "step": None,
        "ended_at": now,
        "result": result,
        "error_code": error if status == "failed" else None,
        "steps": _push(AssistantResearch.steps, _log(status, now)),
    }
    if calls is not None:  # 모르면(감시 · 시작 전 멈춤) worker가 적어 둔 값을 그대로 둔다
        values["calls"] = min(calls, 20)
    if cost is not None:
        values["cost_micros"] = max(cost, 0)
    if notes_used is not None:
        values["notes_used"] = notes_used
    got = await s.execute(
        update(AssistantResearch)
        .where(AssistantResearch.id == research_id, AssistantResearch.status.in_(from_))
        .values(**values)
        .returning(AssistantResearch.user_id, AssistantResearch.project_id, AssistantResearch.title)
        .execution_options(synchronize_session=False)
    )
    row = got.first()
    if row is None:
        return False
    user_id, project_id, title = row
    body = ENDED_LINE[status].format(title=title).split(". ")[0].rstrip(".")
    await notify_service.add(
        s,
        user_id=user_id,
        kind=NOTIFY_KIND,
        body=body,
        link=f"/projects/{project_id}",
        dedup_key=f"research:{research_id}",
        project_id=project_id,
    )
    return True


async def _signal(r: AssistantResearch) -> None:
    """commit 뒤: 열어 둔 대화가 다시 읽게(state) · 안 읽은 알림 수(notif). 실패해도 일은 끝난 것(로그만)."""
    from app.notify import service as notify_service
    from app.realtime import service as realtime

    try:
        await realtime.push_state([r.user_id], "thread", r.id, r.project_id)
        async with SessionLocal() as s:
            await notify_service.push_unread(s, [r.user_id])
    except Exception as e:  # noqa: BLE001 - 신호는 지워져도 되는 것(화면은 다시 읽어 맞춘다)
        log.warning("조사 끝 신호 실패 (%s)", type(e).__name__)


async def watch(s: AsyncSession, job: Any, now: datetime) -> bool:
    """jobs 처리 함수(시작 + 6분): 아직 대기 · 도는 중이면 멈춘 조사(failed stalled)로 끝낸다. commit은 worker가."""
    from app.jobs.service import AFTER_COMMIT

    if job.ref_id is None:
        return False
    if not await _end(s, job.ref_id, RESEARCH_LIVE, "failed", {"partial": True}, "stalled", now):
        return False
    rid = job.ref_id

    async def later() -> None:
        async with SessionLocal() as s2:
            r = await s2.get(AssistantResearch, rid)
        if r is not None:
            await _signal(r)

    s.info.setdefault(AFTER_COMMIT, []).append(later)
    return True


HANDLERS = {JOB_KIND: watch}


# ---- worker ----


@dataclass
class _Ctl:
    stop: bool
    notes: list[str]


async def _control(research_id: uuid.UUID) -> _Ctl:
    """API 호출 사이: 멈춤 요청 · 바꾸기 메모(지금 DB 값). 못 읽으면 그대로 이어 간다."""
    try:
        async with SessionLocal() as s:
            row = (
                await s.execute(
                    select(AssistantResearch.stop_at, AssistantResearch.notes).where(
                        AssistantResearch.id == research_id
                    )
                )
            ).first()
    except Exception as e:  # noqa: BLE001 - 다음 사이에 다시 본다
        log.warning("조사 멈춤 · 메모 읽기 실패 (%s)", type(e).__name__)
        return _Ctl(False, [])
    if row is None:
        return _Ctl(True, [])
    stop_at, notes = row
    return _Ctl(stop_at is not None, [str(n.get("text") or "") for n in notes or []])


async def _mark(research_id: uuid.UUID, **values: Any) -> None:
    """도는 조사의 칸 몇 개(단계 · 쓴 메모 수)를 바꾼다. 실패해도 조사는 이어 간다(보이는 값일 뿐)."""
    try:
        async with SessionLocal() as s:
            await s.execute(
                update(AssistantResearch)
                .where(AssistantResearch.id == research_id, AssistantResearch.status == "running")
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("조사 진행 기록 실패 (%s)", type(e).__name__)


async def _home_terms(s: AsyncSession, user: User, project_id: uuid.UUID) -> str:
    """검색에 넣을 집 조건(코드 값): 시 · 구 · 동 · 평형 · 벽지. 동호수 · 단지 이름은 넣지 않는다."""
    from app.assistant.tools import cards
    from app.project import service as project_service

    p = await project_service.get_for(s, user, project_id)
    parts = [p.region, p.emd or ""]
    try:
        _, home = await cards.home(s, user, project_id)
    except Exception as e:  # noqa: BLE001 - 평형 · 벽지는 없어도 조사는 한다
        log.warning("조사 집 조건 읽기 실패 (%s)", type(e).__name__)
        home = {}
    pyeong = pyeong_text(home.get("pyeong") or await home_pyeong(s, user, project_id))
    if pyeong:
        parts.append(pyeong)
    if home.get("grade") in cards.GRADE:
        parts.append(cards.GRADE[home["grade"]])
    return " · ".join(x for x in parts if x)


async def home_pyeong(s: AsyncSession, user: User, project_id: uuid.UUID) -> Decimal | None:
    """집 정보의 공급 평형(계산 엔진, 표준견적서 · 집 정보 카드와 같은 값). 셀 수 없으면 None."""
    from app.calc.standard_quote import house_pyeong
    from app.project import service as project_service
    from app.refprice.house import HOUSE_2026H2

    p = await project_service.get_for(s, user, project_id)
    try:
        return house_pyeong(p.size.band, p.size.m2, p.size.basis, HOUSE_2026H2)
    except (ValueError, AttributeError):
        return None


def pyeong_text(pyeong: object | None) -> str | None:
    """평형 → '21.4평'(집 정보 줄과 같은 꼴). 모르면 None."""
    if pyeong is None:
        return None
    try:
        return f"{Decimal(str(pyeong)).normalize():f}평"
    except (InvalidOperation, ValueError):
        return None


@dataclass
class _Run:
    """조사 하나의 왕복 상태(worker 안에서만)."""

    research_id: uuid.UUID
    kind: str
    goal: str
    terms: str
    used: int  # 메시지에 넣은 바꾸기 메모 수
    messages: list[dict]
    blocks: list[tuple[int, dict]] = field(default_factory=list)  # (바꾸기 번째, 응답 블록)
    gen: int = 0
    calls: int = 0
    cost: int = 0
    step: str = "search"
    seen_result: bool = False
    container: str | None = None
    last_stop: str | None = None
    final_text: str | None = None
    reason: str | None = (
        None  # 일찍 끝난 까닭: stop · cost · time · calls · error · budget · off · refusal …
    )


def _steer_text(note: str) -> str:
    return (
        f"고객이 조사 중에 조건을 바꿨어요(고객 말): {note}\n"
        "바꾼 조건으로 이어서 찾고, 끝에는 같은 꼴로 정리해 주세요."
    )


def _first_message(kind: str, goal: str, terms: str, notes: list[str], today: date) -> str:
    """첫 왕복 user 글. 고객이 집과 다른 지역을 찾아 달라고 했으면(믿집 밖 업체) 집 조건에서 집 지역 · 동을 빼고 '찾을
    지역' 줄을 둔다(QA r3 s3: '성남시 말고 용인시로' 조사에 집 조건 성남시가 같이 들어가 성남 · 분당 링크 3/5)."""
    want = target_places(goal, notes)
    home = places(terms)
    other = kind == "outside_vendors" and bool(want) and not (want & home)
    shown = " · ".join(p for p in terms.split(" · ") if not _is_place(p)) if other else terms
    lines = [
        f"조사 종류: {kind}({KIND_LABEL.get(kind, kind)})",
        f"찾을 것(고객 부탁, 가린 글): {goal}",
        f"집 조건: {shown or '모름'}",
    ]
    if other:
        lines.append(
            f"찾을 지역: {' · '.join(sorted(want))}(집과 다른 지역이에요. 이 지역 페이지만 골라 주세요)"
        )
    lines.append(f"오늘: {today.isoformat()}")
    if notes:
        lines.append("바꾼 조건(고객 말): " + " / ".join(notes))
    return "\n".join(lines)


# ---- 지역(믿집 밖 업체 조사: 찾을 지역 · 다른 지역 링크 빼기) ----

_PLACE_SIDO = ("seoul", "gyeonggi", "incheon")  # 업체를 받는 수도권
# 흔한 낱말과 겹치는 줄기는 이름 전체로만 찾아요(동작 · 연수 · 강화 · 고양이 · 이천만 …)
_FULL_ONLY = frozenset(
    {"동작구", "연수구", "남동구", "서해구", "중구", "강화군", "고양시", "광주시", "구리시", "이천시"}
)  # fmt: skip
# 큰 시의 구 · 신도시 이름 → 시(제목에 '분당도배' · '수지 도배'처럼 써요)
_SUB_PLACES = {
    "분당": "성남시", "판교": "성남시", "수정구": "성남시", "중원구": "성남시",
    "수지": "용인시", "기흥": "용인시", "처인": "용인시",
    "영통": "수원시", "장안구": "수원시", "권선": "수원시", "팔달": "수원시",
    "일산": "고양시", "덕양": "고양시", "동탄": "화성시", "평촌": "안양시", "만안": "안양시",
    "산본": "군포시", "상록구": "안산시", "단원구": "안산시",
}  # fmt: skip
_EMD = re.compile(r"^[가-힣0-9]{1,6}[동읍면리]$")


def _place_names() -> dict[str, str]:
    """지역 이름(전체 · 줄기) → 지역 열쇠(서울은 구, 경기 · 인천은 시 · 군 · 구 이름 전체)."""
    from app.shared.regions import SIDO

    out: dict[str, str] = {}
    for sido in _PLACE_SIDO:
        for _group, _pre, names in SIDO[sido][2]:
            for n in names:
                out[n] = n
                if n not in _FULL_ONLY and len(n) >= 3 and n[-1] in "시구군":
                    out.setdefault(n[:-1], n)
    for sub, city in _SUB_PLACES.items():
        out.setdefault(sub, city)
    return out


_PLACES = _place_names()
_PLACE_RE = re.compile("|".join(sorted(map(re.escape, _PLACES), key=len, reverse=True)))


def places(text: str | None) -> set[str]:
    """글에 나온 수도권 지역 열쇠들(긴 이름 먼저: '남양주'는 양주가 아니에요)."""
    return {_PLACES[m.group(0)] for m in _PLACE_RE.finditer(text or "")}


# '성남시 말고 용인시로' · '분당 빼고'의 앞 지역은 찾을 지역이 아니에요
_NOT_HERE = re.compile(
    r"[가-힣0-9]+\s*(?:은|는|이|가)?\s*(?:말고|빼고|아니고|아니라|제외하고|제외)"
)


def target_places(goal: str, notes: list[str] | tuple[str, ...] = ()) -> set[str]:
    """찾을 지역: 가장 최근 바꾸기 메모에 지역이 있으면 그것, 없으면 목표의 지역('…말고' 앞 지역은 뺀다)."""
    for text in [*reversed(list(notes)), goal]:
        got = places(_NOT_HERE.sub(" ", text or ""))
        if got:
            return got
    return set()


# ---- 바꾼 조사의 제목(QA r4 s3: '성남시 말고 용인시로' 바꿔 찾았는데 제목 · 종 알림 · 끝 줄이 '성남시 …') ----

_EMD_WORD = re.compile(r"^[가-힣0-9]{1,6}[동읍면]$")  # 바꾼 지역 바로 뒤의 옛 동
_GRADES = ("실크", "합지")


def _from_notes(notes: list[str], find) -> Any:
    """가장 최근 메모부터 '…말고' 앞 말을 뺀 글에서 find가 찾은 첫 값(없으면 None)."""
    for text in reversed(notes):
        got = find(_NOT_HERE.sub(" ", text or ""))
        if got:
            return got
    return None


def _swap_places(text: str, want: set[str]) -> str:
    """목표 글의 지역 낱말(시 · 구, 바로 뒤 옛 동까지)을 찾을 지역으로 바꿔요. 지역 낱말이 없으면 앞에 붙여요."""
    name = " · ".join(sorted(want))
    out: list[str] = []
    put = after = False
    for w in text.split():
        if after and _EMD_WORD.match(w):
            after = False
            continue
        after = False
        if places(w):
            if not put:
                out.append(name)
                put = True
            after = True
            continue
        out.append(w)
    return " ".join(out) if put else f"{name} {text}"


def _grade_of(text: str) -> str | None:
    got = [g for g in _GRADES if g in text]
    return got[0] if len(got) == 1 else None


def steered_title(goal: str, notes: list[str], kind: str = "outside_vendors") -> str:
    """바꾸기 메모를 반영한 제목: 믿집 밖 업체 조사는 메모에 찾을 지역이 있으면 목표의 지역을 그 지역으로(조사가 찾는
    지역 target_places와 같은 셈, 자재 · 자료 조사는 지역을 보지 않아요: '수지 코팅'), 벽지(실크 · 합지) · 평형을
    바꿨으면 그 말로 바꿔요. 바뀐 것이 없으면 목표 제목(title_of) 그대로예요."""
    text = " ".join((goal or "").split())
    want = _from_notes(notes, places) if kind == "outside_vendors" else None
    if want and want != places(_NOT_HERE.sub(" ", text)):
        text = _swap_places(text, want)
    grade = _from_notes(notes, _grade_of)
    other = next((g for g in _GRADES if g != grade), None) if grade else None
    if grade and other and other in text and grade not in text:
        text = text.replace(other, grade)
    py = _from_notes(notes, lambda t: (m := _PYEONG.search(t)) and m.group(0))
    if py and (m := _PYEONG.search(text)) and abs(_pyeong_num(py) - _pyeong_num(m.group(0))) >= 1:
        text = f"{text[: m.start()]}{py}{text[m.end() :]}"  # 어림('21평' ← 21.4평)은 그대로
    return title_of(text)


def _pyeong_num(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else 0.0


REGION_TEXT = 3000  # 지역을 볼 가져온 글 앞 글자 수


def in_region(hits: list, want: set[str]) -> list:
    """찾을 지역과 겹치지 않는 지역만 나온 페이지를 뺀다(제목 · 가져온 글 앞쪽). 지역이 안 나온 페이지는 둔다."""
    if not want:
        return hits
    out = []
    for h in hits:
        got = places(f"{h.title} {h.text[:REGION_TEXT]}")
        if not got or got & want:
            out.append(h)
    return out


def _is_place(part: str) -> bool:
    """집 조건 한 토막이 지역(시 · 구 · 동)인지."""
    p = part.strip()
    return bool(places(p)) or bool(_EMD.match(p))


def _ends_with_result(content: list[dict]) -> bool:
    """pause_turn 응답이 서버 도구 결과로 끝났는지(그 뒤에는 role:system 글 메시지를 둘 수 있다)."""
    last = content[-1] if content else None
    return bool(last) and str(last.get("type", "")).endswith("_tool_result")


def _final_text(content: list[dict]) -> str:
    """마지막 서버 도구 블록 뒤의 글(끝 정리). 도구 앞 말('찾아볼게요')은 뺀다."""
    tail: list[str] = []
    for b in content:
        if b.get("type") == "text":
            tail.append(str(b.get("text") or ""))
        elif b.get("type") not in ("thinking", "redacted_thinking"):
            tail = []
    return "".join(tail).strip()


async def run(research_id: uuid.UUID) -> str:
    """worker 일 하나: 대기 줄을 도는 중으로 바꾸고 조사해 결과를 저장한다. 돌려주는 값: 끝 상태
    (다른 곳이 이미 가져갔거나 멈췄으면 skipped)."""
    now = now_utc()
    async with SessionLocal() as s:
        got = await s.execute(
            update(AssistantResearch)
            .where(AssistantResearch.id == research_id, AssistantResearch.status == "queued")
            .values(
                status="running",
                started_at=now,
                step="search",
                steps=_push(AssistantResearch.steps, _log("running", now)),
            )
            .returning(
                AssistantResearch.user_id,
                AssistantResearch.project_id,
                AssistantResearch.kind,
                AssistantResearch.goal,
                AssistantResearch.notes,
            )
            .execution_options(synchronize_session=False)
        )
        row = got.first()
        if row is None:
            return "skipped"
        user_id, project_id, kind, goal, stored = row
        await s.commit()
        user = await s.get(User, user_id)
        try:
            terms = await _home_terms(s, user, project_id) if user else ""
        except AppError:
            terms = ""
    notes = [x for x in (clean_goal(n.get("text"), NOTE_MAX) for n in stored or []) if x]
    run_ = _Run(
        research_id=research_id,
        kind=kind,
        goal=goal,
        terms=terms,
        used=len(stored or []),
        messages=[_opening(kind, goal, terms, notes, now)],
    )
    with llm.call_ctx(user_id, None, "research") as cc:
        try:
            await _loop(run_, cc)
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 그때까지 찾은 것으로 끝낸다(종류 이름만 로그)
            log.warning("조사 실패 (%s)", type(e).__name__)
            run_.reason = run_.reason or "error"
        run_.cost = cc.spent_micros
    return await _finish(run_)


def _opening(kind: str, goal: str, terms: str, notes: list[str], now: datetime) -> dict:
    """첫 왕복의 user 메시지(조사 종류 · 목표 · 집 조건 · 오늘 · 시작 전에 온 바꾸기 메모)."""
    text = _first_message(kind, goal, terms, notes, now.astimezone(SEOUL).date())
    return {"role": "user", "content": [{"type": "text", "text": text}]}


async def _loop(run_: _Run, cc: llm.CallCtx) -> None:
    t0 = time.monotonic()
    system = prompts.text("researcher")

    # 진행 단계(QA r3 s3: 도구 사이 짧은 글이 '정리하는 중'을 찍고 다시 '찾는 중'으로 돌아갔다): 찾는 중 · 자료 읽는 중은
    # 웹 도구 부름으로, 정리하는 중은 웹 결과를 본 뒤 끝 정리('요약:'으로 시작하는 글)가 시작될 때만 찍는다
    head = {"text": "", "armed": False}

    async def mark(step: str) -> None:
        if step != run_.step:
            run_.step = step
            await _mark(
                run_.research_id,
                step=step,
                steps=_push(AssistantResearch.steps, _log("step", now_utc(), step=step)),
            )

    async def on_block(kind: str, name: str | None) -> None:
        head["armed"] = False
        if kind in WEB_RESULTS:
            run_.seen_result = True
        elif kind == "text":
            head.update(text="", armed=run_.seen_result)
        elif kind == "server_tool_use":
            step = {"web_search": "search", "web_fetch": "read"}.get(name or "")
            if step:
                await mark(step)

    async def on_text(t: str) -> None:
        if not head["armed"]:
            return
        head["text"] += t
        if _SUMMARY_HEAD.match(head["text"].lstrip()):
            head["armed"] = False
            await mark("write")
        elif len(head["text"].strip()) >= SUMMARY_PEEK:
            head["armed"] = False  # 끝 정리가 아닌 글(도구 사이 말)

    while True:
        ctl = await _control(run_.research_id)
        if ctl.stop:
            run_.reason = "stop"
            return
        fresh = [clean_goal(n, NOTE_MAX) for n in ctl.notes[run_.used :]]
        fresh = [n for n in fresh if n]
        steered = False
        if fresh and run_.last_stop is None:  # 첫 왕복 전에 온 메모: 첫 메시지에 넣는다
            all_notes = [x for x in (clean_goal(n, NOTE_MAX) for n in ctl.notes) if x]
            run_.messages[0] = _opening(run_.kind, run_.goal, run_.terms, all_notes, now_utc())
            run_.used = len(ctl.notes)
            await _mark(run_.research_id, notes_used=run_.used)
        elif fresh:
            text = _steer_text(" / ".join(fresh))
            if run_.last_stop == "pause_turn":
                last = run_.messages[-1]["content"] if run_.messages else []
                if _ends_with_result(
                    last
                ):  # 멈춘 턴이 도구 결과로 끝남: 글 system 메시지를 둘 수 있다
                    run_.messages.append({"role": "system", "content": text})
                    steered = True
            else:
                run_.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
                steered = True
            if steered:
                run_.used = len(ctl.notes)
                run_.gen += 1
                await _mark(run_.research_id, notes_used=run_.used)
        if run_.last_stop == "end_turn" and not steered:
            return
        if run_.calls >= CALL_MAX:
            run_.reason = "calls"
            return
        run_.cost = cc.spent_micros
        if run_.cost >= COST_CAP:
            run_.reason = "cost"
            return
        left = TIME_CAP - (time.monotonic() - t0)
        if left <= CALL_FLOOR:
            run_.reason = "time"
            return
        try:
            reply = await asyncio.wait_for(
                llm.claude_stream(
                    system,
                    run_.messages,
                    tools=TOOLS,
                    purpose="research",
                    max_tokens=MAX_TOKENS,
                    container=run_.container,
                    on_block=on_block,
                    on_text=on_text,
                ),
                timeout=left,
            )
        except TimeoutError:
            run_.calls += 1
            run_.reason = "time"
            return
        except llm.OverBudget:
            run_.reason = "budget"
            return
        except llm.LLMOff:
            run_.reason = "off"
            return
        except llm.LLMError:
            run_.calls += 1
            run_.reason = "error"
            return
        run_.calls += 1
        run_.cost = cc.spent_micros
        run_.container = reply.container or run_.container
        run_.blocks.extend((run_.gen, b) for b in reply.content)
        if reply.stop == "refusal":
            run_.reason = "refusal"
            return
        run_.messages.append({"role": "assistant", "content": reply.content})
        run_.last_stop = reply.stop
        if reply.stop == "end_turn":
            run_.final_text = _final_text(reply.content) or None
        elif reply.stop != "pause_turn":  # max_tokens · 모르는 멈춤: 그때까지 찾은 것으로
            run_.reason = reply.stop
            return
        await _mark(run_.research_id, calls=min(run_.calls, 20), cost_micros=run_.cost)


# ---- 결과(코드가 만든다) ----


def _source_text(blocks: list[dict], extra: list[str]) -> str:
    """요약 · 메모 숫자 근거: 가져온 글 · 검색 결과 제목 · 날짜 · 인용 · 거르기 코드 출력 + 고객 목표 · 집 조건."""
    out = list(extra)
    for h in weblinks.hits(blocks, ()):
        out.extend([h.title, h.page_age or "", h.text[:DOC_CHARS]])
    for b in blocks:
        t = b.get("type")
        if t == "text":
            out.extend(str(c.get("cited_text") or "") for c in b.get("citations") or [])
        elif t in ("code_execution_tool_result", "bash_code_execution_tool_result"):
            c = b.get("content")
            if isinstance(c, dict) and c.get("stdout"):
                out.append(str(c["stdout"])[:DOC_CHARS])
    return "\n".join(x for x in out if x)


def gate(text: str, allowed: set[float], prompt: str, kind: str) -> str | None:
    """요약 · 메모 문장 하나: SentenceGate와 같은 검사(숫자 · 주소 · 누출 · 한 일처럼 · 표준 대비 %) + 연락처가 든 문장
    빼기 + 종류별(믿집 밖 업체: 값 · 평점 · 순위 · 추천, 자재: 값). 못 넘으면 None."""
    from app.assistant import runtime  # 늦게: runtime → tools → 조사 도구 → 이 파일 순환을 피한다

    t = _MARK.sub("", _BULLET.sub("", text)).strip()
    if not t or _INSIDE.search(t):  # 안쪽 사정(도구 상한 · 코드 오류)은 고객 쪽 말이 아니다(결정 3)
        return None
    if check.mask(t) != t or _PHONE.search(t):
        return None
    ok, _why = check.sentence_ok(Sentence(text=t), allowed, None, None, prompt)
    if ok is None or runtime.claims_done(ok.text) or policy.VS_STANDARD.search(ok.text):
        return None
    if kind == "outside_vendors" and (_MONEY.search(ok.text) or _RATING.search(ok.text)):
        return None
    if kind == "materials" and _MONEY.search(ok.text):
        return None
    return ok.text


def _summary(final_text: str | None, allowed: set[float], prompt: str, kind: str) -> str | None:
    if not final_text:
        return None
    body = final_text
    m = _SUMMARY_HEAD.search(body)
    if m:
        body = body[m.end() :]
    lines = []
    for line in body.split("\n"):
        if _BULLET.match(line) and _URL_IN.search(line):  # 메모 줄부터는 요약이 아니다
            break
        lines.append(line)
    kept: list[str] = []
    for sent in _SENT.split("\n".join(lines)):
        ok = gate(sent, allowed, prompt, kind) if sent.strip() else None
        if ok and ok not in kept:
            kept.append(ok)
        if len(kept) == SUMMARY_MAX:
            break
    return " ".join(kept) or None


def _memos(final_text: str | None, allowed: set[float], prompt: str, kind: str) -> dict[str, str]:
    """'- 주소 : 메모' 줄 → {주소 열쇠: 메모}. 주소는 결과 블록 링크와 맞추는 열쇠로만 쓴다(그 주소를 보이지 않는다)."""
    if not final_text or kind == "outside_vendors":
        return {}
    out: dict[str, str] = {}
    for line in final_text.split("\n"):
        m = _URL_IN.search(line)
        if not m or not _BULLET.match(line):
            continue
        url = m.group(0).rstrip(".,;:")
        # 메모는 주소 뒤 글(없으면 앞 글). 마크다운 링크 괄호 · 구분 기호는 뗀다
        after = line[m.end() :].lstrip(")>]").strip(" -–—:|·")
        before = _BULLET.sub("", line[: m.start()]).replace("](", " ").strip(" -–—:|·[(<")
        memo = after or before
        ok = gate(memo, allowed, prompt, kind) if memo else None
        if ok:
            short = ok if len(ok) <= MEMO_MAX else ok[: MEMO_MAX - 1] + "…"
            out.setdefault(weblinks.key(url), short)
    return out


def _picked(final_text: str | None) -> set[str]:
    """끝 글 '- 주소 : 메모' 줄의 주소 열쇠. 결과 블록 링크를 고르는 데만 쓴다(그 주소를 보이지 않는다)."""
    out: set[str] = set()
    for line in (final_text or "").split("\n"):
        m = _URL_IN.search(line)
        if m and _BULLET.match(line):
            out.add(weblinks.key(m.group(0).rstrip(".,;:")))
    return out


def _title(raw: str, host: str) -> str:
    """페이지 제목: '이름 | 사이트 소개' 꼴이면 앞 이름만(광고 · 순위 문구를 뺀다), 가림 · 80자."""
    head = _TITLE_TAIL.split(raw, 1)[0]
    return scrub(head if len(head.strip()) > 4 else raw)[:80] or host


def _source(host: str) -> str:
    """보여 줄 출처 도메인: 한글 도메인(xn--)은 한글로 풀고, 다른 글자가 섞이면(흉내 주소) 그대로 둔다."""
    try:
        shown = host.encode("ascii").decode("idna")
    except UnicodeError:
        return host
    return shown if shown != host and _HOST_KO.fullmatch(shown) else host


def _order(kind: str, hits: list[weblinks.Hit]) -> list[weblinks.Hit]:
    """믿집 밖 업체는 검색 결과 순서 그대로(순위 없음), 자재는 제조사 공식 먼저, 일반은 공공 · 읽은 페이지 먼저."""
    if kind == "outside_vendors":
        return hits

    def rank(h: weblinks.Hit) -> int:
        if weblinks.blocked(h.host, OFFICIAL) or h.host.endswith(".go.kr"):
            return 0
        return 1 if h.fetched else 2

    return sorted(hits, key=rank)  # 같은 자리끼리는 나온 순서(sorted는 안정)


def build_result(run_: _Run, notes: list[str], prompt: str, today: date) -> dict:
    """결과 JSON(research.result): 요약 · 링크 6개 · 확인하는 곳 · 표시. 링크는 서버 도구 결과 블록에서만.

    끝 글 메모 줄에 적힌 결과 블록 링크가 있으면 그것만(모델이 읽고 고른 곳, 지역이 다른 검색 결과를 뺀다),
    없으면 바꾼 조건 뒤 결과 · 모든 결과 순. 순서는 _order(고른 것도 검색 결과 순서 그대로)."""
    blocks = [b for _, b in run_.blocks]
    newest = [b for g, b in run_.blocks if g == run_.gen]  # 바꾼 조건 뒤에 찾은 것을 먼저 본다
    allowed = guard.numbers(_source_text(blocks, [run_.goal, run_.terms, *notes]))
    every = weblinks.hits(blocks)
    dead = {weblinks.key(h.url) for h in every if h.dead}  # 열리지 않는 · 닫힌 페이지
    picked = _picked(run_.final_text)
    chosen = [h for h in every if weblinks.key(h.url) in picked]
    hits = chosen or weblinks.hits(newest) or every
    hits = [h for h in hits if weblinks.key(h.url) not in dead]
    # 믿집 밖 업체: 찾을 지역(바꾼 조건 · 목표, 없으면 집 지역)과 다른 지역만 나온 링크는 뺀다
    if run_.kind == "outside_vendors":
        hits = in_region(hits, target_places(run_.goal, notes) or places(run_.terms))
    memos = _memos(run_.final_text, allowed, prompt, run_.kind)
    links: list[dict] = []
    for h in _order(run_.kind, hits):
        links.append(
            ResearchLink(
                title=_title(h.title, h.host),
                href=h.url,
                source=_source(h.host),
                memo=memos.get(weblinks.key(h.url)),
                day=_day_of(h.page_age, today),
            ).model_dump(mode="json")
        )
        if len(links) == LINK_MAX:
            break
    outside = run_.kind == "outside_vendors"
    # 찾은 만큼(결정 3): 상한 · 멈춤으로 일찍 끝났거나, 웹 도구 상한까지 다 썼거나(max_uses_exceeded) 결과를 거르는
    # 코드가 실패한 조사는 '그때까지 찾은 것만'으로 보인다(QA r3 s3: 요약이 '도구 한도' · '코드 오류'를 말함)
    short = "max_uses_exceeded" in weblinks.tool_errors(blocks) or weblinks.code_failed(blocks)
    return {
        "summary": _summary(run_.final_text, allowed, prompt, run_.kind),
        "links": links,
        "checks": [{"label": a, "href": b} for a, b in CHECKS] if outside else [],
        "outside": outside,
        "partial": run_.reason is not None or short,
        "note": OUTSIDE_NOTE if outside else None,
    }


async def _finish(run_: _Run) -> str:
    """끝 상태 · 결과 저장 + 종 알림(한 트랜잭션) → commit 뒤 화면 신호."""
    prompt = prompts.text("researcher")
    if run_.step != "write":
        await _mark(
            run_.research_id,
            step="write",
            steps=_push(AssistantResearch.steps, _log("step", now_utc(), step="write")),
        )
    ctl = await _control(run_.research_id)
    try:
        result = build_result(run_, ctl.notes, prompt, now_utc().astimezone(SEOUL).date())
    except Exception as e:  # noqa: BLE001 - 결과를 못 만들면 실패로 끝낸다(지어내지 않음)
        log.warning("조사 결과 만들기 실패 (%s)", type(e).__name__)
        result = None
    found = bool(result and result["links"])
    if run_.reason == "stop":
        status, error = "stopped", None
    elif result is None or (run_.reason in ("error", "budget", "off", "refusal") and not found):
        status, error = "failed", (run_.reason or "result")[:40]
    else:
        status, error = "done", None
    async with SessionLocal() as s:
        ok = await _end(
            s,
            run_.research_id,
            ("running",),
            status,  # type: ignore[arg-type]
            result,
            error,
            now_utc(),
            run_.calls,
            run_.cost,
            notes_used=run_.used,
        )
        await s.commit()
        r = await s.get(AssistantResearch, run_.research_id, populate_existing=True)
    if not ok:
        return "skipped"  # 그사이 감시가 멈춘 조사로 닫았다
    if r is not None:
        await _signal(r)
    return status


async def run_job(ctx: dict, research_id: str) -> str:
    """arq 일(worker.WorkerSettings.functions, 이름 JOB_FN). 같은 조사는 _job_id로 한 번만 들어온다."""
    return await run(uuid.UUID(research_id))


def dump(value: Any) -> str:
    """시험 · 보고용: 결과를 글로(로그에는 쓰지 않는다)."""
    return json.dumps(value, ensure_ascii=False, default=str)

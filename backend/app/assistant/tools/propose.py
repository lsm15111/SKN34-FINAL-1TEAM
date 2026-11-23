"""제안 도구 (계약서 5장): 대기 행동 행만 만든다. 실행은 사람이 승인 카드를 눌러야 actions.execute가 한다.

- 대상은 ref로만 받고 코드가 id로 푼다(모르는 ref는 unknown_ref). 금액 · 날짜 · 판은 기능 service 값이다.
- 제안할 수 없는 상태(잠김 · 견적서 없음 · 겹침 …)는 도구 오류로 돌려준다(행을 만들지 않음).
- 같은 대상의 열린 제안은 하나(서로 바꾸는 묶음, actions.swap_kinds): 새로 만들면 옛 것은 만료(replaced)되고 그
  action 이벤트도 보낸다. 같은 제안이 열려 있으면 그 행을 쓰고(state same), 고객이 거절한 같은 제안이면 오류 대신 모델
  값으로 알린다(state rejected). 단, 사람이 이번 턴에 분명히 해 달라고 했으면(asks_again) 새 결정으로 보고 만든다.
- 승인 카드 글의 날짜는 한국어 글이다: 비서도 읽는 제목 · 오류 글은 긴 꼴(cards.md_long · long_range, 문장 숫자
  검사가 월 · 일을 보게), 요약 줄 · 판 글은 짧은 꼴(md_week · md_range). payload(실행할 값)는 ISO 날짜 그대로다.
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.assistant import actions
from app.assistant.schemas import (
    ActionSummary,
    AmountRow,
    CardOut,
    DiffOut,
    LinkOut,
    SummaryRow,
)
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards, obj, tool
from app.assistant.tools.customer import TRADE, dobae_only, pid_of, region_of
from app.calc import visit_view
from app.db import SessionLocal
from app.project import diy as project_diy
from app.project.diy import DIY as DIY_LABELS
from app.project.diy import DiyKey
from app.shared.clock import SEOUL
from app.shared.errors import AppError
from app.shared.korean import euro

REF = {"type": "string", "description": "도구 결과에 나온 이름표"}
HALF = {"am": "오전", "pm": "오후"}
FIELD_LABEL = {
    "sgg": "지역",
    "area_m2": "면적(㎡)",
    "area_basis": "면적 기준",
    "occupied": "사는 중",
    "grade": "벽지",
    "rooms": "방 개수",
    "start_date": "공사 시작 희망",
    "demolition": "철거 범위",
    "diy": "직접 할 일",
}
# 제안 결과(state) → 모델에 줄 한 줄(고객에게 할 말의 근거). 거절은 오류가 아니라 값으로 알린다
OFFER_NOTE = {
    "new": "승인 카드를 만들었어요. 사람이 카드 버튼을 눌러야 실행돼요.",
    "same": "같은 승인 카드가 이미 열려 있어요(새로 만들지 않았어요). 그 카드를 확인하고 눌러 달라고 안내해요.",
}
CLOSED_NOTE = "이미 닫힌 제안이에요(새로 만들지 않았어요)."
REPLACED_NOTE = (
    "앞에 열려 있던 '{titles}' 카드는 닫고 이 카드로 바꿨어요(그 카드는 거둘 것이 없어요)."
)


def summary_rows(sm: ActionSummary) -> list[dict]:
    """승인 카드 요약 → 모델 값 줄: 칸(이름 · 값 · 덧말) · 업체별 금액 · 합계 금액 · 차액(계산 엔진 값 그대로)."""
    rows: list[dict] = [
        {"label": r.label, "value": r.value, **({"sub": r.sub} if r.sub else {})} for r in sm.rows
    ]
    if sm.version:  # 어느 판(견적서 2판 · 공정표 3판)인지: 카드에 보이는 그대로
        rows.insert(0, {"label": "판", "value": sm.version})
    rows += [{"label": x.label, "won": x.won} for x in sm.amounts]
    if sm.amount_won is not None:
        rows.append({"label": "금액", "won": sm.amount_won})
    if sm.diff is not None:  # 카드 위 차액 칸(부가세 포함): 승인하면 이 금액이 이렇게 바뀌어요
        d = sm.diff
        rows.append({"label": f"{d.label}(지금)", "won": d.from_won})
        rows.append({"label": f"{d.label}(승인 뒤)", "won": d.to_won, "diff_won": d.diff_won})
    return rows


# 이번 턴에 사람이 분명히 해 달라고 한 말: 하는 말(저장 · 바꿔 · 요청 · 수락 …) 뒤에 부탁 · 다짐 끝말(주세요 · 줘 ·
# 부탁 · 할게요 …), 또는 '…로 해 주세요'. 하지 말라는 말은 빼요. 거절한 제안을 다시 만들 새 결정으로 본다
ASK_DO = re.compile(
    r"(?:저장|바꿔|바꾸어|변경|수정|고쳐|반영|적용|넣어|빼|만들어|요청|보내|수락|확정|진행|미뤄|당겨|옮겨|골라|"
    r"잡아|승인|거절|답해|올려|취소|그걸로|그것으로|이걸로|이것으로|그대로|그렇게|직접)"
    r"\S{0,3}\s{0,2}(?:좀\s{0,2})?(?:해\s{0,2})?"
    r"(?:주세요|주십시오|주실래요|주시겠어요|주실\s{0,2}수\s{0,2}있|줘요|줘|주라|줄래요|줄래|부탁|할게요|할께요|"
    r"할래요|하겠습니다)"
    r"|로\s{0,2}(?:해|바꿔)\s{0,2}(?:주세요|주십시오|주실래요|주시겠어요|줘요|줘|주라|줄래요|줄래)"
)
NOT_DO = re.compile(
    r"(?:하|되)?지\s{0,2}(?:마|말)|안\s{0,2}(?:해도|하셔도)|필요\s{0,2}없|그만\s{0,2}(?:해|두)"
)


def asks_again(text: str) -> bool:
    """사람이 이번 턴 말로 분명히 해 달라고 했는지('32평 맞아요. 저장해 주세요'). 거절 막기는 먼저 말 걸기 · 비서가
    스스로 낸 제안에만 걸고, 이렇게 새로 부탁한 턴에는 거절한 같은 제안도 다시 만든다(계약서 '거절한 것을 다시 밀지
    않는다'의 예외: 사람이 새로 정함)."""
    t = text or ""
    return bool(ASK_DO.search(t)) and not NOT_DO.search(t)


def rejected_note(surface: str) -> str:
    who = "고객이" if surface == "customer" else "업체가"
    return (
        f"{who} 거절한 제안이에요. 판 · 금액 · 날짜가 바뀌지 않아 다시 만들지 않았어요. 다시 원하면 카드 단추로 직접 "
        "고르거나 해 달라고 분명히 말해 달라고 안내해요(그렇게 말한 턴에는 새로 만들어요)."
    )


def _show(key: str, v) -> str:
    from app.calc.dobae import DEMOLITION

    if v is None:
        return "없음"
    if key == "start_date":  # 집 카드 사실과 같은 꼴 '12월 15일(화)'(ISO 날짜 아님)
        return cards.md_long(date.fromisoformat(str(v)))
    if key == "area_basis":
        return cards.BASIS.get(v, v)
    if key == "grade":
        return cards.GRADE.get(v, v)
    if key == "occupied":
        return "살면서 공사" if v else "빈 집"
    if key == "demolition":
        return DEMOLITION.get(v, v)
    if key == "diy":
        from app.project.diy import DIY

        return " · ".join(DIY.get(k, k) for k in v) or "없어요"
    return str(v)


async def _offer(tc: ToolCtx, **kw) -> tuple[ToolOut, dict]:
    """행동 행을 만들고 commit한다. (도구 결과, 모델용 요약). 새 행 · 열린 같은 행만 승인 카드(action)로 보내고,
    거절한 같은 제안 · 닫힌 행은 보내지 않는다(모델 값 state · note로만 알림). 사람이 새로 정한 제안(카드 단추 ·
    LLM 턴에서 분명히 해 달라고 한 말)은 거절한 같은 제안도 다시 만든다. 무료 모드는 낱말 규칙이 말을 잘못 읽을 수
    있어 말로는 다시 만들지 않는다."""
    fresh = tc.pressed or (tc.mode == "llm" and asks_again(tc.text))
    async with SessionLocal() as s:
        got = await actions.offer(
            s,
            tc.user,
            surface=tc.surface,
            now=tc.now,
            turn_id=tc.turn_id,
            pressed=fresh,
            **kw,
        )
        await s.commit()
    a = actions.out(got.row)
    state = got.state if got.live or got.state == "rejected" else "closed"
    note = rejected_note(tc.surface) if state == "rejected" else OFFER_NOTE.get(state, CLOSED_NOTE)
    model: dict = {
        "proposed": got.live,
        "state": state,
        "kind": a.kind,
        "summary": {"title": a.summary.title, "approve_label": a.summary.approve_label},
        "note": note,
    }
    if got.live:
        model["expires_at"] = cards.seoul_text(a.expires_at)  # 서울 시각 글(UTC를 그대로 읽지 않게)
        # 카드에 보이는 줄(직접 할 일 · 지역 · 날짜 · 금액): 모델이 카드와 다른 목록을 말하지 않게(QA r3 s6 B1)
        model["summary"]["rows"] = summary_rows(a.summary)
    # 같은 대상의 열린 카드를 새 카드로 바꿔 닫았다(QA r3 s4: 이미 닫힌 카드를 '거둘까요?'라고 물음)
    if got.closed:
        titles = [title_of(c) for c in got.closed]
        model["replaced"] = titles
        model["note"] = f"{note} {REPLACED_NOTE.format(titles=' · '.join(titles))}"
    out = ToolOut(
        data=model,
        actions=[a] if got.live else [],
        closed=[actions.out(c) for c in got.closed],
    )
    return out, model


# ---- 고객 ----


class HomeFields(BaseModel):
    sgg: str | None = Field(default=None, max_length=30)  # 지역 바꾸기: '노원구' · '부산 중구'
    area_m2: Decimal | None = Field(default=None, gt=10, lt=400, decimal_places=1)
    area_basis: Literal["supply", "exclusive"] | None = None
    pyeong: Decimal | None = Field(default=None, gt=3, lt=121, decimal_places=1)  # 공급 기준 평형
    occupied: bool | None = None
    grade: Literal["economy", "basic"] | None = None
    rooms: int | None = Field(default=None, ge=1, le=5)
    start_date: date | None = None
    demolition: Literal["full", "partial", "none"] | None = None  # 모은 조건(집 정보 칸 아님)
    diy: list[DiyKey] | None = Field(
        default=None, max_length=len(DIY_LABELS)
    )  # 직접 할 일(모은 조건, 바꾼 뒤 전체 목록)


class HomeIn(BaseModel):
    fields: HomeFields


REQUESTED = "실측을 요청한 업체"
CHOSEN = "확정한 업체"


async def chosen_names(s, pid: uuid.UUID) -> set[str]:
    """이 공사에서 확정한 업체 이름(실측 요청 상태 chosen, 읽기 조인)."""
    from sqlalchemy import select

    from app.visit.models import Visit

    rows = await s.scalars(
        select(Visit.vendor_name).where(Visit.project_id == pid, Visit.status == "chosen")
    )
    return set(rows.all())


def told_whom(names: list[str], chosen: set[str]) -> str:
    """직접 할 일 사본을 고쳐 알리는 업체를 부르는 말: 모두 확정한 업체면 '확정한 업체', 아니면 '실측을 요청한 업체'
    (QA r4 c2: 확정 뒤 직접 할 일 승인 카드의 메모 · 결과가 '실측을 요청한 업체')."""
    return CHOSEN if names and set(names) <= chosen else REQUESTED


def home_note(
    changes: dict,
    locked: bool,
    before: list[str] | None = None,
    *,
    live: bool = False,
    dealt: bool = False,
    who: str = REQUESTED,
    moved: bool | None = None,
) -> str:
    """집 정보 승인 카드 메모: 바뀌는 것에 맞춰요. 직접 할 일만 바꾸면 표준견적서는 그대로예요(실행은 칩 저장만).
    벽지 직접 구매(paper_buy)를 켜거나 끄면 표준견적서 도배지 줄이 고객 구매로 빠지거나 돌아와요(before: 지금 칩).
    실측을 요청한 뒤면 확정 전 요청 · 공사 시작 전 확정(live, who: 그 업체를 부르는 말 told_whom)의 '업체에 알릴 것'도
    같이 고쳐 업체에 알리고(visit.flow.sync_diy), 공사가 시작된 확정 업체(dealt)에는 채팅으로 따로 알려야 해요(QA r2 c2).
    moved는 저장 전에 계산 엔진으로 견준 표준견적서 합계가 달라지는지예요(False면 '금액은 그대로', 모르면 None).
    공사 시작 희망일을 바꾸면 예상 공정표 날짜가 바뀐다고 적어요(QA r6 c2: 날짜 · 부분 철거만 바꿔도 '새로 계산해요')."""
    from app.calc.dobae import DEMOLITION_KEY

    if set(changes) == {"diy"}:
        buy = project_diy.PAPER_BUY in changes["diy"]
        paper = buy != (project_diy.PAPER_BUY in (before or ()))
        std = "표준견적서는 그대로예요"
        if paper:
            std = (
                "표준견적서에서 벽지 값을 빼요(고객 구매)"
                if buy
                else "표준견적서에 벽지 값을 다시 넣어요"
            )
        tell = [
            *([f"{who}에도 바뀐 직접 할 일을 알려요"] if locked and live else []),
            *(["확정한 업체에는 채팅으로 따로 알려 주세요"] if locked and dealt else []),
        ]
        said = [std] if paper or not tell else []
        return ". ".join(["저장하면 공정표에 직접 할 일 날짜가 들어가요", *said, *tell])
    if moved is False:
        std = "표준견적서 금액은 그대로예요"
    elif changes.get(DEMOLITION_KEY) == "full":
        std = "표준견적서를 리모델링 기준으로 새로 계산해요"
    else:
        std = "표준견적서를 새로 계산해요"
    parts = [
        *(["예상 공정표 날짜가 바뀌어요"] if "start_date" in changes else []),
        std,
        # 지역 바꾸기(QA r3 s1): 업체 추천 · 실측 요청이 그 지역으로
        *(
            ["업체 추천도 바뀐 지역 업체로 바뀌어요"]
            if "sgg" in changes or "sido" in changes
            else []
        ),
    ]
    return "저장하면 " + ". ".join(parts)


def standard_change(p, said: dict, changes: dict, merged) -> tuple[int, int] | None:
    """집 정보 승인 카드 미리 보기: (지금, 바꾼 뒤) 표준견적서 합계(부가세 포함, 계산 엔진, 저장 안 함). 바꾼 뒤는 집
    정보(merged, 없으면 그대로) · 철거 범위 · 직접 할 일 칩을 넣어 다시 세요. 셀 수 없으면 None."""
    from app.calc.dobae import DEMOLITION_KEY
    from app.project import service as project_service
    from app.quote import service as quote_service

    after = dict(said)
    if DEMOLITION_KEY in changes:
        after[DEMOLITION_KEY] = changes[DEMOLITION_KEY]
    if "diy" in changes:
        after = project_diy.with_chips(after, changes["diy"])
    home = project_service.preview_home(p, merged) if merged is not None else p
    try:
        return quote_service.preview_total(p, said), quote_service.preview_total(home, after)
    except (ValueError, KeyError):
        return None


NEED_BASIS = (
    "면적(㎡)을 바꿀 때는 기준(area_basis: supply 공급 · exclusive 전용)을 같이 넣어요. "
    "계약서 · 등기 · 'nn 타입'의 ㎡는 전용, 평형은 pyeong에 넣어요."
)
# 잠긴 집 정보(실측 요청 뒤)를 고치려 할 때 까닭: 보낸 요청이 모두 끝나고 견적서가 없으면 잠금이 풀린다
# (visit.service.unlock_if_idle, 리드 결정 11-22). 견적서가 온 뒤에는 취소로도 풀리지 않는다
LOCKED_QUOTED = "업체 견적서가 온 뒤라 집 정보를 고칠 수 없어요."
LOCKED_LIVE = "실측 요청이 진행 중이라 집 정보를 고칠 수 없어요. 보낸 요청을 모두 취소하면 다시 고칠 수 있어요."
# 바뀐 조건을 업체에 알리기만 하려면 요청을 두는 길이 먼저예요(QA r6 c2 M5: 취소만 권함)
LOCKED_HINT = (
    "바뀐 조건을 업체에 알리려는 거면 요청은 그대로 두고 실측 때나 채팅이 열리면 말하면 돼요. 집 정보까지 고치려면 "
    "보낸 요청을 propose_visit_cancel(요청마다)로 취소 승인 카드를 만들 수 있어요. 고객이 눌러 모두 취소되면 "
    "잠금이 풀리고, 그 뒤 다시 부르면 돼요."
)


def locked_text(live: int, quoted: bool) -> str:
    """잠긴 집 정보를 고칠 수 없는 까닭(견적서가 왔는지 · 살아 있는 요청이 있는지)."""
    if quoted:
        return LOCKED_QUOTED
    return LOCKED_LIVE if live else "실측을 요청한 뒤라 집 정보를 고칠 수 없어요."


@tool(
    "propose_home_info",
    surface="customer",
    kind="propose",
    status="집 정보 저장을 준비하고 있어요",
    description="고객이 말한 집 정보(지역 · 면적 · 평형 · 면적 기준 · 사는 중 · 벽지 · 방 개수 · 공사 시작 희망 · 철거 "
    "범위) 바뀜을 승인 카드로 만들어요. 고객이 말한 값을 넣으면 카드에서 고객이 확인하고 눌러야 저장돼요. 실측 요청이 "
    "진행 중이거나 업체 견적서가 온 뒤에는 고칠 수 없어요(보낸 요청을 모두 취소하면 견적서가 오기 전까지는 다시 고칠 수 "
    "있어요). 기준을 되묻기만 하지 말고 고객이 말한 값으로 카드를 만들어요. 지역이 틀렸거나 다른 구로 바꾸면 "
    "sgg(시 · 군 · 구, 예 노원구)를 넣어요(같은 이름이 여러 시 · 도에 있으면 '부산 중구'처럼). "
    "평형('34평')은 pyeong에 넣으면 믿집이 공급 ㎡로 바꿔요. ㎡를 area_m2에 넣을 때는 area_basis를 같이 넣어요: "
    "'nn 타입'('84 타입' = 전용 84㎡) · 등기의 ㎡는 exclusive, 분양 면적이라고 한 ㎡는 supply예요. "
    "계약서 ㎡처럼 고객이 기준을 말하지 않은 ㎡는 보통 전용이라 exclusive로 카드를 만들고, 답에 기준을 밝혀 카드로 "
    "확인받아요(예: '계약서 84㎡는 보통 전용면적이라 전용 84㎡로 카드를 만들었어요. 공급면적이면 말해 주세요'). "
    "기준에 따라 표준견적서가 크게 달라져요. "
    "평형과 타입을 같이 말하면 타입(전용 ㎡)을 넣어요. "
    "철거 범위는 전체 철거(full) · 부분 철거(partial) · 철거 안 함(none)이고, 전체 철거면 표준견적서가 "
    "리모델링 기준으로 바뀌어요. 직접 할 일(diy)은 고객이 업체 없이 직접 하는 일의 바뀐 뒤 전체 목록이고, 빈 목록이면 "
    "'없어요'예요. 직접 할 일만 바꾸는 건 실측을 요청한 뒤에도 돼요.",
    model=HomeIn,
    schema=obj(
        {
            "fields": obj(
                {
                    "sgg": {
                        "type": "string",
                        "description": "바꿀 지역의 시 · 군 · 구(예 노원구 · 성남시 · 부산 중구). 지역을 "
                        "바꿀 때만",
                    },
                    "area_m2": {"type": "number", "description": "㎡, 소수 한 자리(기준과 같이)"},
                    "area_basis": {
                        "type": "string",
                        "enum": ["supply", "exclusive"],
                        "description": "면적 기준: supply 공급 · exclusive 전용(계약서 · 타입의 ㎡)",
                    },
                    "pyeong": {
                        "type": "number",
                        "description": "고객이 말한 평형(공급 기준 평, 예 34). 믿집이 공급 ㎡로 바꿔요",
                    },
                    "occupied": {"type": "boolean"},
                    "grade": {"type": "string", "enum": ["economy", "basic"]},
                    "rooms": {"type": "integer"},
                    "start_date": {"type": "string", "format": "date"},
                    "demolition": {
                        "type": "string",
                        "enum": ["full", "partial", "none"],
                        "description": "철거 범위: full 전체 · partial 부분 · none 안 함",
                    },
                    "diy": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(DIY_LABELS)},
                        "description": "직접 할 일 전체 목록(바꾼 뒤): paint 페인트(문틀 · 몰딩) · outlet 콘센트 · "
                        "스위치 커버 · light 조명 · silicone 실리콘 · 줄눈 · handle 손잡이 · clean 입주 청소 · "
                        "paper_buy 벽지 직접 구매(벽지만 고객이 사요, 도배 시공은 업체). 없어요는 빈 목록",
                    },
                },
                required=[],
            )
        }
    ),
)
async def propose_home_info(tc: ToolCtx, a: HomeIn) -> ToolOut:
    from app.calc.common import pyeong_to_m2
    from app.calc.dobae import DEMOLITION_KEY
    from app.project import service as project_service
    from app.project.schemas import HomeInfoIn, check_home
    from app.shared.regions import region_label
    from app.visit import flow as visit_flow
    from app.visit import service as visit_service

    pid = pid_of(tc)
    asked = a.fields.model_dump(exclude_none=True, mode="json")
    want_region = asked.pop("sgg", None)  # 지역은 아래에서 시 · 도와 함께 푼다
    py = asked.pop("pyeong", None)
    if "area_m2" in asked and "area_basis" not in asked:
        raise ToolError("need_basis", NEED_BASIS)
    if py is not None and "area_m2" not in asked:  # 평형 → 공급 ㎡(계산 엔진)
        asked["area_m2"] = str(pyeong_to_m2(Decimal(str(py))))
        asked["area_basis"] = "supply"
    else:
        py = None  # ㎡(타입)를 같이 말했으면 그것을 쓴다
    async with SessionLocal() as s:
        p = await project_service.get_for(s, tc.user, pid)
        card, _ = await cards.home(s, tc.user, pid)
        diy_now = await project_diy.diy_for(s, pid)
        said = await project_service.conditions(s, pid)  # 모은 조건(철거 범위 · 직접 할 일 칩)
        reach = await visit_flow.diy_reach(s, pid)  # 직접 할 일을 바꾸면 닿는 업체(QA r2 c2)
        who = told_whom(reach.live, await chosen_names(s, pid)) if reach.live else REQUESTED
        hold = await visit_service.lock_hold(s, pid) if p.locked else (0, False)
    if p.home is None:
        raise ToolError("no_home", "이 공사는 집 정보 화면에서 고쳐 주세요.")
    now_home = p.home.model_dump(mode="json")  # 철거 범위(모은 조건)도 들어 있다
    now_home["diy"] = diy_now
    home_now = {k: v for k, v in now_home.items() if k not in (DEMOLITION_KEY, "diy")}
    if "diy" in asked:  # 칩 순서로 맞춰 견준다
        asked["diy"] = [k for k in tuple(DIY_LABELS) if k in set(asked["diy"])]
    changes = {k: v for k, v in asked.items() if str(now_home.get(k)) != str(v)}
    if want_region is not None:  # 지역 바꾸기(리드 결정 11-22, QA r3 s1)
        region = region_of(want_region, now_home["sido"])
        if region != (now_home["sido"], now_home["sgg"]):  # 시 · 도와 구를 같이, 옛 동은 지운다
            dong = {"emd": None} if now_home.get("emd") else {}
            changes = {"sido": region[0], "sgg": region[1], **dong, **changes}
    if not changes:
        raise ToolError("no_change", "바뀐 칸이 없어요.")
    if p.locked and set(changes) != {"diy"}:  # 직접 할 일만 바꾸는 건 요청 뒤에도 된다
        raise ToolError("locked", locked_text(*hold), hint=LOCKED_HINT if hold[0] else None)
    home_changes = {k: v for k, v in changes.items() if k not in (DEMOLITION_KEY, "diy")}
    merged = None
    if home_changes:  # 철거 범위만 바꾸면 집 정보는 그대로라 다시 검사하지 않는다
        try:
            merged = HomeInfoIn.model_validate({**home_now, **home_changes})
            check_home(merged, tc.today)
        except (ValidationError, AppError) as e:
            raise ToolError("bad_input", "집 정보 칸을 다시 확인해 주세요.") from e
    # 저장 전 표준견적서 금액 · 차액(계산 엔진, 저장 안 함): 살면서 ↔ 빈 집 같은 바뀜도 누르기 전에 보이고, 금액이
    # 그대로인 바뀜(날짜 · 부분 철거)은 메모가 '그대로'라고 말해요(QA r6 c2)
    money = standard_change(p, said, changes, merged)
    moved = None if money is None else money[0] != money[1]
    diff = None
    if money is not None and moved:
        diff = DiffOut(
            label="표준견적서",
            from_won=money[0],
            to_won=money[1],
            diff_won=visit_view.grade_diff(money[1], money[0]),
        )

    def after(k: str, v) -> str:  # 평형으로 받은 면적은 고객이 말한 평을 같이 보인다
        got = _show(k, v)
        return f"{got} ({Decimal(str(py)).normalize():f}평)" if k == "area_m2" and py else got

    # (칸 이름, 바꾼 뒤, 지금): 지역은 시 · 도 · 구 · 동을 한 줄 '서울 노원구'로 보인다
    shown = [
        (FIELD_LABEL[k], after(k, v), _show(k, now_home.get(k)))
        if k != "sgg"
        else (
            FIELD_LABEL[k],
            region_label(changes["sido"], v),
            region_label(now_home["sido"], now_home["sgg"]),
        )
        for k, v in changes.items()
        if k not in ("sido", "emd")
    ]
    rows = [SummaryRow(label=k, value=v, sub=f"지금 {b}") for k, v, b in shown]
    out, _ = await _offer(
        tc,
        kind="home_info",
        target_kind="project",
        target_id=pid,
        target_ver=actions.home_ver(p.rev, changes, diy_now),  # 직접 할 일을 바꾸면 칩 지문까지
        payload={"fields": changes},
        summary=ActionSummary(
            title="직접 할 일 저장" if set(changes) == {"diy"} else "집 정보 저장",
            diff=diff,
            rows=rows,
            note=home_note(
                changes,
                p.locked,
                diy_now,
                live=bool(reach.live),
                dealt=bool(reach.dealt),
                who=who,
                moved=moved,
            ),
            approve_label="맞아요, 저장",
        ),
        expires_at=tc.now + timedelta(days=7),
        project_id=pid,
    )
    if "diy" in changes and (reach.live or reach.dealt):  # 직접 할 일이 닿는 업체(QA r2 c2)
        from app.assistant.tools.diy import vendors_of

        out.data["vendors"] = vendors_of(reach)
    if not out.actions:  # 거절한 같은 제안: 카드에 바뀜 · 단추를 달지 않는다
        return out
    card.data = {
        **card.data,
        "changes": [{"label": k, "before": b, "after": v} for k, v, b in shown],
        "action_id": str(out.actions[0].action_id),
    }
    card.say = "이 집 정보가 맞는지 확인해 주세요."
    out.cards.append(card)
    return out


class VisitReqIn(BaseModel):
    trade: Literal["dobae", "mokgong"] = "dobae"
    vendor_refs: list[str] = Field(default_factory=list, max_length=3)
    wish_ref: str | None = None
    pick: Literal["top"] | None = None  # 고객이 맡김: 믿집 점수 1위를 서버가 넣는다

    @model_validator(mode="after")
    def _who(self) -> "VisitReqIn":
        if self.pick is None and not self.vendor_refs:
            raise ValueError("vendor_refs(업체 이름표 1~3개) 또는 pick=top")
        return self


TOP_WHY = "고객이 맡겨서 믿집 점수 1위(별점 · 끝낸 공사 · 가견적을 합친 점수)를 넣었어요"
ESTIMATE_LABEL = "가견적"


def estimate_row(paper_note: str | None) -> SummaryRow:
    """실측 요청 승인 카드 '가견적' 줄. 벽지 직접 구매면 가견적은 벽지 값이 든 값이라는 안내(틀 quote.service
    OWN_PAPER_NOTE, 업체 고르기 카드와 같은 글)를 덧말로 달아요(QA r6 c2)."""
    return SummaryRow(label=ESTIMATE_LABEL, value="업체가 확인한 단가로 고정돼요", sub=paper_note)


@tool(
    "propose_visit_request",
    surface="customer",
    kind="propose",
    status="실측 요청을 준비하고 있어요",
    description="고른 업체(v1…, 1~3곳)에 보낼 실측 요청을 승인 카드로 만들어요. 희망 기간은 wish_ref(r1…)이고, "
    "비우면 믿집 초안(공사 시작 희망일 − 28 ~ − 14일)이에요. 고객이 업체를 알아서 골라 달라고 맡기면 vendor_refs를 "
    "빈 목록으로 두고 pick=top으로 불러요: 믿집 점수 1위 업체를 믿집이 넣고, 결과의 why가 까닭이에요(따로 고르지 "
    "않아요). 요청은 집 지역 업체에만 보낼 수 있어요.",
    model=VisitReqIn,
    schema=obj(
        {
            "trade": TRADE,
            "vendor_refs": {
                "type": "array",
                "items": REF,
                "description": "업체 이름표 1~3개(pick=top이면 빈 목록)",
            },
            "wish_ref": REF,
            "pick": {
                "type": "string",
                "enum": ["top"],
                "description": "고객이 고르기를 맡김: 믿집 점수 1위를 믿집이 넣어요",
            },
        },
        required=["trade", "vendor_refs"],
    ),
)
async def propose_visit_request(tc: ToolCtx, a: VisitReqIn) -> ToolOut:
    from app.assistant.tools import diy as diy_tools
    from app.calc import slots
    from app.project import service as project_service
    from app.visit import service as visit_service

    dobae_only(a.trade)
    pid = pid_of(tc)
    top = None
    if a.pick == "top":  # 맡긴 고르기는 코드 점수 1위(리드 결정 11-22, QA r3 s4)
        async with SessionLocal() as s:
            _card, pm = await cards.vendor_picks(s, tc.user, pid, a.trade, tc.refs)
        if not pm["picks"]:
            raise ToolError("no_vendor", "지금 요청할 수 있는 업체가 없어요.")
        top = pm["picks"][0]
    refs = [top["ref"]] if top else a.vendor_refs
    picked = {tc.refs.get(r, "vendor")["id"]: r for r in refs}
    async with SessionLocal() as s:
        p = await project_service.get_for(s, tc.user, pid)
        lst = await visit_service.vendors_for(s, tc.user, pid, a.trade)
        told, diy_keys = await diy_tools.offer_part(s, tc.user.id, pid)  # 반셀프: 업체에 알릴 것
    cards_by_id = {str(c.vendor_id): c for c in (*lst.local, *lst.nearby)}
    rows = []
    for vid in picked:
        c = cards_by_id.get(vid)
        if c is None or c.state != "ok" or c.estimate_total is None:
            raise ToolError("unavailable", "고른 업체 중 지금 요청할 수 없는 곳이 있어요.")
        rows.append(c)
    if a.wish_ref is not None:
        w = tc.refs.get(a.wish_ref, "wish")
        start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
    else:
        start, end = slots.draft_wish(visit_service.work_start(p), tc.today) or (
            tc.today + timedelta(days=1),
            tc.today + timedelta(days=14),
        )
    if start <= tc.today:
        raise ToolError("past", "희망 기간이 지났어요. 시간 후보를 다시 찾아 주세요.")
    summary = ActionSummary(
        title=f"{' · '.join(c.name for c in rows)}에 실측 요청 보내기",  # 턴 사실에 업체가 보이게
        amounts=[AmountRow(label=c.name, won=c.estimate_total) for c in rows],
        rows=[
            SummaryRow(label="지역", value=p.region),  # 어느 집 지역으로 가는 요청인지(QA r3 s1)
            SummaryRow(label="희망 기간", value=cards.md_range(start, end)),
            estimate_row(lst.paper_note),
            *([told] if told else []),
        ],
        note="업체마다 48시간 안에 갈 수 있는 기간을 답해요. 연락은 믿집 채팅으로 이어져요",
        approve_label=f"{len(rows)}곳에 요청 보내기",
    )
    out, _ = await _offer(
        tc,
        kind="visit_request",
        target_kind="project",
        target_id=pid,
        target_ver=str(p.rev),
        payload={
            "trade": a.trade,
            "vendor_ids": [str(c.vendor_id) for c in rows],
            "wish_start": start.isoformat(),
            "wish_end": end.isoformat(),
            **({"diy": diy_keys} if diy_keys else {}),
        },
        summary=summary,
        expires_at=tc.now + timedelta(days=3),
        project_id=pid,
    )
    if top is not None:  # 맡긴 고르기: 누구를 왜 넣었는지(까닭 틀)
        out.data["vendor"] = top["name"]
        out.data["why"] = [TOP_WHY, *top.get("reasons", [])]
    return out


class SlotIn(BaseModel):
    slot_ref: str


# 반나절 승인 카드를 누른 뒤 일(모델 값 note): 업체 수락 전에는 실측이 정해진 게 아니에요
SLOT_ACCEPT = (
    "고객이 카드를 누르면 고른 반나절이 업체에 가고, 업체가 수락하면 정해져요. 누르기 전이나 업체 수락 전에는 "
    "정해진 게 아니에요."
)
SLOT_INSTANT = "고객이 카드를 누르면 바로 정해져요. 누르기 전에는 정해진 게 아니에요."


def slot_offer(v, slot: dict) -> dict:
    """반나절 하나(pick_view 결과 v · 이름표 값 slot) → 대기 행동 인자. 도구 · 먼저 말 걸기가 같이 쓴다.
    고를 수 있는 때가 아니면 ToolError(stale)."""
    via = slot["via"]
    if via == "proposal":
        if v.status != "proposed" or v.proposal is None:
            raise ToolError("stale", "업체가 낸 날이 바뀌었어요. 시간 후보를 다시 찾아 주세요.")
        due, instant, ver = v.proposal.due_at, True, "업체가 낸 날"
    else:
        if v.status != "offered" or v.window is None:
            raise ToolError("stale", "고를 수 있는 때가 아니에요. 시간 후보를 다시 찾아 주세요.")
        w = v.window
        due, instant = w.pick_due_at, w.instant
        ver = f"업체가 답한 기간 {cards.md_range(w.start, w.end)}"
    day = date.fromisoformat(slot["day"])
    summary = ActionSummary(
        title=f"{v.vendor_name} 실측 {cards.md_long(day)} {HALF[slot['half']]}",
        version=ver,
        rows=[
            SummaryRow(
                label="그 뒤 일",
                value="고르면 바로 확정돼요" if instant else "업체가 수락하면 확정돼요",
            )
        ],
        note="시각은 실측 전날 채팅으로 정해요",
        approve_label="이 시간으로 고르기",
    )
    return {
        "kind": "visit_slot",
        "target_kind": "visit",
        "target_id": v.visit_id,
        "target_ver": v.status,
        "payload": {
            "visit_id": str(v.visit_id),
            "day": slot["day"],
            "half": slot["half"],
            "via": via,
            "instant": instant,
        },
        "summary": summary,
        "expires_at": due,
    }


@tool(
    "propose_visit_slot",
    surface="customer",
    kind="propose",
    status="실측 시간을 준비하고 있어요",
    description="반나절 후보(s1…) 하나를 고르는 승인 카드를 만들어요.",
    model=SlotIn,
    schema=obj({"slot_ref": REF}),
)
async def propose_visit_slot(tc: ToolCtx, a: SlotIn) -> ToolOut:
    from app.visit import service as visit_service

    pid = pid_of(tc)
    slot = tc.refs.get(a.slot_ref, "slot")
    visit_id = uuid.UUID(slot["visit_id"])
    async with SessionLocal() as s:
        v = await visit_service.pick_view(s, tc.user, pid, visit_id, tc.now)
    got = slot_offer(v, slot)
    out, _ = await _offer(tc, project_id=pid, **got)
    if out.actions:  # 누른 뒤 일: 바로 확정인지 업체 수락을 기다리는지(QA r3 s4 6턴 '정해졌어요')
        then = SLOT_INSTANT if got["payload"]["instant"] else SLOT_ACCEPT
        out.data["note"] = f"{out.data['note']} {then}"
    return out


class VisitRefIn(BaseModel):
    visit_ref: str


@tool(
    "propose_vendor_confirm",
    surface="customer",
    kind="propose",
    status="업체 확정을 준비하고 있어요",
    description="견적서를 받은 업체(m1…) 하나로 확정하는 승인 카드를 만들어요. 지금 견적서 판으로 고정되고, "
    "업체가 새 판을 보내면 그 카드는 실행되지 않아요.",
    model=VisitRefIn,
    schema=obj({"visit_ref": REF}),
)
async def propose_vendor_confirm(tc: ToolCtx, a: VisitRefIn) -> ToolOut:
    from app.visit import service as visit_service

    pid = pid_of(tc)
    ref = tc.refs.get(a.visit_ref, "visit")
    visit_id = uuid.UUID(ref["id"])
    trade = ref.get("trade") or "dobae"
    async with SessionLocal() as s:
        cmp = await visit_service.compare(s, tc.user, pid, trade, tc.today)
    row = next((r for r in cmp.vendors if r.visit_id == visit_id), None)
    done = next((r for r in cmp.vendors if r.status == "chosen"), None)
    if done is not None:  # 이미 확정했다('확정할 견적서가 없어요'라고 하지 않는다)
        if done is not row:
            raise ToolError(
                "already_chosen",
                f"이미 {euro(done.vendor_name)} 확정했어요. 바꾸려면 견적서 화면에서 다시 골라 주세요.",
            )
        from app.schedule import service as schedule_service

        # 확정 뒤 지금 공사 날짜 상태로 말해요(끝난 일을 기다리라고 하지 않게)
        async with SessionLocal() as s:
            sch = await schedule_service.schedule_for(s, tc.user, pid, tc.today)
        t = next((x for x in sch.trades if x.deal.visit_id == visit_id), None)
        state = cards.DATES_STATE.get(t.dates_state) if t else None
        d = t.deal if t else None
        if t is not None and t.dates_state == "scheduled" and d.start_date and d.end_date:
            state = f"공사 날짜 {cards.long_range(d.start_date, d.end_date)}도 수락했어요"
        raise ToolError(
            "already_chosen",
            f"이미 {euro(done.vendor_name)} 확정했어요." + (f" {state}." if state else ""),
        )
    if row is None or row.latest is None or row.status != "quoted" or row.seen_ver is None:
        raise ToolError("not_quoted", "아직 확정할 수 있는 견적서가 없어요.")
    if row.expired:
        raise ToolError("expired", "견적서 유효기간이 지났어요. 다시 받기를 요청해 주세요.")
    q = row.latest
    summary = actions.confirm_summary(row.vendor_name, q.version, q.total, q.days, q.valid_until)
    summary.file = LinkOut(label="견적서 보기", href=cards.href(pid, "/quotes"))
    out, _ = await _offer(
        tc,
        kind="vendor_confirm",
        target_kind="visit",
        target_id=visit_id,
        target_ver=str(row.seen_ver),
        payload={
            "visit_id": str(visit_id),
            "trade": trade,
            "vendor_name": row.vendor_name,
            "version": q.version,
        },
        summary=summary,
        expires_at=actions.confirm_expiry(q.valid_until, tc.now),
        project_id=pid,
    )
    return out


class ProposalIn(BaseModel):
    proposal_ref: str


def dates_offer(sch, proposal_id: str, kind: str, now) -> dict:
    """공사 날짜 제안 하나(schedule_for 결과 sch) → 수락 대기 행동 인자. 도구 · 먼저 말 걸기가 같이 쓴다.
    바뀌었으면 ToolError(stale), 다른 공정과 겹치면 ToolError(conflict)."""
    t = next(
        (x for x in sch.trades if x.proposal is not None and str(x.proposal.id) == proposal_id),
        None,
    )
    if t is None or t.proposal is None or t.proposal.status != "pending":
        raise ToolError("stale", "날짜가 바뀌었어요. 공사 날짜를 다시 봐 주세요.")
    if t.fit is not None and t.fit.conflicts:
        raise ToolError(
            "conflict", "다른 공정과 겹쳐서 수락할 수 없어요. 다른 날짜를 요청해 주세요."
        )
    x = t.proposal
    name = cards.TRADE.get(t.deal.trade, t.deal.trade)
    summary = ActionSummary(
        title=f"{name} {cards.long_range(x.start, x.end)} 수락",
        version=f"공정표 {sch.final_version}판" if sch.final_version else "첫 공사 날짜",
        rows=[
            SummaryRow(label="업체", value=t.deal.vendor_name),
            SummaryRow(label="일하는 날", value=f"{x.workdays}일"),
        ],
        note="수락하면 확정 공정표가 만들어져요"
        if kind == "dates_accept"
        else "수락하면 공정표가 바뀐 날짜로 다시 짜여요",
        approve_label="이 날짜로 수락",
    )
    return {
        "kind": kind,
        "target_kind": "proposal",
        "target_id": x.id,
        "target_ver": str(sch.final_version),
        "payload": {"deal_id": str(t.deal.id), "proposal_id": str(x.id)},
        "summary": summary,
        "expires_at": now + timedelta(days=2),
    }


def dates_kind(deal_status: str) -> Literal["dates_accept", "delay_accept"]:
    """수락한 뒤(scheduled) 바뀐 날짜면 연기 수락, 아니면 첫 날짜 수락."""
    return "delay_accept" if deal_status == "scheduled" else "dates_accept"


async def _dates(tc: ToolCtx, a: ProposalIn, kind: Literal["dates_accept", "delay_accept"]):
    from app.schedule import service as schedule_service

    pid = pid_of(tc)
    pr = tc.refs.get(a.proposal_ref, "proposal")
    want = "delay" if kind == "delay_accept" else "dates"
    if pr.get("type") != want:  # 글에는 도구 이름 없이, 모델 힌트에만
        other = "propose_delay_accept" if want == "dates" else "propose_dates_accept"
        raise ToolError(
            "wrong_kind",
            "수락한 뒤 바뀐 날짜예요. 바뀐 날짜 수락 카드로 만들어야 해요."
            if want == "dates"
            else "처음 올린 날짜예요. 날짜 수락 카드로 만들어야 해요.",
            hint=f"{other}로 다시 불러요",
        )
    async with SessionLocal() as s:
        sch = await schedule_service.schedule_for(s, tc.user, pid, tc.today)
    out, _ = await _offer(tc, project_id=pid, **dates_offer(sch, pr["id"], kind, tc.now))
    if out.actions:  # 같은 card_id로 바꿔 끼운다: 수락 단추는 승인 카드 하나만(카드 단추를 비움)
        async with SessionLocal() as s:
            card, _ = await cards.schedule(s, tc.user, pid, tc.today, tc.refs)
        if card is not None:
            out.cards.append(card)
    return out


@tool(
    "propose_dates_accept",
    surface="customer",
    kind="propose",
    status="공사 날짜 수락을 준비하고 있어요",
    description="업체가 처음 올린 공사 날짜(p1…)를 수락하는 승인 카드를 만들어요.",
    model=ProposalIn,
    schema=obj({"proposal_ref": REF}),
)
async def propose_dates_accept(tc: ToolCtx, a: ProposalIn) -> ToolOut:
    return await _dates(tc, a, "dates_accept")


@tool(
    "propose_delay_accept",
    surface="customer",
    kind="propose",
    status="바뀐 날짜 수락을 준비하고 있어요",
    description="이미 수락한 공사의 바뀐(연기된) 날짜(p1…)를 수락하는 승인 카드를 만들어요.",
    model=ProposalIn,
    schema=obj({"proposal_ref": REF}),
)
async def propose_delay_accept(tc: ToolCtx, a: ProposalIn) -> ToolOut:
    return await _dates(tc, a, "delay_accept")


CHANGE_WISH_MAX = 3  # 시작해도 되는 날 후보 수(schedule 다른 날짜 요청 WISH_MAX와 같다)
CHANGE_AHEAD = timedelta(days=365)  # 요청 날짜는 1년 안(schedule service와 같다)
ChangeReason = Literal["move", "family", "other_work", "other"]
# 바꾸는 쪽: 앞당기기 earlier(지금 시작일 전 후보만) · 미루기 later(지금 시작일 뒤 후보만)
ChangeDirection = Literal["earlier", "later"]
NO_EARLIER = (
    "지금 시작일 전에는 다른 공정과 겹치지 않게 앞당길 수 있는 날이 없어요. 다른 때를 말해 주세요."
)


def date_change_offer(
    sch,
    deal_id: str,
    reason: str,
    today: date,
    now: datetime,
    *,
    delay_days: int | None = None,
    wish_from: date | None = None,
    direction: str | None = None,
) -> dict:
    """공사 날짜 바꾸기 요청(schedule_for 결과 sch의 확정 하나) → 대기 행동 인자. 도구 · 무료 모드가 같이 쓴다.
    시작해도 되는 날은 계산 엔진이 고른다: 지금 날짜에서 delay_days 뒤(또는 wish_from)부터 지금과 같은 일하는 날
    수로, 다른 공정과 겹치지 않는 자리 안에서 1~3개. 요청할 수 없으면 ToolError.
    direction(earlier 앞당기기 · later 미루기)과 반대인 후보는 내지 않는다(QA r2 f1x: 앞당기기에 늦은 후보). 없으면
    delay_days는 미루기, wish_from은 지금 시작일과 견줘 정한다(같은 날이면 정하지 않음). earlier + delay_days는 며칠 앞으로."""
    from app.calc.schedule import WEEKEND, Dated, count_workdays, free_range, start_choices
    from app.refprice.holidays import days_off
    from app.schedule import service as schedule_service

    t = next((x for x in sch.trades if str(x.deal.id) == str(deal_id)), None)
    if t is None:
        raise ToolError("stale", "공사를 찾을 수 없어요. 공사 날짜를 다시 봐 주세요.")
    if t.request is not None:
        raise ToolError(
            "already_requested",
            "이미 날짜 바꾸기를 요청했어요. 업체가 새 날짜를 올리면 수락할 수 있어요.",
        )
    if t.requests_left <= 0:
        raise ToolError(
            "requests_used", "날짜 바꾸기 요청은 2번까지예요. 업체와 믿집 채팅으로 이야기해 주세요."
        )
    base = actions.change_base(t)
    if base is None:
        raise ToolError("no_dates", "업체가 공사 날짜를 낸 뒤에 바꾸기를 요청할 수 있어요.")
    weekend = () if sch.weekend_work else WEEKEND
    off = days_off(min(today, base[0]), today + CHANGE_AHEAD + timedelta(days=120))
    n = max(count_workdays(base[0], base[1], off, weekend), 1)
    if direction is None and delay_days:
        direction = "later"
    elif direction is None and wish_from is not None and wish_from != base[0]:
        direction = "earlier" if wish_from < base[0] else "later"
    if delay_days:
        step = timedelta(days=delay_days)
        first = base[0] - step if direction == "earlier" else base[0] + step
    else:
        first = wish_from
    first = max(first or today, today + timedelta(days=1))
    if direction == "later":  # 미루기: 지금 시작일 뒤부터
        first = max(first, base[0] + timedelta(days=1))
    others = [
        Dated(x.deal.trade, x.deal.start_date, x.deal.end_date)
        for x in sch.trades
        if x.deal.id != t.deal.id
        and x.deal.status in schedule_service.AFTER_DATES_ACCEPTED
        and x.deal.start_date
        and x.deal.end_date
    ]
    start_from, end_by = free_range(
        t.deal.trade, [Dated(t.deal.trade, *base), *others], schedule_service.ORDER, off, weekend
    )
    first = max(first, start_from) if start_from else first
    got = start_choices(first, n, CHANGE_WISH_MAX, {base[0]}, off, weekend, end_by)
    # 앞당기기: 지금 시작일 전 후보만(뒤로 갈수록 늦어지니 앞 후보는 그대로 남아요)
    if direction == "earlier":
        got = [(a, b) for a, b in got if a < base[0]]
        if not got:
            raise ToolError("no_earlier", NO_EARLIER)
    picked = [(a, b) for a, b in got if a <= today + CHANGE_AHEAD]
    if not picked:
        raise ToolError(
            "no_room", "그때로는 다른 공정과 겹치지 않는 날이 없어요. 다른 때를 말해 주세요."
        )
    change = t.deal.status == "scheduled"
    name = cards.TRADE.get(t.deal.trade, t.deal.trade)
    rows = [
        SummaryRow(
            label="지금 날짜" if change else "업체가 낸 날짜",
            value=cards.md_range(base[0], base[1]),
        ),
        *[
            SummaryRow(label=f"후보 {i}", value=cards.md_range(a, b))
            for i, (a, b) in enumerate(picked, 1)
        ],
        SummaryRow(label="까닭", value=actions.CHANGE_REASONS[reason]),
    ]
    summary = ActionSummary(
        title=f"{name} 공사 날짜 바꾸기 요청" if change else f"{name} 다른 공사 날짜 요청",
        rows=rows,
        note="업체가 새 날짜를 올려 수락하기 전까지 지금 날짜는 그대로예요. "
        f"날짜 바꾸기 요청은 {t.requests_left}번 남았어요",
        approve_label="날짜 바꾸기 요청 보내기",
    )
    pending = t.proposal if t.proposal is not None and t.proposal.status == "pending" else None
    return {
        "kind": "date_change",
        "target_kind": "deal",
        "target_id": t.deal.id,
        "target_ver": actions.change_ver(t),
        "payload": {
            "deal_id": str(t.deal.id),
            "wish_dates": [a.isoformat() for a, _ in picked],
            "reason": reason,
            "proposal_id": str(pending.id) if pending else None,
        },
        "summary": summary,
        # 첫 후보 날이 오면 요청할 수 없어서 그 전(그날 0시, 서울)까지, 길어도 2일
        "expires_at": min(now + timedelta(days=2), datetime.combine(picked[0][0], time(0), SEOUL)),
    }


class DateChangeIn(BaseModel):
    deal_ref: str
    reason: ChangeReason
    delay_days: int | None = Field(default=None, ge=1, le=180)
    wish_from: date | None = None
    direction: ChangeDirection | None = None

    @model_validator(mode="after")
    def _one(self) -> "DateChangeIn":
        if (self.delay_days is None) == (self.wish_from is None):
            raise ValueError("delay_days와 wish_from 중 하나만")
        return self


@tool(
    "propose_date_change",
    surface="customer",
    kind="propose",
    status="날짜 바꾸기 요청을 준비하고 있어요",
    description="확정한 공사(d1…)의 공사 날짜를 바꿔 달라는 요청을 승인 카드로 만들어요. 고객이 수락한 날짜를 "
    "미루거나 당기고 싶을 때, 업체가 낸 날짜 대신 다른 날을 원할 때 써요. 바라는 때는 하나만 넣어요: delay_days(지금 "
    "날짜에서 며칠 뒤로, 일주일 7 · 2주 14) 또는 wish_from(고객이 말한 시작해도 되는 첫날). direction: 앞당기기 "
    "earlier · 미루기 later(고객 말에 쪽이 있으면 넣어요, earlier + delay_days는 며칠 앞으로). 안 넣으면 delay_days는 "
    "미루기, wish_from은 지금 시작일과 견줘 정하고, 그 쪽과 반대인 후보는 내지 않아요. 믿집이 지금과 같은 일하는 "
    "날 수로 시작해도 되는 날 1~3개를 골라요. reason: move 이사 · 입주 · family 집안 일정 · other_work 다른 공사 · "
    "other 그 밖. 요청은 확정마다 2번까지이고, 승인하면 업체가 새 날짜를 올려요(수락 전까지 지금 날짜는 그대로).",
    model=DateChangeIn,
    schema=obj(
        {
            "deal_ref": REF,
            "reason": {"type": "string", "enum": list(actions.CHANGE_REASONS)},
            "delay_days": {"type": "integer", "description": "지금 날짜에서 며칠 뒤로(1~180)"},
            "wish_from": {
                "type": "string",
                "format": "date",
                "description": "고객이 말한 시작해도 되는 첫날",
            },
            "direction": {
                "type": "string",
                "enum": ["earlier", "later"],
                "description": "앞당기기 earlier · 미루기 later",
            },
        },
        required=["deal_ref", "reason"],
    ),
)
async def propose_date_change(tc: ToolCtx, a: DateChangeIn) -> ToolOut:
    from app.schedule import service as schedule_service

    pid = pid_of(tc)
    deal = tc.refs.get(a.deal_ref, "deal")
    async with SessionLocal() as s:
        sch = await schedule_service.schedule_for(s, tc.user, pid, tc.today)
    got = date_change_offer(
        sch,
        deal["id"],
        a.reason,
        tc.today,
        tc.now,
        delay_days=a.delay_days,
        wish_from=a.wish_from,
        direction=a.direction,
    )
    out, _ = await _offer(tc, project_id=pid, **got)
    return out


# ---- 거두기 · 실측 요청 취소(피클 표본 7, 고정 선 1: 실행 전 제안은 고객 말로 거둔다) ----

# 고객 승인 카드 종류(제안 도구 이름에서 propose_를 뗀 것) → 화면 이름
KIND_NAME: dict[str, str] = {
    "home_info": "집 정보", "visit_request": "실측 요청", "visit_slot": "실측 시간",
    "vendor_confirm": "업체 확정", "dates_accept": "공사 날짜 수락", "delay_accept": "바뀐 날짜 수락",
    "date_change": "날짜 바꾸기 요청", "extra_answer": "추가 금액 답", "work_check": "공사 끝 확인",
    "visit_again": "한 번 더 요청", "visit_cancel": "실측 요청 취소",
}  # fmt: skip
WithdrawKind = Literal[
    "any", "home_info", "visit_request", "visit_slot", "vendor_confirm", "dates_accept",
    "delay_accept", "date_change", "extra_answer", "work_check", "visit_again", "visit_cancel",
]  # fmt: skip
_PLAIN = re.compile(r"[\s·,.!?~()\[\]'\"“”‘’:;\-]+")
# 말 조각 끝의 조사(업체 이름 · 카드 이름에 붙은 '솔빛도배에' · '요청을')
_JOSA = re.compile(r"(?:에게|한테|으로|이랑|하고|에서|에|의|을|를|이|가|은|는|로|도|만|랑|께)$")
# 거둘 카드를 가리킬 때 같이 오는 말(카드를 가르지 않는 말)
FILLER = frozenset({
    "카드", "승인", "제안", "그", "그거", "그것", "이거", "이것", "저거", "아까", "방금", "좀", "거", "것", "꺼",
})  # fmt: skip
WITHDRAWN_NOTE = (
    "카드를 거뒀어요. 실행 전이라 업체에 간 것은 없어요. 고객이 다시 원하면 새로 만들 수 있어요."
)
CHOOSE_NOTE = "거둘 카드가 여럿이에요. 어느 카드인지 고객에게 물어요(카드의 단추로 고를 수 있어요)."
NONE_NOTE = "지금 거둘 승인 카드가 없어요."
EXECUTED_NOTE = "이미 실행된 카드라 거둘 수 없어요."
SENT_NOTE = (
    "보낸 실측 요청은 취소 승인 카드(propose_visit_cancel)로 취소해요. 고객이 어느 업체 요청인지 말했으면 requests의 "
    "이름표로, 요청이 여럿인데 말하지 않았으면 visit_ref 없이 불러 고르기 카드를 내요. 고객이 눌러야 취소돼요."
)


def plain(text: str | None) -> str:
    """띄움 · 문장부호를 뺀 글(카드 제목 · 고객 말 견주기)."""
    return _PLAIN.sub("", text or "")


def haystack(a) -> str:
    """승인 카드에서 찾을 글: 제목 · 요약 줄 값 · 금액 줄 이름(업체 이름)."""
    sm = a.summary or {}
    bits = [
        sm.get("title") or "",
        *(str(r.get("value") or "") for r in sm.get("rows") or []),
        *(str(x.get("label") or "") for x in sm.get("amounts") or []),
    ]
    return plain(" ".join(bits))


def title_of(a) -> str:
    return str((a.summary or {}).get("title") or KIND_NAME.get(a.kind, "승인 카드"))


def _words(text: str) -> list[str]:
    out = []
    for w in re.split(r"[\s·,]+", text or ""):
        w = plain(w)
        w = _JOSA.sub("", w) if len(w) > 2 else w
        if len(w) >= 2 and w not in FILLER:
            out.append(w)
    return out


def about_hits(rows: list, about: str) -> list:
    """카드 고르기(about: 카드 제목 또는 업체 이름): 제목이 같은 카드 → 글이 든 카드 → 낱말이 모두 든 카드.
    about이 비면 모두."""
    key = plain(about)
    if not key:
        return list(rows)
    same = [a for a in rows if plain(title_of(a)) == key]
    if same:
        return same
    hits = [a for a in rows if key in haystack(a) or plain(title_of(a)) in key]
    if hits:
        return hits
    words = _words(about)
    return [a for a in rows if words and all(w in haystack(a) for w in words)]


def unique_say(rows: list) -> list[tuple[str, str, str | None]]:
    """고르기 칩(단추 글, 보낼 말, 덧말): 제목이 같은 카드는 첫 요약 줄 값(업체 등)을 붙여 가른다."""
    titles = [title_of(a) for a in rows]
    out = []
    for a, t in zip(rows, titles, strict=True):
        rows_ = (a.summary or {}).get("rows") or []
        extra = str(rows_[0].get("value")) if titles.count(t) > 1 and rows_ else ""
        label = f"{t} · {extra}" if extra else t
        out.append((label, f"{label} 카드 거둬 줘", KIND_NAME.get(a.kind)))
    return out


async def open_cards(s, user_id: uuid.UUID, pid: uuid.UUID, now: datetime) -> list:
    """이 공사의 고객 승인 기다리는 카드(기한 전, 오래된 것부터)."""
    from app.assistant import repository as repo

    rows = await repo.actions_of(s, user_id, "customer", project_id=pid, status="proposed")
    return sorted((a for a in rows if a.expires_at > now), key=lambda a: a.created_at)


def requests_model(tc: ToolCtx, visits: list) -> list[dict]:
    """보낸 실측 요청(취소할 수 있는 것) → 모델 값(이름표 m…). 이름표는 이 대화 표에 넣는다."""
    return [
        {
            "ref": tc.refs.put(
                "visit", {"id": str(v.id), "vendor_name": v.vendor_name, "trade": v.trade}
            ),
            "vendor_name": v.vendor_name,
            "state": cards.SENT_STATE.get(v.status, "진행 중"),
        }
        for v in visits
    ]


async def withdraw_one(tc: ToolCtx, a) -> tuple[ToolOut, str]:
    """카드 하나를 거둔다(조건부: 그사이 승인 · 거절 · 만료면 지금 상태로 알린다). (도구 결과, state)."""
    from app.assistant import repository as repo

    async with SessionLocal() as s:
        got = await actions.withdraw(s, a, tc.now)
        await s.commit()
        if got is None:
            got = await repo.action_owned(s, tc.user.id, a.id, "customer")
    row = actions.out(got)  # type: ignore[arg-type]
    if row.status == "rejected" and row.error_code == actions.WITHDRAWN:
        data = {"state": "withdrawn", "title": row.summary.title, "note": WITHDRAWN_NOTE}
        return ToolOut(data=data, closed=[row]), "withdrawn"
    note = EXECUTED_NOTE if row.status in ("approved", "executed") else CLOSED_NOTE
    return ToolOut(data={"state": "closed", "title": row.summary.title, "note": note}), "closed"


class WithdrawIn(BaseModel):
    kind: WithdrawKind = "any"
    about: str = Field(default="", max_length=80)


@tool(
    "withdraw_proposal",
    surface="customer",
    # 승인 카드를 만들지 않아 엄격(제안 도구 propose_* 20개 한도)에 넣지 않아요. 입력은 run이 pydantic으로 검사해요
    kind="read",
    status="카드를 거두고 있어요",
    description="고객이 아직 누르지 않은 승인 카드(승인 기다리는 카드)를 고객 말로 거둬요('그 카드 취소해 줘' · "
    "'아까 요청 카드 거둬 줘'). 거절과 같게 남아 다시 만들지 않아요. kind는 카드 종류(모르면 any), about은 거둘 "
    "카드 제목(턴 사실 · 도구 결과의 제목 그대로) 또는 업체 이름이고 모르면 빈 글이에요. 하나로 정해지면 바로 "
    "거두고(state withdrawn), 여럿이면 후보(items)와 고르기 칩 카드를 돌려줘요(state choose: 어느 카드인지 물어요). "
    "이미 실행된 카드는 거둘 수 없어요: 보낸 실측 요청은 propose_visit_cancel(requests의 m 이름표)로 취소 승인 "
    "카드를 만들어요.",
    model=WithdrawIn,
    schema=obj(
        {
            "kind": {
                "type": "string",
                "enum": ["any", *KIND_NAME],
                "description": "거둘 카드 종류(제안 도구 이름에서 propose_를 뗀 것), 모르면 any",
            },
            "about": {
                "type": "string",
                "description": "거둘 카드 제목 또는 업체 이름(모르면 빈 글)",
            },
        }
    ),
)
async def withdraw_proposal(tc: ToolCtx, a: WithdrawIn) -> ToolOut:
    pid = pid_of(tc)
    async with SessionLocal() as s:
        rows = await open_cards(s, tc.user.id, pid, tc.now)
        got = about_hits([x for x in rows if a.kind in ("any", x.kind)], a.about)
        visits = await cards.sent_visits(s, tc.user, pid) if len(got) != 1 else []
    if len(got) == 1:
        out, _ = await withdraw_one(tc, got[0])
        return out
    sent = requests_model(tc, visits)
    if len(got) > 1:
        options = unique_say(got)
        card = cards.options_card("withdraw-pick", "어느 카드를 거둘까요?", options)
        items = [{"title": t, "kind": k} for t, _, k in options]
        data = {"state": "choose", "items": items, "note": CHOOSE_NOTE}
        return ToolOut(data={**data, **({"requests": sent} if sent else {})}, cards=[card])
    note = NONE_NOTE + (" " + SENT_NOTE if sent else "")
    return ToolOut(data={"state": "none", "note": note, **({"requests": sent} if sent else {})})


class VisitCancelIn(BaseModel):
    # 비우면: 하나면 그것, 여럿이면 고객 말(업체 이름 · '둘 다')로 풀고, 못 풀면 고르기 카드
    visit_ref: str | None = None
    code: Literal["changed", "other_vendor", "other"] = "other"


def every_word(n: int) -> str:
    """보낸 요청 n개 모두를 가리키는 말(고르기 칩 · 메모 글): 둘이면 '둘 다', 셋 이상이면 '모두'."""
    return "둘 다" if n == 2 else "모두"


def choose_note(every: str) -> str:
    """취소 고르기 결과의 메모 글: 칩을 가리켜 묻게 한다(QA r5 A s1-3 · s6-2: '둘 다 취소' 칩이 있는데 '"둘 다"라고
    말씀해 주세요'라고 말로 하라고 함). every는 요청 모두를 고르는 칩 글('둘 다 취소' · '모두 취소')."""
    return (
        "보낸 실측 요청이 여럿인데 고객 말에 어느 업체인지 없어요. 고르기 칩을 보였으니 이 턴에는 다시 부르지 말고 어느 "
        f"업체 요청을 취소할지 고객에게 물어요. 말로 적어 달라고 하지 말고 '아래 칩에서 업체나 [{every}]를 고르면 "
        "돼요'처럼 칩을 가리켜요. 모두 취소하려면 요청마다 visit_ref(requests의 ref)로 불러요."
    )


CANCEL_CHOOSE_NOTE = choose_note(f"{every_word(2)} 취소")  # 요청이 둘일 때(셋 이상은 '모두 취소')
CANCEL_AGAIN = "고르기 칩을 이미 보였어요. 고객이 고를 때까지 기다려 주세요."
CANCEL_AGAIN_HINT = (
    "고르기 칩을 이미 보였어요. 고객이 고를 때까지 기다리거나, 고객이 말한 업체의 이름표(m…)로 visit_ref를 넣어 "
    "불러요(이름표: {refs})."
)
CANCEL_MANY_NOTE = (
    "요청마다 취소 승인 카드를 만들었어요(items). 카드마다 사람이 눌러야 그 요청이 취소돼요."
)
CANCEL_NONE_NOTE = "지금 취소할 수 있는 실측 요청이 없어요."
CHOSE = "cancel_choose"  # 이 턴에 취소 고르기 칩을 보였다(ToolCtx.marks)
# 보낸 요청 모두를 가리키는 말('둘 다' · '두 곳 다' · '모두' · '전부' · '다 취소'). '다른' · '다시' · '다음'은 아니다
ALL_SAID = re.compile(
    r"(?:둘|셋|두\s{0,2}(?:곳|군데|업체|개|건)|세\s{0,2}(?:곳|군데|업체|개|건))\s{0,2}(?:다|모두)(?![른시음])"
    r"|모두|전부|(?<![가-힣])다\s{0,2}(?:취소|빼|없애|거둬|거두)"
)
# 업체 이름 바로 뒤(띄움을 뺀 글)에 오면 그 요청은 남기는 말('결도배는 남기고 …' · '결도배 요청은 그대로 두고' ·
# '결도배 빼고 다')
KEEP_SAID = re.compile(
    r"^(?:에보낸요청|요청|업체|쪽|거|건)?(?:은|는|이|가|도|만)?(?:그대로|그냥|계속|일단)?"
    r"(?:남기|남겨|두고|놔두|놓고|말고|빼고|제외|유지|살리|살려)"
)


def cancel_targets(live: list, text: str) -> list:
    """visit_ref 없이 불렀을 때 이번 턴 고객 말(가린 글)로 취소할 요청을 푼다(QA r4 s1 C1 · s6 12 · 13턴: 고르기 칩
    글 '마루와벽에 보낸 실측 요청 취소해 줘' · '둘 다 취소해 주세요'에도 고르기 칩만 6번). 업체 이름이 나오면 그
    요청(들), '…는 남기고'면 남긴 업체 말고 남은 하나(또는 '나머지 · 모두'면 남은 것 모두), '둘 다 · 모두 · 전부 · 다
    취소'면 살아 있는 요청 모두. 못 풀면 빈 목록(고르기 칩으로 물어요)."""
    said = plain(text)
    named, kept = [], []
    for v in live:
        name = plain(v.vendor_name)
        at = said.find(name) if name else -1
        if at >= 0:
            (kept if KEEP_SAID.match(said[at + len(name) :]) else named).append(v)
    # 다른 업체 이름에 든 짧은 이름은 뺀다('한결도배'라고 하면 '한결'은 아니에요)
    names = [plain(v.vendor_name) for v in named]
    named = [
        v for v, n in zip(named, names, strict=True) if not any(n != m and n in m for m in names)
    ]
    every = bool(ALL_SAID.search(text))
    if named:
        return named
    if kept:
        rest = [v for v in live if v not in kept]
        return rest if len(rest) == 1 or every or "나머지" in said else []
    return list(live) if every else []


def cancel_options(visits: list) -> CardOut:
    """살아 있는 요청이 여럿일 때 '무엇을 취소할까요?' 고르기 칩(무료 모드 '취소해 줘'와 같은 꼴) + '둘 다 · 모두
    취소' 칩(QA r4 s1: 모두 취소하려는 고객에게 칩이 없었어요)."""
    options: list[tuple[str, str, str | None]] = [
        (
            f"{v.vendor_name}에 보낸 실측 요청",
            f"{v.vendor_name}에 보낸 실측 요청 취소해 줘",
            cards.SENT_STATE.get(v.status),
        )
        for v in visits
    ]
    if len(visits) > 1:
        word = every_word(len(visits))
        options.append((f"{word} 취소", f"보낸 실측 요청 {word} 취소해 줘", None))
    return cards.options_card("cancel-pick", "무엇을 취소할까요?", options)


def cancel_choose(tc: ToolCtx, live: list) -> ToolOut:
    """고르기 칩(state choose). 같은 턴에 이미 보였으면 또 내지 않고 오류로 돌려준다(QA r4 s1 C1: 이름표 없이 6번)."""
    if CHOSE in tc.marks:
        refs = " · ".join(f"{r['ref']} {r['vendor_name']}" for r in requests_model(tc, live))
        raise ToolError("choose_shown", CANCEL_AGAIN, hint=CANCEL_AGAIN_HINT.format(refs=refs))
    tc.marks.add(CHOSE)
    note = choose_note(f"{every_word(len(live))} 취소")  # 칩 글과 같은 말(둘 다 · 모두 취소)
    data = {"state": "choose", "requests": requests_model(tc, live), "note": note}
    return ToolOut(data=data, cards=[cancel_options(live)])


async def cancel_one(tc: ToolCtx, v, code: str, pid: uuid.UUID) -> ToolOut:
    """요청 하나의 취소 승인 카드."""
    summary = ActionSummary(
        title=f"{v.vendor_name}에 보낸 실측 요청 취소",
        rows=[
            SummaryRow(label="업체", value=v.vendor_name),
            SummaryRow(label="지금", value=cards.SENT_STATE.get(v.status, "진행 중")),
            SummaryRow(label="까닭", value=actions.CANCEL_REASONS[code]),
        ],
        note="취소하면 업체에 알림이 가고 이 업체의 담기 칸이 비어요. 잡아 둔 실측 날짜도 풀려요",
        approve_label="실측 요청 취소하기",
    )
    out, _ = await _offer(
        tc,
        kind="visit_cancel",
        target_kind="visit",
        target_id=v.id,
        target_ver=v.status,
        payload={"visit_id": str(v.id), "code": code, "vendor_name": v.vendor_name},
        summary=summary,
        expires_at=tc.now + timedelta(days=2),
        project_id=pid,
    )
    return out


async def cancel_many(tc: ToolCtx, visits: list, code: str, pid: uuid.UUID) -> ToolOut:
    """요청마다 취소 승인 카드('둘 다 취소해 주세요'). 모델 값은 요청마다 결과(items)예요."""
    outs = [await cancel_one(tc, v, code, pid) for v in visits]
    states = [o.data.get("state") for o in outs]
    items = [{"vendor_name": v.vendor_name, **o.data} for v, o in zip(visits, outs, strict=True)]
    data = {
        "state": "new" if "new" in states else states[0],
        "count": len(items),
        "items": items,
        "note": CANCEL_MANY_NOTE,
    }
    return ToolOut(
        data=data,
        actions=[x for o in outs for x in o.actions],
        closed=[x for o in outs for x in o.closed],
    )


@tool(
    "propose_visit_cancel",
    surface="customer",
    kind="propose",
    status="실측 요청 취소를 준비하고 있어요",
    description="이미 보낸 실측 요청(m1…)을 취소하는 승인 카드를 만들어요. code는 고객이 말한 까닭: changed 일정이 "
    "바뀜 · other_vendor 다른 업체로 할래요, 까닭을 말하지 않았으면 other. 고객이 카드를 눌러야 취소되고 업체에도 "
    "알림이 가요(잡은 실측 날짜도 풀려요). visit_ref는 턴 사실 '업체:' 줄이나 requests의 이름표예요. 비우면 보낸 "
    "요청이 하나면 그 요청 카드, 여럿이면 이번 고객 말로 풀어요: 업체 이름이 나오면 그 요청 카드, '둘 다 · 모두'면 "
    "요청마다 카드(items), 못 풀면 카드 대신 고르기 칩(state choose, 한 턴에 한 번)이에요. 견적서가 온 뒤 · 확정 · "
    "이미 닫힌 요청은 카드 없이 까닭(state closed)을 돌려줘요. 아직 보내지 않은 실측 요청 카드는 withdraw_proposal로 "
    "거둬요.",
    model=VisitCancelIn,
    schema=obj(
        {
            "visit_ref": {
                "type": "string",
                "description": "실측 요청 이름표 m…(고객이 어느 요청인지 말하지 않았으면 비워요)",
            },
            "code": {"type": "string", "enum": list(actions.CANCEL_REASONS)},
        },
        required=["code"],
    ),
)
async def propose_visit_cancel(tc: ToolCtx, a: VisitCancelIn) -> ToolOut:
    from app.visit import service as visit_service

    pid = pid_of(tc)
    visit_id = uuid.UUID(tc.refs.get(a.visit_ref, "visit")["id"]) if a.visit_ref else None
    async with SessionLocal() as s:
        live = await cards.sent_visits(s, tc.user, pid)
        v = next((x for x in live if x.id == visit_id), None) if visit_id else None
        gone = (
            await visit_service.in_project(s, pid, visit_id)
            if visit_id is not None and v is None
            else None
        )
    if gone is not None:  # 닫힌 요청에는 카드를 만들지 않아요(QA r3 c4 #37)
        why = visit_service.ended_why(gone) or "지금 취소할 수 없는 요청이에요"
        return ToolOut(
            data={
                "state": "closed",
                "vendor_name": gone.vendor_name,
                "note": f"{why}. 카드를 만들지 않았어요.",
            }
        )
    if visit_id is None:
        if not live:
            return ToolOut(data={"state": "none", "note": CANCEL_NONE_NOTE})
        # 여럿이면 고객 말로 풀고(QA r4 s1 · s6), 못 풀면 어느 요청인지 물어요(QA r3 s6 B2)
        if len(live) > 1:
            picked = cancel_targets(live, tc.text)
            if not picked:
                return cancel_choose(tc, live)
            if len(picked) > 1:
                return await cancel_many(tc, picked, a.code, pid)
            v = picked[0]
        else:
            v = live[0]
    if v is None:  # 위에서 하나로 정해졌다(타입 검사용)
        raise ToolError("not_cancellable", "지금 취소할 수 있는 실측 요청이 없어요.")
    return await cancel_one(tc, v, a.code, pid)


# ---- 업체 ----


def _vendor_visit_id(tc: ToolCtx, ref: str) -> uuid.UUID:
    return uuid.UUID(tc.refs.get(ref, "visit")["id"])


class WindowAnswerIn(BaseModel):
    visit_ref: str
    window_ref: str


@tool(
    "propose_window_answer",
    surface="vendor",
    kind="propose",
    status="기간 답하기를 준비하고 있어요",
    description="요청(m1…)에 기간 후보(w1…)로 답하는 승인 카드를 만들어요.",
    model=WindowAnswerIn,
    schema=obj({"visit_ref": REF, "window_ref": REF}),
)
async def propose_window_answer(tc: ToolCtx, a: WindowAnswerIn) -> ToolOut:
    from app.visit import service as visit_service

    visit_id = _vendor_visit_id(tc, a.visit_ref)
    w = tc.refs.get(a.window_ref, "window")
    if w.get("visit_id") != str(visit_id):
        raise ToolError("mismatch", "이 요청의 기간 후보가 아니에요. 빈 기간을 다시 찾아 주세요.")
    async with SessionLocal() as s:
        d = await visit_service.vendor_visit(s, tc.user, visit_id, tc.today)
    if d.status != "requested":
        raise ToolError("stale", "이미 답했거나 닫힌 요청이에요.")
    instant = bool(d.instant_default)
    summary = ActionSummary(
        title="이 기간으로 답하기",
        rows=[
            SummaryRow(
                label="기간",
                value=cards.md_range(date.fromisoformat(w["start"]), date.fromisoformat(w["end"])),
            ),
            SummaryRow(
                label="빼는 날",
                value=cards.md_list(date.fromisoformat(x) for x in w.get("excluded") or [])
                or "없음",
            ),
            SummaryRow(label="빈 반나절", value=f"{w.get('open_count', 0)}칸"),
            SummaryRow(label="바로 확정", value="켜요" if instant else "꺼요"),
        ],
        note="답하면 고객이 그 기간에서 반나절을 골라요",
        approve_label="이 기간으로 답하기",
    )
    due = d.reply_due_at if d.reply_due_at and d.reply_due_at > tc.now else None
    out, _ = await _offer(
        tc,
        kind="window_answer",
        target_kind="visit",
        target_id=visit_id,
        target_ver=d.status,
        payload={
            "visit_id": str(visit_id),
            "start": w["start"],
            "end": w["end"],
            "excluded": list(w.get("excluded") or []),
            "instant": instant,
        },
        summary=summary,
        expires_at=due,
    )
    return out


class DeclineIn(BaseModel):
    visit_ref: str
    code: Literal["full", "out_of_area", "other"]


DECLINE = {"full": "일정이 꽉 찼어요", "out_of_area": "지역 밖이에요", "other": "그 밖의 까닭"}


@tool(
    "propose_decline",
    surface="vendor",
    kind="propose",
    status="못 받아요를 준비하고 있어요",
    description="요청(m1…)을 못 받는다고 알리는 승인 카드를 만들어요. code: full 일정 꽉 참 · "
    "out_of_area 지역 밖 · other 그 밖.",
    model=DeclineIn,
    schema=obj({"visit_ref": REF, "code": {"type": "string", "enum": list(DECLINE)}}),
)
async def propose_decline(tc: ToolCtx, a: DeclineIn) -> ToolOut:
    from app.visit import service as visit_service

    visit_id = _vendor_visit_id(tc, a.visit_ref)
    async with SessionLocal() as s:
        d = await visit_service.vendor_visit(s, tc.user, visit_id, tc.today)
    # visit.service.decline은 requested에서만 바꾼다(기간을 답한 뒤 카드를 만들면 승인해도 409)
    if d.status in ("offered", "picked", "proposed", "booked", "visited"):
        raise ToolError(
            "answered",
            "기간을 답한 뒤에는 못 받아요를 보낼 수 없어요. 고객과 믿집 채팅으로 이야기해 주세요.",
        )
    if d.status != "requested":
        raise ToolError("stale", "이미 닫혔거나 견적서를 보낸 요청이에요.")
    summary = ActionSummary(
        title="이번 요청 못 받아요",
        rows=[SummaryRow(label="까닭", value=DECLINE[a.code])],
        note="고객에게 까닭이 보이고 고객의 담기 칸이 비어요",
        approve_label="못 받는다고 알리기",
    )
    out, _ = await _offer(
        tc,
        kind="decline",
        target_kind="visit",
        target_id=visit_id,
        target_ver=d.status,
        payload={"visit_id": str(visit_id), "code": a.code},
        summary=summary,
        expires_at=tc.now + timedelta(days=2),
    )
    return out


class DatesPropose(BaseModel):
    deal_ref: str
    days_ref: str


def vendor_dates_offer(job, deal_id: uuid.UUID, days: dict, now) -> dict:
    """공사 날 후보 하나(job_for 결과 job · 이름표 값 days) → 공사 날짜 보내기 대기 행동 인자.
    도구 · 먼저 말 걸기가 같이 쓴다. 지금 낼 수 없으면 ToolError(stale)."""
    if job.dates_state not in ("waiting", "requested", "proposed"):
        raise ToolError("stale", "지금은 공사 날짜를 낼 수 없어요. 공사 화면에서 확인해 주세요.")
    picked = [date.fromisoformat(x) for x in days["days"]]
    summary = ActionSummary(
        title=f"공사 날짜 {cards.long_range(picked[0], picked[-1])} 보내기",
        rows=[
            # 주말 · 휴일을 건너뛴 날이 보이게
            SummaryRow(label="일하는 날", value=cards.day_list(picked)),
            SummaryRow(label="하루 인원", value=f"{days['crew']}명"),
            SummaryRow(label="다른 공사", value="우리 업체의 다른 공사 날은 피했어요"),
        ],
        note="고객이 수락하면 확정 공정표가 만들어져요",
        approve_label="이 날짜로 보내기",
    )
    due = job.dates_due_at if job.dates_due_at > now else now + timedelta(days=2)
    return {
        "kind": "dates",
        "target_kind": "deal",
        "target_id": deal_id,
        "target_ver": job.dates_state,
        "payload": {"deal_id": str(deal_id), "days": days["days"], "crew": days["crew"]},
        "summary": summary,
        "expires_at": due,
    }


@tool(
    "propose_dates",
    surface="vendor",
    kind="propose",
    status="공사 날짜 보내기를 준비하고 있어요",
    description="확정된 공사(d1…)에 공사 날 후보(n1…)를 보내는 승인 카드를 만들어요. 고객이 다른 날짜 · 날짜 "
    "바꾸기를 요청했으면 그 요청에 답하는 카드예요(후보는 고객이 고른 시작일).",
    model=DatesPropose,
    schema=obj({"deal_ref": REF, "days_ref": REF}),
)
async def propose_dates(tc: ToolCtx, a: DatesPropose) -> ToolOut:
    from app.assistant.tools import aftercare as aftercare_tools
    from app.schedule import service as schedule_service

    deal = tc.refs.get(a.deal_ref, "deal")
    days = tc.refs.get(a.days_ref, "days")
    if days.get("deal_id") != deal["id"]:
        raise ToolError("mismatch", "이 공사의 날짜 후보가 아니에요. 할 일을 다시 봐 주세요.")
    deal_id = uuid.UUID(deal["id"])
    async with SessionLocal() as s:
        job = await schedule_service.job_for(s, tc.user, deal_id, tc.today)
    if job.dates_state in ("requested", "change_requested") and job.request is not None:
        # 고객의 날짜 요청에 답한다: 먼저 말 걸기(dates_requested)와 같은 조건 · 같은 행동 값(kind · request_id).
        # 이름표 값의 kind 칸은 이름표 종류('days')라 쓰지 않고 공사 상태로 정한다
        kind = "change" if job.status == "scheduled" else "initial"
        days = {**days, "kind": kind}
        days.setdefault("request_id", str(job.request.id))
        offer = aftercare_tools.request_dates_offer(job, deal_id, days, tc.now)
    else:
        offer = vendor_dates_offer(job, deal_id, days, tc.now)
    out, _ = await _offer(tc, **offer)
    return out

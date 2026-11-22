"""프로젝트(집 정보) 만들기 · 보기 · 고치기.

표준견적서는 quote, 공정표는 schedule이 이 프로젝트를 읽어 만든다(rev가 바뀌면 새 버전).
v3: 몸통은 지금 화면(ProjectCreate)과 v3 기본 정보(HomeInfoIn, 손님 계산과 같은 칸) 둘 다 받는다.
손님 답 옮기기는 Idempotency-Key(= projects.client_key)로 한 번만 만든다(dev-03).
"""

import uuid
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.files import service as files_service
from app.project import diy
from app.project import repository as repo
from app.project.models import (
    CHECK_KEYS,
    CHECK_LABELS,
    FACES,
    SPACE_NAMES,
    Project,
    ProjectCheck,
    ProjectCondition,
    ProjectFile,
    ProjectSpace,
    ProjectTrade,
    ProjectTradeSpace,
)
from app.project.schemas import (
    ConditionOut,
    DiyOut,
    DobaeOut,
    EmdOut,
    HomeInfoIn,
    HomeInfoOut,
    MokgongOut,
    PhotoOut,
    ProjectBrief,
    ProjectCheckOut,
    ProjectCreate,
    ProjectListItem,
    ProjectOut,
    SizeIn,
    SpaceOut,
    TradesOut,
    WhenIn,
    check_home,
)
from app.shared.clock import now_utc
from app.shared.errors import AppError, app_error
from app.shared.ids import uuid7
from app.shared.regions import emd_list, is_region, region_label

LOCKED = "실측을 요청한 뒤에는 집 정보를 고칠 수 없어요."
Body = ProjectCreate | HomeInfoIn


async def _check(
    s: AsyncSession,
    owner: User,
    data: ProjectCreate,
    today: date,
    project_id: uuid.UUID | None = None,
) -> None:
    """만들기 · 고치기가 같이 쓰는 검사. 파일은 내가 올린 것, 종류가 맞는 것,
    다른 프로젝트에 안 붙은 것만(고칠 때는 이 프로젝트에 붙은 것은 괜찮다)."""
    if not is_region(data.sido, data.sgg):
        raise AppError(422, "region", "지역을 다시 골라 주세요.")
    if data.built_year is not None and data.built_year > today.year:
        raise AppError(422, "built_year", "준공 연도를 다시 확인해 주세요.")
    if data.when.start is not None and data.when.start < today:
        raise AppError(422, "past_date", "오늘 이후 날짜를 골라 주세요.")
    latest = date(today.year + 2, today.month, min(today.day, 28))
    if any(d is not None and d > latest for d in (data.when.start, data.when.end)):
        raise AppError(422, "far_date", "2년 안의 날짜를 골라 주세요.")
    photo_ids = [p.file_id for p in data.photos]
    files = await files_service.owned(s, owner.id, photo_ids + list(data.plans))
    if any(i not in files or files[i].kind != "photo" for i in photo_ids) or any(
        i not in files or files[i].kind != "plan" for i in data.plans
    ):
        raise AppError(422, "file", "올린 사진 · 도면을 다시 확인해 주세요.")
    ids = photo_ids + list(data.plans)
    used = (
        await repo.attached_file_ids(s, ids)
        if project_id is None
        else await repo.attached_elsewhere(s, ids, project_id)
    )
    if used:
        raise AppError(409, "file_used", "이미 다른 프로젝트에 붙인 파일이 있어요.")


def _fill(p: Project, data: ProjectCreate) -> None:
    p.sido = data.sido
    p.sgg = data.sgg
    p.house_type = data.house_type
    p.built_year = data.built_year
    p.size_band = data.size.band
    p.area_basis = data.size.basis
    p.area_m2 = data.size.m2
    p.balcony_ext = data.balcony_ext
    p.start_kind = data.when.kind
    p.start_date = data.when.start
    p.end_date = data.when.end
    p.occupied = data.occupied
    p.budget = data.budget
    p.emd = None  # v3 칸 (v2 몸통으로 고치면 v3 기본 정보가 없어진다)
    p.budget_won = None
    p.rooms = None


def _fill_home(p: Project, data: HomeInfoIn) -> None:
    """v3 기본 정보 → 프로젝트 칸. 면적은 ㎡ + 기준만, 희망일은 날짜 · 모름만 쓴다(data-model 3장)."""
    p.sido = data.sido
    p.sgg = data.sgg
    p.emd = data.emd
    p.house_type = data.housing
    p.built_year = None
    p.size_band = None
    p.area_basis = data.area_basis
    p.area_m2 = data.area_m2
    p.balcony_ext = False
    p.start_kind = "date" if data.start_date else "unknown"
    p.start_date = data.start_date
    p.end_date = None
    p.occupied = data.occupied
    p.budget = None
    p.budget_won = data.budget_won
    p.rooms = data.rooms


async def _write_home_parts(s: AsyncSession, p: Project, data: HomeInfoIn) -> None:
    """도배 공정 한 줄(범위 · 면 · 벽지) + 부분 공사면 고른 공간(종류)과 공정 × 공간 연결"""
    ids: list[uuid.UUID] = []
    for i, kind in enumerate(data.spaces):
        row = ProjectSpace(project_id=p.id, name=SPACE_NAMES[kind], sort=i, kind=kind)
        s.add(row)
        await s.flush()
        ids.append(row.id)
    s.add(
        ProjectTrade(
            project_id=p.id,
            trade=data.trade,
            items=[],
            grade=data.grade,
            scope=data.scope,
            faces=[f for f in FACES if f in data.faces],
        )
    )
    await s.flush()
    s.add_all([ProjectTradeSpace(project_id=p.id, trade=data.trade, space_id=i) for i in ids])


async def _write_parts(s: AsyncSession, p: Project, data: ProjectCreate) -> None:
    space_id: dict[str, uuid.UUID] = {}
    for i, sp in enumerate(data.spaces):
        row = ProjectSpace(project_id=p.id, name=sp.name, sort=i)
        s.add(row)
        await s.flush()
        space_id[sp.key] = row.id

    for trade, t in (("dobae", data.trades.dobae), ("mokgong", data.trades.mokgong)):
        if t is None:
            continue
        s.add(
            ProjectTrade(
                project_id=p.id,
                trade=trade,
                items=list(getattr(t, "items", [])),
                grade=getattr(t, "grade", None),
            )
        )
        await s.flush()
        s.add_all(
            [
                ProjectTradeSpace(project_id=p.id, trade=trade, space_id=space_id[k])
                for k in t.spaces
            ]
        )

    s.add_all(
        [
            ProjectFile(
                file_id=ph.file_id,
                project_id=p.id,
                space_id=space_id[ph.space],
                role="photo",
                sort=i,
            )
            for i, ph in enumerate(data.photos)
        ]
    )
    s.add_all(
        [
            ProjectFile(file_id=fid, project_id=p.id, space_id=None, role="plan", sort=i)
            for i, fid in enumerate(data.plans)
        ]
    )


async def _commit(s: AsyncSession) -> None:
    try:
        await s.commit()
    except IntegrityError as exc:  # 같은 사진으로 동시에 두 번 만들면 파일 PK가 막는다
        await s.rollback()
        if "uq_projects_client_key" in str(exc.orig):  # 같은 멱등 키 (잠금을 지나 온 드문 경우)
            raise app_error("in_progress") from exc
        raise AppError(409, "file_used", "이미 다른 프로젝트에 붙인 파일이 있어요.") from exc


async def _validate(
    s: AsyncSession,
    owner: User,
    data: Body,
    today: date,
    project_id: uuid.UUID | None = None,
) -> None:
    """몸통 모양에 맞춰 검사한다(v3: 지역 · 동 · 희망일, 지금 화면: 지역 · 날짜 · 파일)."""
    if isinstance(data, HomeInfoIn):
        check_home(data, today)
    else:
        await _check(s, owner, data, today, project_id)


async def _write(s: AsyncSession, p: Project, data: Body) -> None:
    """칸 · 공간 · 공정 · 파일을 쓴다 (고치기면 부르는 쪽이 먼저 지운다).
    v4 철거 범위는 모은 조건(demolition)에 둔다: 보낸 때만 쓰고(null이면 지움), 안 보내면 그대로.
    직접 할 일(diy 칩)도 모은 조건(diy.<키>)이다: 목록을 보낸 때만 덮어쓰고(빈 목록 = 없어요), null · 안 보냄은 그대로."""
    if isinstance(data, HomeInfoIn):
        _fill_home(p, data)
    else:
        _fill(p, data)
    s.add(p)
    await s.flush()
    if isinstance(data, HomeInfoIn):
        await _write_home_parts(s, p, data)
        if "demolition" in data.model_fields_set:
            await set_demolition(s, p.id, data.demolition)
        if data.diy is not None:
            await diy.set_diy(s, p.id, list(data.diy))
    else:
        await _write_parts(s, p, data)


async def set_demolition(s: AsyncSession, project_id: uuid.UUID, value: str | None) -> None:
    """철거 범위(모은 조건 demolition, 코드 값)를 덮어쓰거나(값) 지운다(None). 권한 · commit은 부르는 쪽."""
    from app.calc.dobae import DEMOLITION_KEY

    if value is None:
        await s.execute(
            delete(ProjectCondition).where(
                ProjectCondition.project_id == project_id, ProjectCondition.key == DEMOLITION_KEY
            )
        )
        return
    stmt = insert(ProjectCondition).values(
        id=uuid7(), project_id=project_id, trade="dobae", key=DEMOLITION_KEY, value=value
    )
    await s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_project_conditions_key",
            set_={"value": value, "trade": "dobae", "updated_at": func.now()},
        )
    )


async def create_once(
    s: AsyncSession, owner: User, data: Body, today: date, key: uuid.UUID | None = None
) -> tuple[ProjectOut, bool]:
    """공사 만들기. key(Idempotency-Key)가 같은 공사가 있으면 그 공사를 돌려준다(새로 만들지 않음).
    같은 키 요청이 아직 처리 중이면 409 in_progress. 돌려주는 값: (공사, 새로 만들었는지)."""
    if key is not None:
        got = await repo.by_client_key(s, owner.id, key)
        if got is None:
            if not await repo.try_key_lock(s, owner.id, key):
                raise app_error("in_progress")
            got = await repo.by_client_key(s, owner.id, key)  # 잠그는 사이 먼저 끝났을 수 있다
        if got is not None:
            return await _out(s, got), False
    await _validate(s, owner, data, today)
    no = await repo.next_code_no(s)
    v3 = isinstance(data, HomeInfoIn)
    source = ("guest" if key is not None else "member") if v3 else "v2"
    p = Project(
        owner_id=owner.id,
        code=f"MJ-{today:%y%m}-{no:04d}",
        source=source,
        client_key=key,
    )
    await _write(s, p, data)
    await _commit(s)
    return await _out(s, p), True


async def create(
    s: AsyncSession, owner: User, data: Body, today: date, key: uuid.UUID | None = None
) -> ProjectOut:
    return (await create_once(s, owner, data, today, key))[0]


async def update(
    s: AsyncSession, owner: User, project_id: uuid.UUID, data: Body, today: date
) -> ProjectOut:
    """집 정보 고치기: 실측을 요청하기 전까지만(뒤에는 409 locked). 공간 · 공정 · 파일은 통째로 바꾸고
    rev를 올린다(표준견적서 · 공정표가 새 버전이 된다). 만든 길(source)은 그대로 둔다."""
    p = await repo.get_for_update(s, project_id)
    if p is None or p.owner_id != owner.id:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    if p.locked_at is not None:
        raise app_error("locked", LOCKED)
    await _validate(s, owner, data, today, project_id)
    p.rev += 1
    await repo.clear_parts(s, p.id)
    await s.flush()
    await _write(s, p, data)
    await _commit(s)
    return await _out(s, p)


async def lock(s: AsyncSession, project_id: uuid.UUID) -> None:
    """프로젝트 행을 잠근다. 같은 집의 상태 변경은 프로젝트 → 요청 · 확정 행 → 제안 · 요청 행 순서로
    잠가 줄 선다(알림 insert의 project_id FK도 이 행을 잡으므로 먼저 잡는다). commit은 부르는 쪽이."""
    if await repo.get_for_update(s, project_id) is None:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")


async def lock_for_visit(
    s: AsyncSession, project_id: uuid.UUID, unit: tuple[str, str, str] | None = None
) -> Project:
    """실측 요청을 넣기 전에 부른다: 프로젝트 행을 잠그고(같은 프로젝트의 요청이 줄 선다),
    아직 안 잠겼으면 locked_at을 찍는다. 연락처를 보내면 아파트 이름 · 동 · 호수(unit)도 적는다.
    commit은 부르는 쪽이 한다."""
    p = await repo.get_for_update(s, project_id)
    if p is None:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    if p.locked_at is None:
        p.locked_at = now_utc()
    if unit is not None:
        p.apt_name, p.dong, p.ho = unit
    return p


async def unlock(s: AsyncSession, project_id: uuid.UUID) -> bool:
    """집 정보 잠금(locked_at)을 푼다. 보낸 실측 요청이 모두 끝났고(취소 · 못 받음 · 기한 지남 · 닫힘) 받은 견적서 ·
    확정이 없을 때 visit.service가 판정하고 부른다(QA r3 s1: 취소하면 집 정보를 다시 고칠 수 있어요). 풀었으면 True.
    rev는 그대로다(집 정보가 바뀐 것이 아니다). commit은 부르는 쪽이."""
    res = await s.execute(  # 같은 세션의 공사 객체도 맞춘다(기본 synchronize_session)
        sql_update(Project)
        .where(Project.id == project_id, Project.locked_at.is_not(None))
        .values(locked_at=None)
    )
    return res.rowcount == 1


def _size(p: Project) -> SizeIn:
    return SizeIn(band=p.size_band) if p.size_band else SizeIn(basis=p.area_basis, m2=p.area_m2)


def _home(
    p: Project, spaces: list, trades: list, links: list, demolition: str | None = None
) -> HomeInfoOut | None:
    """v3 기본 정보(넣은 그대로). v3 몸통으로 만든 공사만(source guest · member), v2 공사는 None.
    동은 비어 있을 수 있다(지금 화면은 시 · 군 · 구까지만 받는다). 철거 범위는 모은 조건 값."""
    t = next((t for t in trades if t.trade == "dobae"), None)
    if p.source == "v2" or t is None or p.area_m2 is None or p.area_basis is None:
        return None
    linked = {link.space_id for link in links if link.trade == "dobae"}
    return HomeInfoOut(
        trade=t.trade,
        scope=t.scope,
        spaces=[sp.kind for sp in spaces if sp.kind and sp.id in linked],
        faces=list(t.faces),
        rooms=p.rooms,
        housing=p.house_type,
        sido=p.sido,
        sgg=p.sgg,
        emd=p.emd,
        area_m2=p.area_m2,
        area_basis=p.area_basis,
        occupied=p.occupied,
        grade=t.grade,
        budget_won=p.budget_won,
        start_date=p.start_date,
        demolition=demolition if demolition in ("full", "partial", "none") else None,
    )


async def _out(s: AsyncSession, p: Project) -> ProjectOut:
    from app.calc.dobae import DEMOLITION_KEY

    spaces, trades, links, files = await repo.parts(s, p.id)
    demolition = await s.scalar(
        select(ProjectCondition.value).where(
            ProjectCondition.project_id == p.id, ProjectCondition.key == DEMOLITION_KEY
        )
    )
    tr = TradesOut()
    for t in trades:
        ids = [link.space_id for link in links if link.trade == t.trade]
        if t.trade == "dobae":
            tr.dobae = DobaeOut(spaces=ids, grade=t.grade)
        else:
            tr.mokgong = MokgongOut(spaces=ids, items=list(t.items))
    return ProjectOut(
        source=p.source,
        emd=p.emd,
        budget_won=p.budget_won,
        home=_home(p, spaces, trades, links, demolition),
        id=p.id,
        code=p.code,
        rev=p.rev,
        locked=p.locked_at is not None,
        sido=p.sido,
        sgg=p.sgg,
        region=region_label(p.sido, p.sgg),
        house_type=p.house_type,
        built_year=p.built_year,
        size=_size(p),
        balcony_ext=p.balcony_ext,
        when=WhenIn(kind=p.start_kind, start=p.start_date, end=p.end_date),
        occupied=p.occupied,
        budget=p.budget,
        spaces=[SpaceOut(id=sp.id, name=sp.name) for sp in spaces],
        trades=tr,
        photos=[
            PhotoOut(file_id=f.file_id, space_id=f.space_id) for f in files if f.role == "photo"
        ],
        plans=[f.file_id for f in files if f.role == "plan"],
        created_at=p.created_at,
    )


async def get_for(s: AsyncSession, user: User, project_id: uuid.UUID) -> ProjectOut:
    p = await repo.get(s, project_id)
    if p is None or (p.owner_id != user.id and user.role != "admin"):
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    return await _out(s, p)


def emds(sido: str, sgg: str) -> list[EmdOut]:
    """GET /regions/{sido}/{sgg}: 읍면동 목록(B6 자료, 법정동 코드 순). 자료가 없는 시 · 군 · 구는 404."""
    rows = emd_list(sido, sgg)
    if not rows:
        raise app_error("not_found", "동 목록이 없는 지역이에요.")
    return [EmdOut(name=r["name"], code=r["code"]) for r in rows]


async def get_out(s: AsyncSession, project_id: uuid.UUID) -> ProjectOut:
    """권한 확인 없이 읽는다. 업체 확정처럼 부르는 쪽이 이미 권한을 확인했을 때만 쓴다."""
    p = await repo.get(s, project_id)
    if p is None:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    return await _out(s, p)


async def list_mine(s: AsyncSession, user: User) -> list[ProjectListItem]:
    rows = await repo.list_by_owner(s, user.id)
    trades = await repo.trades_of(s, [p.id for p in rows])
    return [
        ProjectListItem(
            id=p.id,
            code=p.code,
            region=region_label(p.sido, p.sgg),
            size=_size(p),
            trades=sorted(trades[p.id]),
            created_at=p.created_at,
        )
        for p in rows
    ]


async def briefs(s: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProjectBrief]:
    """실측 요청을 받은 업체 쪽에 쓰는 집 요약 (권한은 부르는 쪽이 요청으로 확인한다)."""
    if not project_ids:
        return {}
    return {
        p.id: ProjectBrief(
            id=p.id,
            code=p.code,
            owner_id=p.owner_id,
            owner_name=name,
            owner_phone=phone,
            sido=p.sido,
            sgg=p.sgg,
            region=region_label(p.sido, p.sgg),
            occupied=p.occupied,
            when=WhenIn(kind=p.start_kind, start=p.start_date, end=p.end_date),
            apt_name=p.apt_name,
            dong=p.dong,
            ho=p.ho,
        )
        for p, name, phone in await repo.with_owners(s, project_ids)
    }


# ---- 공사 전에 할 일 체크 ----


async def checks(s: AsyncSession, project_id: uuid.UUID) -> list[ProjectCheckOut]:
    """체크 목록 (권한은 부르는 쪽이 먼저 확인한다)"""
    rows = {
        c.key: c
        for c in (
            await s.execute(select(ProjectCheck).where(ProjectCheck.project_id == project_id))
        ).scalars()
    }
    return [
        ProjectCheckOut(
            key=k,
            label=CHECK_LABELS[k],
            done=k in rows,
            done_at=rows[k].done_at if k in rows else None,
        )
        for k in CHECK_KEYS
    ]


async def set_check(
    s: AsyncSession, user: User, project_id: uuid.UUID, key: str, done: bool
) -> list[ProjectCheckOut]:
    """체크 켜기 · 끄기 (만든 고객만). 두 번 켜도 한 줄(PK), 없는 것을 꺼도 그대로."""
    p = await get_for(s, user, project_id)
    if user.role != "customer":
        raise AppError(403, "forbidden", "고객만 체크할 수 있어요.")
    if done:
        await s.execute(
            insert(ProjectCheck)
            .values(project_id=p.id, key=key, by_id=user.id)
            .on_conflict_do_nothing(index_elements=["project_id", "key"])
        )
    else:
        await s.execute(
            delete(ProjectCheck).where(ProjectCheck.project_id == p.id, ProjectCheck.key == key)
        )
    await s.commit()
    return await checks(s, p.id)


# ---- v3 모은 조건(맥락 L3, docs/v3/agent-context.md 3절) ----
async def _own(s: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    """만든 고객만(남의 것 · 없는 것은 같은 404)."""
    p = await repo.get(s, project_id)
    if p is None or p.owner_id != user.id:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")


async def conditions(s: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """{칸: 값}. 에이전트 사실(ProjectFacts.brief)로 넘겨요. 권한은 부르는 쪽이 get_for로 먼저 확인한다."""
    rows = await s.execute(
        select(ProjectCondition.key, ProjectCondition.value).where(
            ProjectCondition.project_id == project_id
        )
    )
    return {k: v for k, v in rows}


DIY_LABEL = "직접 할 일"  # 모은 조건 칩 '직접 할 일: 페인트(문틀 · 몰딩)'
DIY_NONE = "없어요"


def _chip(key: str, value: str) -> tuple[str, str]:
    """모은 조건 한 칸 → 칩 (이름, 값). 코드 값 칸(철거 범위 · 직접 할 일)은 화면 말로 바꾼다."""
    from app.agent.v3.trades import slot_label
    from app.calc.dobae import DEMOLITION, DEMOLITION_KEY

    if key == DEMOLITION_KEY:
        return slot_label(key), DEMOLITION.get(value, value)
    if key.startswith(diy.PREFIX):
        return DIY_LABEL, diy.DIY.get(key.removeprefix(diy.PREFIX), DIY_NONE)
    return slot_label(key), value


async def condition_list(s: AsyncSession, user: User, project_id: uuid.UUID) -> list[ConditionOut]:
    """화면 칩 목록(만든 고객만, 먼저 모은 것부터). 코드 값 칸(철거 범위 · 직접 할 일)은 화면 말로 바꿔 보여 준다."""
    await _own(s, user, project_id)
    rows = await s.scalars(
        select(ProjectCondition)
        .where(ProjectCondition.project_id == project_id)
        .order_by(ProjectCondition.updated_at, ProjectCondition.key)
    )
    out = []
    for r in rows:
        label, value = _chip(r.key, r.value)
        out.append(ConditionOut(trade=r.trade, key=r.key, label=label, value=value))
    return out


async def put_diy(s: AsyncSession, user: User, project_id: uuid.UUID, keys: list[str]) -> DiyOut:
    """직접 할 일 칩 덮어쓰기(만든 고객만, 남의 것 · 없는 것은 같은 404). 고객이 직접 누른 입력이라 승인 카드 없이
    저장하고, 집 정보 rev는 그대로다(벽지 직접 구매만 표준견적서 도배지 줄을 바꾸고, 그건 quote.service가 own_paper로
    새 판을 쌓는다). 같은 공사 요청은 프로젝트 행 잠금으로 줄 선다.
    확정 전 실측 요청의 '업체에 알릴 것' 사본도 같은 트랜잭션에서 맞추고 업체에 알린다(QA r2 c2 리드 결정).
    visit은 위층이라 함수 안에서 늦게 import한다(/me의 vendor.repository와 같은 꼴의 예외)."""
    from app.shared.clock import now_utc
    from app.visit import flow

    p = await repo.get_for_update(s, project_id)
    if p is None or p.owner_id != user.id:
        raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    picked = await diy.set_diy(s, project_id, keys)
    synced = await flow.sync_diy(s, project_id, picked, now_utc())
    await s.commit()
    return DiyOut(diy=picked, told=synced.told, notice=synced.note)


async def save_condition(
    s: AsyncSession, user: User, project_id: uuid.UUID, *, trade: str, key: str, value: str
) -> None:
    """고객이 되묻기에 답한 값 한 칸을 덮어써요. commit은 부르는 쪽(대화 저장과 같은 트랜잭션)이 해요."""
    await _own(s, user, project_id)
    v = (value or "").strip()[:40]
    if not v or not 3 <= len(key) <= 40:
        return
    stmt = insert(ProjectCondition).values(
        id=uuid7(), project_id=project_id, trade=trade[:20], key=key, value=v
    )
    await s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_project_conditions_key",
            set_={"value": v, "trade": trade[:20], "updated_at": func.now()},
        )
    )


async def delete_condition(
    s: AsyncSession, user: User, project_id: uuid.UUID, key: str
) -> list[ConditionOut]:
    """칩 X: 그 칸을 지우면 에이전트가 다음에 다시 물어요. 없는 칸을 지워도 그대로예요."""
    await _own(s, user, project_id)
    await s.execute(
        delete(ProjectCondition).where(
            ProjectCondition.project_id == project_id, ProjectCondition.key == key
        )
    )
    await s.commit()
    return await condition_list(s, user, project_id)

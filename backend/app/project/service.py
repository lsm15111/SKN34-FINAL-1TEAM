"""프로젝트 만들기 · 보기.

예상 공정표 · 표준견적서 · 추천은 다음 단계(계산 엔진 이식 · 워커)에서 이 프로젝트를 읽어 만든다.
"""

import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.files import service as files_service
from app.project import repository as repo
from app.project.models import Project, ProjectFile, ProjectSpace, ProjectTrade, ProjectTradeSpace
from app.project.schemas import (
    DobaeOut,
    MokgongOut,
    PhotoOut,
    ProjectCreate,
    ProjectListItem,
    ProjectOut,
    SizeIn,
    SpaceOut,
    TradesOut,
    WhenIn,
)
from app.shared.errors import AppError
from app.shared.regions import is_region, region_label


async def create(s: AsyncSession, owner: User, data: ProjectCreate, today: date) -> ProjectOut:
    if not is_region(data.sido, data.sgg):
        raise AppError(422, "region", "지역을 다시 골라 주세요.")
    if data.built_year is not None and data.built_year > today.year:
        raise AppError(422, "built_year", "준공 연도를 다시 확인해 주세요.")
    if data.when.start is not None and data.when.start < today:
        raise AppError(422, "past_date", "오늘 이후 날짜를 골라 주세요.")
    latest = date(today.year + 2, today.month, min(today.day, 28))
    if any(d is not None and d > latest for d in (data.when.start, data.when.end)):
        raise AppError(422, "far_date", "2년 안의 날짜를 골라 주세요.")

    # 파일: 내가 올린 것, 종류가 맞는 것, 아직 다른 프로젝트에 안 붙은 것만
    photo_ids = [p.file_id for p in data.photos]
    files = await files_service.owned(s, owner.id, photo_ids + list(data.plans))
    if any(i not in files or files[i].kind != "photo" for i in photo_ids) or any(
        i not in files or files[i].kind != "plan" for i in data.plans
    ):
        raise AppError(422, "file", "올린 사진 · 도면을 다시 확인해 주세요.")
    if await repo.attached_file_ids(s, photo_ids + list(data.plans)):
        raise AppError(409, "file_used", "이미 다른 프로젝트에 붙인 파일이 있어요.")

    p = Project(
        owner_id=owner.id,
        sido=data.sido,
        sgg=data.sgg,
        house_type=data.house_type,
        built_year=data.built_year,
        size_band=data.size.band,
        area_basis=data.size.basis,
        area_m2=data.size.m2,
        balcony_ext=data.balcony_ext,
        start_kind=data.when.kind,
        start_date=data.when.start,
        end_date=data.when.end,
        occupied=data.occupied,
        budget=data.budget,
    )
    s.add(p)
    await s.flush()

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
    try:
        await s.commit()
    except IntegrityError as exc:  # 같은 사진으로 동시에 두 번 만들면 파일 PK가 막는다
        await s.rollback()
        raise AppError(409, "file_used", "이미 다른 프로젝트에 붙인 파일이 있어요.") from exc
    return await _out(s, p)


def _size(p: Project) -> SizeIn:
    return SizeIn(band=p.size_band) if p.size_band else SizeIn(basis=p.area_basis, m2=p.area_m2)


async def _out(s: AsyncSession, p: Project) -> ProjectOut:
    spaces, trades, links, files = await repo.parts(s, p.id)
    tr = TradesOut()
    for t in trades:
        ids = [link.space_id for link in links if link.trade == t.trade]
        if t.trade == "dobae":
            tr.dobae = DobaeOut(spaces=ids, grade=t.grade)
        else:
            tr.mokgong = MokgongOut(spaces=ids, items=list(t.items))
    return ProjectOut(
        id=p.id,
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


async def list_mine(s: AsyncSession, user: User) -> list[ProjectListItem]:
    rows = await repo.list_by_owner(s, user.id)
    trades = await repo.trades_of(s, [p.id for p in rows])
    return [
        ProjectListItem(
            id=p.id,
            region=region_label(p.sido, p.sgg),
            size=_size(p),
            trades=sorted(trades[p.id]),
            created_at=p.created_at,
        )
        for p in rows
    ]

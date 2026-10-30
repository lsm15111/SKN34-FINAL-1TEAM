import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.project.models import Project, ProjectFile, ProjectSpace, ProjectTrade, ProjectTradeSpace


async def attached_file_ids(s: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(
        (await s.execute(select(ProjectFile.file_id).where(ProjectFile.file_id.in_(ids)))).scalars()
    )


async def get(s: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await s.get(Project, project_id)


async def list_by_owner(s: AsyncSession, owner_id: uuid.UUID) -> list[Project]:
    q = select(Project).where(Project.owner_id == owner_id).order_by(Project.created_at.desc())
    return list((await s.execute(q)).scalars())


async def parts(s: AsyncSession, project_id: uuid.UUID):
    spaces = list(
        (
            await s.execute(
                select(ProjectSpace)
                .where(ProjectSpace.project_id == project_id)
                .order_by(ProjectSpace.sort)
            )
        ).scalars()
    )
    trades = list(
        (
            await s.execute(select(ProjectTrade).where(ProjectTrade.project_id == project_id))
        ).scalars()
    )
    links = list(
        (
            await s.execute(
                select(ProjectTradeSpace).where(ProjectTradeSpace.project_id == project_id)
            )
        ).scalars()
    )
    files = list(
        (
            await s.execute(
                select(ProjectFile)
                .where(ProjectFile.project_id == project_id)
                .order_by(ProjectFile.sort)
            )
        ).scalars()
    )
    return spaces, trades, links, files


async def trades_of(s: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {i: [] for i in project_ids}
    if project_ids:
        for pid, t in (
            await s.execute(
                select(ProjectTrade.project_id, ProjectTrade.trade).where(
                    ProjectTrade.project_id.in_(project_ids)
                )
            )
        ).all():
            out[pid].append(t)
    return out

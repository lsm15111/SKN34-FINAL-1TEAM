"""QA 도구(qa.py)의 프로세스 안 일. worker와 같은 설정으로 돌아요: bash .claude/run-qa-worker.sh <qa|dev> once <명령> ...

- tick <시작 ISO> <끝 ISO> [<몇 시간마다>]: 그 사이 매시간 5분(worker의 assistant_hourly 때, 기본 1시간마다)과
  끝 시각에 기한 일(app/run_due.py와 같은 worker.sweep 되풀이) → assistant_hourly → assistant_sweep를 차례로
  돌려요. 시작 = 끝이면 끝 시각에 한 번만이에요. 실제 시계 · 행의 기한은 바꾸지 않아요.
- vendor <업체 이름 | 이메일> <세션 파일> [<비밀번호를 아는 이메일,…>]: 승인된 업체를 찾아요. 비밀번호를 모르는
  업체면 로그인과 같은 세션 함수(auth.service.start_session)로 세션을 만들어 파일에만 써요(화면 · 출력에 없음).
- done <업체 이메일> <확정 id> <오늘 YYYY-MM-DD> [<남길 말>]: 업체 '공사 끝냈어요'를 '오늘 + 시간 당긴 만큼'으로
  (schedule.service.finish, 라우터와 같은 신호 처리). 마지막 공사일이 지나야 되는 일이라 API(실제 오늘)로는 못 해요.
- cost: 비용 장부(llm_usage) 합. make_db.sh가 복사 때 장부를 비워서 QA 비용만 나와요.
결과는 마지막 줄 'QA-JSON: {…}' 하나예요. QA DB(mitjip_qa · mitjip_qa_dev)가 아니면 아무것도 하지 않아요.
"""

import asyncio
import contextlib
import json
import os
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.environ.get("QA_BACKEND") or str(Path.cwd()))

QA_DBS = ("mitjip_qa", "mitjip_qa_dev")
STEP_MINUTE = 5  # worker cron: assistant_hourly는 매시간 5분
MAX_STEPS = 24 * 31  # 한 번에 31일까지


def out(obj: dict) -> None:
    print("QA-JSON: " + json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def guard() -> None:
    from sqlalchemy.engine import make_url

    from app.config import settings

    if make_url(settings.database_url).database not in QA_DBS:
        out({"error": {"code": "not_qa_db", "message": "QA DB가 아니라 멈췄어요."}})
        raise SystemExit(2)


def steps(start: datetime, end: datetime, every: int = 1) -> list[datetime]:
    """start 뒤 ~ end의 every시간마다 5분, 그리고 end. start = end면 [end]."""
    got: list[datetime] = []
    t = start.replace(minute=STEP_MINUTE, second=0, microsecond=0)
    if t <= start:
        t += timedelta(hours=1)
    while t < end and len(got) < MAX_STEPS:
        got.append(t)
        t += timedelta(hours=every)
    return [*got, end]


async def tick(start: datetime, end: datetime, every: int = 1) -> dict:
    from app import run_due
    from app.assistant import service as assistant

    jobs: Counter[str] = Counter()
    hourly: Counter[str] = Counter()
    sweep: Counter[str] = Counter()
    times = steps(start, end, every)
    for t in times:
        for (kind, result), n in (await run_due.run(t)).items():
            jobs[f"{kind}:{result}"] += n
        hourly.update({k: v for k, v in (await assistant.hourly(t)).items() if v})
        sweep.update({k: v for k, v in (await assistant.sweep(t)).items() if v})
    return {"steps": len(times), "jobs": dict(jobs), "hourly": dict(hourly), "sweep": dict(sweep)}


async def vendor(ref: str, secret: str, known: set[str]) -> dict:
    from sqlalchemy import func, or_, select

    from app.auth import service as auth
    from app.auth.models import User
    from app.db import SessionLocal
    from app.vendor.models import Vendor

    async with SessionLocal() as s:
        q = (
            select(User, Vendor)
            .join(Vendor, Vendor.user_id == User.id)
            .where(or_(Vendor.biz_name == ref, func.lower(User.email) == ref.lower()))
        )
        row = (await s.execute(q)).first()
        if row is None:
            return {"error": {"code": "not_found", "message": f"업체를 못 찾았어요: {ref}"}}
        user, v = row
        if v.status != "approved" or user.role != "vendor" or user.status != "active":
            return {"error": {"code": "not_approved", "message": "승인된 업체가 아니에요."}}
        got = {"email": user.email, "name": v.biz_name, "id": str(user.id), "how": "password"}
        if user.email.lower() not in known:
            token = await auth.start_session(s, user)
            await s.commit()
            Path(secret).parent.mkdir(parents=True, exist_ok=True)
            Path(secret).write_text(json.dumps({"token": token}), encoding="utf-8")
            got["how"] = "session"
        return got


async def done(email: str, deal_id: str, today: date, note: str | None) -> dict:
    from sqlalchemy import select

    from app.auth.models import User
    from app.db import SessionLocal
    from app.schedule import service as schedule
    from app.schedule.schemas import DoneIn
    from app.shared.errors import AppError
    from app.vendor.models import Vendor

    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == email))
        v = await s.get(Vendor, user.id) if user else None
        if user is None or v is None or v.status != "approved":
            return {"error": {"code": "not_approved", "message": "승인된 업체가 아니에요."}}
        try:
            job = await schedule.finish(s, user, uuid.UUID(deal_id), today, DoneIn(note=note))
        except AppError as e:
            schedule.drop_later(s)
            return {"error": {"code": e.code, "message": e.message}}
        except Exception:
            schedule.drop_later(s)
            raise
        await schedule.flush_later(s)
        return {
            "status": job.status,
            "work_done_on": job.work_done_on,
            "auto_done_at": job.auto_done_at,
            "today": today,
        }


async def cost() -> dict:
    from sqlalchemy import text

    from app.db import SessionLocal

    async with SessionLocal() as s:
        total = (
            await s.execute(text("select count(*), coalesce(sum(cost_micros), 0) from llm_usage"))
        ).one()
        by_purpose = (
            await s.execute(
                text(
                    "select purpose, model, count(*), sum(cost_micros), count(*) filter (where not ok)"
                    " from llm_usage group by 1, 2 order by 4 desc"
                )
            )
        ).all()
        by_user = (
            await s.execute(
                text(
                    "select coalesce(u.email, '(사람 없음)'), coalesce(u.role, '-'), count(*),"
                    " sum(l.cost_micros) from llm_usage l left join users u on u.id = l.user_id"
                    " group by 1, 2 order by 4 desc"
                )
            )
        ).all()
    return {
        "calls": total[0],
        "usd": int(total[1]) / 1e6,
        "by_purpose": [
            {"purpose": p, "model": m, "calls": n, "usd": int(c) / 1e6, "failed": f}
            for p, m, n, c, f in by_purpose
        ],
        "by_user": [
            {"email": e, "role": r, "calls": n, "usd": int(c) / 1e6} for e, r, n, c in by_user
        ],
    }


async def main(argv: list[str]) -> dict:
    from app import db, queue

    guard()
    cmd = argv[0] if argv else ""
    try:
        if cmd == "tick":
            every = int(argv[3]) if len(argv) > 3 else 1
            return await tick(
                datetime.fromisoformat(argv[1]), datetime.fromisoformat(argv[2]), every
            )
        if cmd == "vendor":
            known = {x.strip().lower() for x in (argv[3] if len(argv) > 3 else "").split(",") if x}
            return await vendor(argv[1], argv[2], known)
        if cmd == "done":
            note = argv[4] if len(argv) > 4 and argv[4] else None
            return await done(argv[1], argv[2], date.fromisoformat(argv[3]), note)
        if cmd == "cost":
            return await cost()
        return {"error": {"code": "bad_cmd", "message": f"모르는 명령이에요: {cmd}"}}
    finally:  # 이 실행의 이벤트 루프에서 연 연결을 닫아요(run_due와 같음)
        await db.engine.dispose()
        with contextlib.suppress(Exception):
            await queue.redis.connection_pool.disconnect()


if __name__ == "__main__":
    out(asyncio.run(main(sys.argv[1:])))
